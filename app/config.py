import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
LOGS = RUNTIME / "logs"


def prepare_paths():
    for relative in ("logs", "webview", "screenshots", "framework", "manual-inventory"):
        (RUNTIME / relative).mkdir(parents=True, exist_ok=True)
    temporary = ROOT / ".cache" / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(temporary)
    os.environ["TMP"] = str(temporary)
    android_home = RUNTIME / "adb-home"
    android_user = android_home / ".android"
    android_user.mkdir(parents=True, exist_ok=True)
    os.environ["ANDROID_USER_HOME"] = str(android_user)
    os.environ["ANDROID_SDK_HOME"] = str(android_home)
    os.environ["ADB_VENDOR_KEYS"] = str(android_user)


def read_settings():
    path = ROOT / "config" / "settings.json"
    if not path.exists():
        path = ROOT / "config" / "settings.example.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {"adb_path": str(data.get("adb_path", "")), "address": str(data.get("address", ""))}

