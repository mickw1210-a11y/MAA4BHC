import base64
import io
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .config import RUNTIME


class MaaDevice:
    def __init__(self, *, read_only=False, allow_inventory_swipe=False):
        self._controller = None
        self._read_only = read_only
        self._allow_inventory_swipe = allow_inventory_swipe
        self._last_size = None

    @property
    def connected(self):
        return self._controller is not None and bool(self._controller.connected)

    @staticmethod
    def validate_connection(adb_path, address):
        path = Path(str(adb_path))
        if not path.is_absolute() or not path.is_file() or path.name.lower() != "adb.exe":
            raise ValueError("请选择实际存在的MuMu adb.exe完整路径")
        match = re.fullmatch(r"127\.0\.0\.1:(\d{1,5})", str(address).strip())
        if not match or not 1 <= int(match.group(1)) <= 65535:
            raise ValueError("连接地址请填写127.0.0.1:端口")
        return path, match.group(0)

    @staticmethod
    def _wait(job, token):
        # Keep the queue occupied until an already-submitted native job has finished.
        job.wait()
        token.check()
        if not job.succeeded:
            raise RuntimeError("设备操作未成功，结果需核对，请停止后检查")
        return job

    def connect(self, adb_path, address, token):
        path, address = self.validate_connection(adb_path, address)
        from maa.controller import AdbController
        from maa.define import MaaAdbInputMethodEnum, MaaAdbScreencapMethodEnum
        from maa.toolkit import Toolkit

        if not Toolkit.init_option(RUNTIME / "framework"):
            raise RuntimeError("MaaFramework本地初始化失败")
        screen_config = self._screen_config(path, address, token)
        if self._read_only:
            controller = token.dispatch(lambda: AdbController(
                path, address, screencap_methods=MaaAdbScreencapMethodEnum.Encode,
                input_methods=MaaAdbInputMethodEnum.Null,
                config=screen_config,
            ))
        else:
            controller = token.dispatch(lambda: AdbController(path, address, config=screen_config))
        self._wait(token.dispatch(controller.post_connection), token)
        if not controller.connected:
            raise RuntimeError("无法确认设备连接")
        if not token.dispatch(lambda: controller.set_screenshot_use_raw_size(True)):
            raise RuntimeError("无法确认截图坐标基准，请停止检查")
        self._controller = controller
        self._capture_target = (path, address, screen_config)
        return {"message": "已连接；请先截图核对页面"}

    @staticmethod
    def _select_game_display(windows, displays):
        package = "com.tomato.android.ssbhc/"
        sections = re.split(r"Display: mDisplayId=(\d+)[^\n]*", windows)
        logical = []
        for index in range(1, len(sections), 2):
            focused = re.search(r"mCurrentFocus=([^\n]+)", sections[index + 1])
            if focused and package in focused.group(1):
                logical.append(sections[index])
        if len(logical) != 1:
            raise RuntimeError("无法唯一确认百货城前台显示屏，请手动检查游戏窗口后重新连接")
        physical = set(re.findall(
            r"DisplayViewport\{[^}]*displayId=" + re.escape(logical[0])
            + r",\s*uniqueId='local:(\d+)'", displays))
        if len(physical) != 1:
            raise RuntimeError("无法唯一匹配游戏显示屏的截图ID，已停止")
        return logical[0], physical.pop()

    @staticmethod
    def _screen_config(path, address, token):
        return MaaDevice._screen_info(path, address, token)[1]

    @staticmethod
    def _screen_info(path, address, token):
        def query(*arguments):
            process = token.dispatch(lambda: subprocess.Popen(
                [str(path), "-s", address, "shell", "dumpsys", *arguments],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ))
            try:
                output, _ = process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise RuntimeError("读取显示屏信息超时") from None
            token.check()
            if process.returncode:
                raise RuntimeError("读取显示屏信息失败")
            return output.decode("utf-8", errors="replace")

        windows = query("window", "displays")
        displays = query("display")
        logical, display_id = MaaDevice._select_game_display(windows, displays)
        # Logical display IDs and physical screencap IDs are different namespaces.
        return logical, {"command": {"ScreencapEncode": ["{ADB}", "-s", "{ADB_SERIAL}", "exec-out",
                                                       "screencap -p -d " + display_id]}}

    def screenshot(self, token, *, save=True):
        controller = self._require_connection()
        path, address, expected = self._capture_target
        if self._screen_config(path, address, token) != expected:
            raise RuntimeError("游戏显示屏已变化，请重新连接后再截图")
        job = self._wait(token.dispatch(controller.post_screencap), token)
        image = job.get()
        if image is None or image.size == 0:
            raise RuntimeError("未取得有效截图")
        from PIL import Image

        rgb = image[:, :, :3][:, :, ::-1]
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG")
        token.check()
        now = datetime.now().astimezone()
        frame_id = now.strftime("%Y%m%d-%H%M%S-%f")
        content = buffer.getvalue()
        self._last_size = (int(image.shape[1]), int(image.shape[0]))
        path = RUNTIME / "screenshots" / (frame_id + ".png")
        if save:
            token.dispatch(lambda: path.write_bytes(content))
        return {
            "frame_id": frame_id,
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "time": now.isoformat(timespec="seconds"),
            "data": "data:image/png;base64," + base64.b64encode(content).decode("ascii"),
        }

    def click(self, x, y, token):
        if self._read_only:
            raise RuntimeError("只读模式禁止点击")
        controller = self._require_connection()
        self._wait(token.dispatch(lambda: controller.post_click(x, y)), token)
        return {"message": "点击指令完成；请截图核对实际结果"}

    def swipe_inventory(self, direction, distance, token):
        """The only additional input capability: a bounded backpack scroll."""
        if not self._allow_inventory_swipe:
            raise RuntimeError("当前模式未启用背包自动滑动")
        self._require_connection()
        if self._last_size != (630, 1120):
            raise RuntimeError("背包自动操作锁定630×1120，请先取得该尺寸截图")
        if direction not in ("up", "down") or type(distance) is not int or not 16 <= distance <= 620:
            raise ValueError("无效背包滑动；距离须为16–620像素")
        path, address, expected = self._capture_target
        logical, config = self._screen_info(path, address, token)
        if config != expected:
            raise RuntimeError("游戏显示屏变化，已停止滑动")
        y1 = 920 if direction == "up" else 300
        y2 = y1 - distance if direction == "up" else y1 + distance
        duration = 1200 if distance >= 40 else 500
        process = token.dispatch(lambda: subprocess.Popen(
            [str(path), "-s", address, "shell", "input", "touchscreen", "-d", logical,
             "swipe", "590", str(y1), "590", str(y2), str(duration)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ))
        try:
            _, error = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            raise RuntimeError("背包滑动结果未知，已停止，请核对画面") from None
        token.check()
        if process.returncode:
            raise RuntimeError("背包滑动失败：" + error.decode("utf-8", errors="replace")[:160])
        return {"direction": direction, "distance": distance, "duration_ms": duration, "logical_display": logical}

    def swipe(self, x1, y1, x2, y2, duration, token):
        if self._read_only:
            raise RuntimeError("只读模式禁止滑动")
        controller = self._require_connection()
        self._wait(token.dispatch(lambda: controller.post_swipe(x1, y1, x2, y2, duration)), token)
        return {"message": "滑动指令完成；请截图核对实际结果"}

    def _require_connection(self):
        if not self.connected:
            raise RuntimeError("连接已失效，请手动重新连接")
        return self._controller

