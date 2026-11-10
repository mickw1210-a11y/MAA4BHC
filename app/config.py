import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
LOGS = RUNTIME / "logs"


def prepare_paths():
    (ROOT / "chars").mkdir(parents=True, exist_ok=True)
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



def prepare_character_paths(character_id, nickname):
    """Create empty local directories for an explicitly confirmed character."""
    if not isinstance(character_id, str) or len(character_id) != 10 or not character_id.isascii() or not character_id.isdigit():
        raise ValueError("角色 ID 必须是 10 位数字")
    if not isinstance(nickname, str) or not nickname or nickname.strip() != nickname or nickname.endswith("."):
        raise ValueError("昵称不能为空或以空格、点结尾")
    if nickname in (".", "..") or any(c in nickname for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in nickname):
        raise ValueError("昵称包含不能用于目录的字符")
    directory = ROOT / "chars" / f"{character_id}_{nickname}"
    config = directory / "Priv_Config"
    assets = directory / "Priv_Assets"
    config.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    return config, assets


def read_settings():
    path = ROOT / "config" / "settings.json"
    if not path.exists():
        path = ROOT / "config" / "settings.example.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return {"adb_path": str(data.get("adb_path", "")), "address": str(data.get("address", ""))}

