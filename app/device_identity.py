"""Stable, host-local identity for a MuMu 12 emulator instance.

Connection paths and ADB endpoints are locators. They are deliberately kept
separate from the identity used by cross-process device leases.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re


class DeviceIdentityUnavailable(ValueError):
    """Raised when the available evidence cannot identify an instance safely."""


@dataclass(frozen=True, slots=True)
class DeviceLocator:
    """How this project reaches a device; none of these fields identify it."""

    project_root: str
    adb_path: str
    adb_address: str


@dataclass(frozen=True, slots=True)
class DeviceInstanceIdentity:
    """Stable identity evidence, independent of project and connection paths."""

    provider: str
    instance_key: str
    schema_version: int = 1

    def __post_init__(self):
        if not isinstance(self.provider, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", self.provider):
            raise ValueError("设备身份提供方无效")
        if not isinstance(self.instance_key, str) or not self.instance_key:
            raise ValueError("设备实例身份不能为空")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("不支持的设备身份版本")

    @property
    def canonical(self):
        """Versioned serialization for equality, diagnostics, and lease keys."""
        return json.dumps(
            [self.provider, self.schema_version, self.instance_key],
            ensure_ascii=True,
            separators=(",", ":"),
        )

    @property
    def lease_key(self):
        """Opaque deterministic key suitable for a named OS lease object."""
        return hashlib.sha256(self.canonical.encode("ascii")).hexdigest()


def mumu12_identity_from_info(record: Mapping) -> DeviceInstanceIdentity:
    """Build an identity from MuMuManager ``info`` metadata.

    The documented instance index plus creation timestamp form the operational
    key. ADB address, manager/ADB executable paths, name, PID, and window handles
    are intentionally excluded. Missing or malformed identity evidence fails
    closed; callers must not fall back to the project path or ADB serial.
    """
    if not isinstance(record, Mapping):
        raise DeviceIdentityUnavailable("MuMu 实例信息格式未知，无法确认实例身份")

    index = record.get("index")
    if type(index) is int:
        index = str(index)
    if not isinstance(index, str) or not re.fullmatch(r"\d{1,10}", index):
        raise DeviceIdentityUnavailable("MuMu 实例编号缺失或无效，无法确认实例身份")

    created_timestamp = record.get("created_timestamp")
    if type(created_timestamp) is not int or created_timestamp <= 0:
        raise DeviceIdentityUnavailable("MuMu 实例创建标记缺失或无效，无法确认实例身份")

    return DeviceInstanceIdentity(
        provider="mumu12",
        instance_key=f"index={index};created_timestamp={created_timestamp}",
    )
