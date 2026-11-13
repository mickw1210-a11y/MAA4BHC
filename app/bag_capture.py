"""Bounded, local-only backpack scrolling for the locked 630x1120 layout."""
import base64
import json
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from .bag_alignment import estimate_vertical_shift
from .config import ROOT
from .inventory import ManualInventory
from .ocr import LocalOcr
from .worker import OperationCancelled


class BagCollector:
    def __init__(self, device, *, root=ROOT, notify=None, ocr=None, pause=None):
        self.root = Path(root).resolve()
        name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        self.directory = self.root / "runtime/auto-inventory" / name
        self.directory.mkdir(parents=True)
        self.inventory = ManualInventory(self.root, directory=self.directory,
                                         output=self.directory / "inventory.csv")
        self.device = device
        self.ocr = ocr or LocalOcr()
        self.notify = notify or (lambda state, inventory, frame: None)
        self.pause = pause or self._pause
        self.status = {"phase": "starting", "pages": 0, "message": "检查背包与分辨率",
                       "directory": self.directory.relative_to(self.root).as_posix(),
                       "capture_complete": False}
        self.actions = []
        self.number = 0
        self.frame = None

    @staticmethod
    def _pause(seconds, token):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            token.check()
            time.sleep(min(.05, max(0, end - time.monotonic())))

    def _publish(self, phase, message):
        self.status.update(phase=phase, message=message)
        state = {**self.status, "actions": self.actions}
        temporary = self.directory / "progress.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.directory / "progress.json")
        self.notify(dict(self.status), self.inventory, self.frame)

    def _capture(self, token, label):
        token.check()
        frame = self.device.screenshot(token, save=False)
        if (frame["width"], frame["height"]) != (630, 1120):
            raise RuntimeError("分辨率变化，自动操作已停止；只支持630×1120")
        self.number += 1
        path = self.directory / f"frame-{self.number:03d}-{label}.png"
        token.dispatch(lambda: path.write_bytes(base64.b64decode(frame["data"].split(",", 1)[1])))
        self.inventory.capture_files.append(path.name)
        token.dispatch(self.inventory._save)
        self.frame = frame
        return path, frame

    def _assert_bag(self, path, token):
        header = self.ocr.read(path, token, roi=(24, 0, 584, 150))
        if not any(value["score"] >= .9 and value["text"].strip() == "背包" for value in header):
            raise RuntimeError("未确认背包页面，已停止自动操作")
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"), dtype=float)
        votes = []
        for left in (24, 225, 415):
            tile = pixels[100:150, left:left + 175]
            red, green, blue = tile[:, :, 0], tile[:, :, 1], tile[:, :, 2]
            votes.append(float(((red - green > 10) & (green - blue > 30) & (red > 160)).mean()))
        if votes[0] < .3 or votes[0] - max(votes[1:]) < .2:
            raise RuntimeError("未确认普通道具页签选中，已停止；不自动切换活动/合成页")

    def _activate(self):
        self.inventory.capture_mode = "automatic"
        self.inventory._save()
        pointer = self.root / "runtime/manual-inventory/active.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        temporary = pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "directory": self.directory.relative_to(self.root).as_posix(),
            "output": self.inventory.output.relative_to(self.root).as_posix(),
        }, ensure_ascii=False), encoding="utf-8")
        temporary.replace(pointer)

    def _settle(self, token):
        self.pause(.6, token)
        before, frame = self._capture(token, "settling")
        for _ in range(4):
            self.pause(.35, token)
            after, frame = self._capture(token, "stable")
            match = estimate_vertical_shift(before, after)
            if match["reliable"] and match["unchanged"]:
                self._assert_bag(after, token)
                return after, frame
            before = after
        raise RuntimeError("滑动后画面未稳定，已停止，截图保留")

    def _move(self, token, before, direction):
        """Measure each small step; two unchanged steps confirm an endpoint."""
        total = 0.0
        unchanged = 0
        sign = 1 if direction == "up" else -1
        for _ in range(2):
            actual_direction = direction
            # In this game tiny reverse corrections produce large inertial
            # jumps. Keep one slow, uniform small gesture with ample overlap.
            hand = 100
            token.check()
            self._assert_bag(before, token)
            action = {"direction": actual_direction, "gesture_distance": hand, "duration_ms": 1200 if hand >= 40 else 500,
                      "before": before.name, "submitted": False}
            self.actions.append(action)
            self._publish(self.status["phase"], "缓慢滑动并核对实际位移")
            self.device.swipe_inventory(actual_direction, hand, token)
            action["submitted"] = True
            after, _ = self._settle(token)
            match = estimate_vertical_shift(before, after)
            action.update(after=after.name, alignment=match)
            self._publish(self.status["phase"], "已取得滑动后稳定截图")
            if not match["reliable"]:
                raise RuntimeError("前后画面无法可靠对齐，已停止，未继续盲滑")
            shift = match["shift"]
            if match["unchanged"]:
                unchanged += 1
                if unchanged >= 2:
                    return after, total, True
            else:
                unchanged = 0
                expected_sign = 1 if actual_direction == "up" else -1
                if shift * expected_sign <= 0 or abs(shift) > 620:
                    raise RuntimeError("实际滚动方向或距离异常，已停止")
                total += sign * shift
                return after, total, False
            before = after
        raise RuntimeError("未能确认滚动结果，已停止；原图和动作记录保留")

    def _record(self, token, path, *, tail=False):
        group = self.inventory.create_group()
        attempts = []
        for attempt in range(3):
            token.check()
            data = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
            self.inventory.import_image(data, group_id=group)
            filename = self.inventory.shots[-1]
            try:
                tokens, parsed = self.ocr.read_inventory(path, token, scrolling=True, prefer_last=tail)
            except OperationCancelled:
                raise
            except Exception as error:
                tokens, parsed = [], {"rows": [], "status": "pending", "message": str(error)}
            attempts.append((filename, path, tokens, parsed))
            self.inventory.ocr_reports[filename] = {**parsed, "tokens": tokens, "status": "pending"}
            self.inventory._save()
            if parsed["status"] == "recognized":
                break
            if attempt < 2:
                new_path, _ = self._capture(token, "ocr-retry")
                match = estimate_vertical_shift(path, new_path)
                if not match["reliable"] or not match["unchanged"]:
                    raise RuntimeError("识别重试期间画面变化，已停止；本轮尚未完成")
                path = new_path
        chosen = max(attempts, key=lambda value: sum(bool(row["name"]) + bool(row["quantity"]) for row in value[3]["rows"]))
        filename, path, tokens, parsed = chosen
        # Select one frame and clear disagreements; do not combine fields.
        from .bridge import Bridge
        parsed = Bridge._clear_retry_conflicts(parsed, [value[3] for value in attempts])
        for other, _, _, _ in attempts:
            if other != filename:
                self.inventory.ocr_reports[other]["status"] = "superseded"
        report = self.inventory.apply_ocr(filename, tokens, parsed)
        self.inventory.select_group(group, filename)
        self.inventory._save()
        self.frame = {**self.frame, "data": self.inventory.preview(filename), "inventory_shot": filename}
        self.status["pages"] += 1
        self._publish("capturing", f"已采集{self.status['pages']}页；识别缺项保留待核对")
        if parsed.get("layout_valid") is False or not parsed["rows"]:
            raise RuntimeError("当前页无法可靠识别网格，已停止，原图保留")
        return path

    def run(self, token):
        try:
            path, _ = self._capture(token, "initial")
            self._assert_bag(path, token)
            self._activate()
            self._publish("rewinding", "已锁定630×1120普通道具，正在返回顶部")
            for _ in range(30):
                path, _, endpoint = self._move(token, path, "down")
                if endpoint:
                    break
            else:
                raise RuntimeError("返回顶部超出限定次数，已停止")
            self._publish("capturing", "已确认顶部，开始逐页截图与OCR")
            for _ in range(30):
                path = self._record(token, path)
                path, moved, endpoint = self._move(token, path, "up")
                if endpoint:
                    self._record(token, path, tail=True)
                    self.status["capture_complete"] = True
                    self._publish("review", "已确认底部，自动截图完成；识别结果待核对，未自动导出或清图")
                    return self.frame
            raise RuntimeError("采集超过30页上限，已停止，不能视为全背包完成")
        except OperationCancelled:
            self._publish("stopped", "自动采集已停止；本次未完成，截图及记录保留")
            raise
        except Exception as error:
            self._publish("error", str(error))
            raise


def main():
    import argparse
    from .config import prepare_paths
    from .device import MaaDevice
    from .reset import SessionLease
    from .worker import SerialWorker
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb-path", required=True)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    prepare_paths()
    lease = SessionLease()
    if not lease.acquire():
        raise SystemExit("请先关闭m4b窗口再执行终端自动采集，避免两个写入者")
    worker = SerialWorker()
    device = MaaDevice(read_only=True, allow_inventory_swipe=True)
    collector = BagCollector(device, notify=lambda state, *_: print(json.dumps(state, ensure_ascii=False), flush=True))
    def run(token):
        device.connect(args.adb_path, args.address, token)
        return collector.run(token)
    try:
        worker.submit(run).result(600)
    except KeyboardInterrupt:
        worker.stop()
        raise
    finally:
        worker.close()
        lease.close()


if __name__ == "__main__":
    main()
