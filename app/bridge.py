import logging
import json
from threading import RLock

from .config import read_settings
from .device import MaaDevice
from .inventory import ManualInventory, active_inventory_paths
from .config import ROOT
from .worker import OperationCancelled, SerialWorker

logger = logging.getLogger("m4b")


class Bridge:
    def __init__(self, *, offline=False, read_only=False, manual_inventory=False, inventory_capture=False, device=None, worker=None):
        self._offline = offline or (manual_inventory and not inventory_capture)
        self._read_only = read_only or manual_inventory or inventory_capture
        self._inventory_capture = inventory_capture
        self._manual_inventory = manual_inventory or inventory_capture
        self._inventory = ManualInventory(**active_inventory_paths(ROOT)) if self._manual_inventory else None
        self._ocr = None
        self._reset_requested = False
        self._reset_version = 0
        self._device = device if device is not None else MaaDevice(read_only=self._read_only, allow_inventory_swipe=inventory_capture)
        self._auto_capture = None
        self._worker = worker if worker is not None else SerialWorker()
        self._lock = RLock()
        self._status = "disconnected"
        self._message = "尚未连接模拟器"
        self._frame = None
        self._settings = read_settings()
        if self._inventory_capture and (self._inventory.directory / "progress.json").exists():
            self._auto_capture = json.loads((self._inventory.directory / "progress.json").read_text(encoding="utf-8"))
            if self._auto_capture.get("phase") in ("starting", "rewinding", "capturing"):
                self._auto_capture.update(phase="stopped", message="上次自动采集中断，尚未完成；不会自动恢复")
        if self._inventory and self._inventory.groups and self._inventory.shots:
            filename = self._inventory.groups[-1]["selected"]
            if filename in self._inventory.shots:
                from PIL import Image
                with Image.open(self._inventory._image_path(filename)) as source:
                    width, height = source.size
                self._frame = {"data": self._inventory.preview(filename), "frame_id": "restored-" + filename,
                               "width": width, "height": height, "time": "已保存截图",
                               "inventory_shot": filename}

    def get_state(self, last_frame_id=""):
        with self._lock:
            self._process_reset()
            frame = dict(self._frame) if self._frame else None
            if frame and frame["frame_id"] == last_frame_id:
                frame.pop("data", None)
            return {
                "status": self._status,
                "message": self._message,
                "busy": self._worker.busy,
                "stopped": self._worker.stopped,
                "offline": self._offline,
                "read_only": self._read_only,
                "manual_inventory": self._manual_inventory,
                "inventory_capture": self._inventory_capture,
                "inventory_automation": self._inventory_capture,
                "auto_capture": dict(self._auto_capture) if self._auto_capture else None,
                "reset_version": self._reset_version,
                "inventory": self._inventory.snapshot() if self._inventory else None,
                "frame": frame,
                "settings": self._settings,
            }

    def connect(self, adb_path, address):
        if self._offline:
            return {"ok": False, "error": "当前为离线检查模式，设备连接已禁用"}
        try:
            MaaDevice.validate_connection(adb_path, address)
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": str(error)}
        return self._submit("connect", lambda token: self._device.connect(adb_path, address, token), resume=True)

    def inventory_action(self, action, *args):
        with self._lock:
            if not self._inventory:
                return {"ok": False, "error": "请用手动背包统计模式打开应用"}
            try:
                if action == "reset":
                    self._reset_requested = True
                    self._worker.stop()
                    self._process_reset()
                    return {"ok": True, "inventory": self._inventory.snapshot()}
                if self._worker.busy:
                    raise ValueError("正在截图或识别，请稍候再修改记录")
                methods = {"import": self._inventory.import_image, "preview": self._inventory.preview,
                           "add": self._inventory.add, "update": self._inventory.update,
                           "cell": self._inventory.update_cell,
                           "remove": self._inventory.remove, "finish": self._inventory.finish,
                           "review": self._inventory.review, "restore": self._inventory.restore}
                if action in ("invalidate_many", "restore_many"):
                    if len(args) != 1 or not isinstance(args[0], dict) or set(args[0]) != {"indexes"}:
                        raise ValueError("批量操作必须提供选中的行编号")
                    self._inventory.set_invalid_many(args[0]["indexes"], action == "invalidate_many")
                    return {"ok": True, "inventory": self._inventory.snapshot()}
                if action not in methods:
                    raise ValueError("未知记录操作")
                result = methods[action](*args)
                if action == "finish":
                    self._frame = None
                    self._ocr = None
                return {"ok": True, "inventory": self._inventory.snapshot(),
                        "image": result if action in ("import", "preview") else None}
            except Exception as error:
                logger.exception("手动背包记录失败：%s", action)
                return {"ok": False, "error": str(error)}

    def _process_reset(self):
        if not self._inventory:
            return
        directory = self._inventory.root / "runtime/manual-inventory"
        request = directory / "reset-request.json"
        request_id = None
        if request.exists():
            request_id = json.loads(request.read_text(encoding="utf-8"))["id"]
            self._reset_requested = True
        if not self._reset_requested:
            return
        self._worker.stop()
        self._status = "stopped"
        self._message = "正在停止截图/识别，随后重置本轮记录"
        if self._worker.busy:
            return
        try:
            counts = self._inventory.reset()
            self._reset_version += 1
            self._frame, self._ocr = None, None
            self._auto_capture = None
            self._status = "disconnected"
            self._message = "本轮识别记录和临时截图已清空；请重新连接后开始"
            result = {"id": request_id, "ok": True, "result": counts}
        except Exception as error:
            self._status = "error"
            self._message = "重置未完成：" + str(error)
            result = {"id": request_id, "ok": False, "error": str(error)}
        self._reset_requested = False
        if request_id:
            temporary = directory / "reset-result.tmp"
            temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            temporary.replace(directory / "reset-result.json")
            request.unlink(missing_ok=True)

    def screenshot(self):
        if self._inventory_capture:
            with self._lock:
                if self._inventory.phase != "draft":
                    return {"ok": False, "error": "本次记录已完成，不再采集截图"}
                if any(report["status"] == "pending" for report in self._inventory.ocr_reports.values()):
                    return {"ok": False, "error": "上一张截图仍待核对，请先核对，保持背包顺序"}
            return self._submit("screenshot", self._capture_inventory)
        return self._submit("screenshot", lambda token: self._device.screenshot(token))

    def auto_inventory(self, adb_path="", address=""):
        if not self._inventory_capture or self._offline:
            return {"ok": False, "error": "当前模式不支持自动背包采集"}
        reconnect = self._status != "connected" or self._worker.stopped
        if reconnect:
            adb_path = adb_path or self._settings["adb_path"]
            address = address or self._settings["address"]
            try:
                MaaDevice.validate_connection(adb_path, address)
            except (TypeError, ValueError) as error:
                return {"ok": False, "error": str(error)}
        def collect(token):
            from .bag_capture import BagCollector
            if reconnect:
                self._device.connect(adb_path, address, token)
            def notify(state, inventory, frame):
                with self._lock:
                    self._auto_capture = state
                    if self._inventory is not inventory:
                        self._reset_version += 1
                    self._inventory = inventory
                    self._message = state["message"]
                    if frame:
                        self._frame = frame
            collector = BagCollector(self._device, notify=notify)
            return collector.run(token)
        return self._submit("auto_inventory", collect, resume=reconnect)

    def _capture_inventory(self, token):
        from .ocr import LocalOcr
        attempts = []
        changed_page = False
        group_id = None
        baseline = None
        for attempt in range(3):
            token.check()
            # Capture failures/connection loss propagate; only OCR failures retry.
            frame = self._device.screenshot(token, save=False)
            with self._lock:
                if group_id is None:
                    group_id = token.dispatch(self._inventory.create_group)
                token.dispatch(lambda: self._inventory.import_image(frame["data"], group_id=group_id))
                filename = self._inventory.shots[-1]
                path = self._inventory._image_path(filename)
                signature = self._inventory_signature(path)
                if baseline is None:
                    baseline = signature
                elif not self._same_inventory_frame(baseline, signature):
                    changed_page = True
                frame = {**frame, "data": self._inventory.preview(filename), "inventory_shot": filename}
                token.dispatch(lambda: self._inventory.apply_ocr(filename, [], {
                    "rows": [], "status": "pending", "message": f"本地OCR第{attempt + 1}次处理中"}))
                self._frame = frame
                self._message = "截图已入库，正在本地OCR" if attempt == 0 else f"识别未完成，自动重截重识别 {attempt}/2"
            tokens = []
            if changed_page:
                parsed = {"rows": [], "status": "pending", "message": "重试时画面发生明显变化，已停止自动识别，请核对当前页"}
                attempts.append((filename, frame, tokens, parsed))
                with self._lock:
                    self._inventory.ocr_reports[filename] = {**parsed, "tokens": [], "attempt": attempt + 1}
                    self._inventory._save()
                break
            try:
                if self._ocr is None:
                    self._ocr = LocalOcr()
                tokens, parsed = self._ocr.read_inventory(self._inventory._image_path(filename), token)
            except OperationCancelled:
                raise
            except Exception as error:
                parsed = {"rows": [], "status": "pending", "message": "OCR失败，截图保留：" + str(error)}
            token.check()
            attempts.append((filename, frame, tokens, parsed))
            with self._lock:
                def save_attempt():
                    self._inventory.ocr_reports[filename] = {**parsed, "tokens": tokens, "status": "pending", "attempt": attempt + 1}
                    self._inventory._save()
                token.dispatch(save_attempt)
            if changed_page or parsed["status"] in ("recognized", "excluded"):
                break
        # Commit a single best frame; never append the same page three times or
        # combine fields from possibly different frames.
        candidates = attempts[:-1] if changed_page else attempts
        selected = max(candidates, key=lambda entry: sum(bool(row["name"]) + bool(row["quantity"]) for row in entry[3]["rows"]))
        filename, frame, tokens, parsed = selected
        if changed_page:
            parsed = {**parsed, "status": "pending", "message": "重试画面发生变化，已停止；仅保留变化前的单帧结果，请核对当前页"}
        else:
            # OCR spelling changes on a stable image are ambiguity, not proof of
            # navigation. Retry normally, but never silently choose a disputed value.
            parsed = self._clear_retry_conflicts(parsed, [entry[3] for entry in attempts])
        with self._lock:
            def commit():
                for other, _, _, _ in attempts:
                    if other != filename:
                        self._inventory.ocr_reports[other].update(status="superseded", message="本次重试过程图，未重复入表")
                report = self._inventory.apply_ocr(filename, tokens, parsed)
                report["attempts"] = len(attempts)
                self._inventory.select_group(group_id, filename)
                self._inventory._save()
                return report
            report = token.dispatch(commit)
        frame["inventory_message"] = report["message"] + f"；识别{len(attempts)}次，新增{report['added']}项"
        return frame

    @staticmethod
    def _inventory_signature(path):
        from PIL import Image, ImageFilter
        from .ocr import CONTENT_ROI
        with Image.open(path) as source:
            size = source.size
            if size == (630, 1120):
                x, y, width, height = CONTENT_ROI
                source = source.crop((x, y, x + width, y + height))
            small = source.convert("L").resize((64, 96)).filter(ImageFilter.GaussianBlur(.7))
            return size, tuple(small.getdata())

    @staticmethod
    def _same_inventory_frame(first, second):
        if first[0] != second[0]:
            return False
        differences = [abs(a - b) for a, b in zip(first[1], second[1])]
        # Coarse luminance ignores tiny badge sparkles, while scrolling or a
        # navigation overlay changes a broad portion of the scrollable area.
        return (sum(differences) / len(differences) <= 8
                and sum(value > 18 for value in differences) / len(differences) <= .15)

    @staticmethod
    def _clear_retry_conflicts(selected, results):
        rows = [dict(row) for row in selected["rows"]]
        conflicts = 0
        for index, row in enumerate(rows):
            slot = row.get("slot", index)
            for field in ("name", "quantity"):
                values = {other[field] for result in results for position, other in enumerate(result["rows"])
                          if other.get("slot", position) == slot and other.get(field)}
                if len(values) > 1:
                    row[field] = ""
                    conflicts += 1
        if conflicts:
            return {**selected, "rows": rows, "status": "pending", "retry_conflicts": conflicts,
                    "message": f"同一画面多次OCR有{conflicts}个字段不一致，已留空待核对；未拼接不同截图"}
        return selected

    def click(self, x, y):
        if self._read_only:
            return {"ok": False, "error": "只读模式禁止点击"}
        try:
            point = self._point(x, y)
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": str(error)}
        return self._submit("click", lambda token: self._device.click(*point, token))

    def swipe(self, x1, y1, x2, y2, duration):
        if self._read_only:
            return {"ok": False, "error": "只读模式禁止滑动"}
        try:
            first = self._point(x1, y1)
            second = self._point(x2, y2)
            duration = self._integer(duration)
            if not 100 <= duration <= 3000:
                raise ValueError("滑动时长须为100–3000毫秒")
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": str(error)}
        return self._submit("swipe", lambda token: self._device.swipe(*first, *second, duration, token))

    def stop(self):
        # A quick path, never enqueued behind the operation being stopped.
        self._worker.stop()
        with self._lock:
            self._status = "stopped"
            self._message = "已停止；已发出的单次动作需核对，后续指令已阻止"
        logger.info("用户停止")
        return {"ok": True}

    def _submit(self, kind, action, *, resume=False):
        if self._offline:
            return {"ok": False, "error": "离线检查模式不允许设备操作"}
        with self._lock:
            if not resume and self._status != "connected":
                return {"ok": False, "error": "请先手动连接模拟器"}
            try:
                future = self._worker.submit(action, resume=resume)
            except (RuntimeError, OperationCancelled) as error:
                return {"ok": False, "error": str(error)}
            self._status = "connecting" if kind == "connect" else "connected"
            self._message = {"connect": "正在连接", "screenshot": "正在截图", "click": "正在点击", "swipe": "正在滑动", "auto_inventory": "正在启动自动背包采集"}[kind]
            if kind in ("connect", "screenshot", "click", "swipe"):
                self._frame = None
        future.add_done_callback(lambda result: self._completed(kind, result))
        return {"ok": True}

    def _completed(self, kind, future):
        try:
            result = future.result()
        except OperationCancelled:
            with self._lock:
                self._status = "stopped"
                self._message = "操作已停止；请手动核对后重新连接"
        except Exception as error:
            logger.exception("操作失败：%s", kind)
            with self._lock:
                self._status = "error"
                self._message = str(error)
                self._frame = None
        else:
            with self._lock:
                if self._worker.stopped:
                    return
                self._status = "connected"
                if kind in ("screenshot", "auto_inventory"):
                    self._frame = result
                    self._message = (self._auto_capture["message"] if kind == "auto_inventory" and self._auto_capture
                                     else result.get("inventory_message", "截图已更新，请核对当前页面"))
                else:
                    self._message = result["message"]
            logger.info("操作完成：%s", kind)

    @staticmethod
    def _integer(value):
        if isinstance(value, bool):
            raise ValueError("坐标和时长必须是整数")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("坐标和时长必须是整数")
        try:
            integer = int(value)
        except (ValueError, TypeError, OverflowError):
            raise ValueError("坐标和时长必须是整数") from None
        if isinstance(value, str) and str(integer) != value.strip():
            raise ValueError("坐标和时长必须是整数")
        return integer

    def _point(self, x, y):
        x, y = self._integer(x), self._integer(y)
        with self._lock:
            if not self._frame:
                raise ValueError("请先截图确认实际画面尺寸")
            if not (0 <= x < self._frame["width"] and 0 <= y < self._frame["height"]):
                raise ValueError("坐标超出最新截图范围")
        return x, y

    def shutdown(self):
        self._worker.close()

