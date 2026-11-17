"""Local configuration checks only; never connects to or inspects a device."""
from pathlib import Path

from .config import ROOT
from .device import MaaDevice


def check_local_readiness(adb_path, address, *, root=ROOT):
    checks = []
    try:
        MaaDevice.validate_connection(adb_path, address)
    except (ValueError, TypeError, OSError) as error:
        checks.append({"name": "连接配置", "status": "missing", "message": str(error)})
    else:
        checks.append({"name": "连接配置", "status": "checked",
                       "message": "ADB 文件与地址格式已检查；尚未验证连接"})

    model = Path(root) / "assets/ocr/zh_cn"
    missing = []
    for name in ("det.onnx", "rec.onnx", "keys.txt"):
        try:
            if not (model / name).is_file() or (model / name).stat().st_size == 0:
                missing.append(name)
        except OSError:
            missing.append(name)
    checks.append({"name": "中文识别", "status": "missing" if missing else "checked",
                   "message": "请补齐非空且可访问的模型文件：" + "、".join(missing) if missing
                   else "模型文件已找到；加载与识别效果待验证"})
    return {"ok": True, "checks": checks}
