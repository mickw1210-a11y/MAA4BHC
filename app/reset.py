"""Project-local reset command and a lock shared with the inventory window."""
import json
import time
from pathlib import Path
from uuid import uuid4

from .config import ROOT, prepare_paths
from .inventory import ManualInventory, active_inventory_paths


class SessionLease:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        if not self.root.is_relative_to(ROOT.resolve()):
            raise ValueError("会话路径必须在当前项目内")
        self.path = self.root / "runtime/manual-inventory/session.lock"
        self.stream = None

    def acquire(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def close(self):
        if self.stream:
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None


def reset_project(root=ROOT, *, timeout=12):
    lease = SessionLease(root)
    if lease.acquire():
        try:
            return ManualInventory(root, **active_inventory_paths(root)).reset()
        finally:
            lease.close()
    directory = Path(root) / "runtime/manual-inventory"
    request_id = uuid4().hex
    request = directory / "reset-request.json"
    temporary = directory / (request_id + ".tmp")
    temporary.write_text(json.dumps({"id": request_id}), encoding="utf-8")
    temporary.replace(request)
    response = directory / "reset-result.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if response.exists():
            result = json.loads(response.read_text(encoding="utf-8"))
            if result.get("id") == request_id:
                if not result["ok"]:
                    raise RuntimeError(result["error"])
                return result["result"]
        time.sleep(.1)
    raise RuntimeError("重置请求已送达，应用尚未回应；请查看m4b，不会绕过会话锁清空文件")


def main():
    prepare_paths()
    result = reset_project()
    print(f"已重置：清空{result['cleared_rows']}条识别记录、{result['cleared_screenshots']}张本轮临时截图。")
    print("历史、参考图和已导出CSV保留。")


if __name__ == "__main__":
    main()
