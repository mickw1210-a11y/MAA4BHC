"""Typed, serializable observations that keep unknown values explicit."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


_OBSERVATION_FIELDS = (
    "device_id",
    "character_id",
    "activity_id",
    "rules_version",
    "frame_id",
    "page_id",
    "board",
    "energy",
)
_TEXT_FIELDS = (
    "device_id",
    "character_id",
    "activity_id",
    "rules_version",
    "frame_id",
    "page_id",
)


@dataclass(frozen=True)
class _FrozenObject(Mapping):
    """Small immutable JSON object used inside an observation snapshot."""

    _items: tuple

    def __getitem__(self, key):
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _ in self._items)

    def __len__(self):
        return len(self._items)


def _freeze_json(value):
    """Copy a JSON value into recursively immutable containers."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("board不能包含非有限数字")
        return value
    if isinstance(value, Mapping):
        items = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("board对象的键必须是文本")
            items.append((key, _freeze_json(item)))
        return _FrozenObject(tuple(items))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("board必须是JSON可序列化的数据")


def _thaw_json(value):
    """Return ordinary JSON containers without exposing snapshot internals."""
    if isinstance(value, _FrozenObject):
        return {key: _thaw_json(item) for key, item in value._items}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _thaw_json(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ObservedValue:
    """A value explicitly marked as observed or unknown with a reason."""

    is_known: bool
    value: object = None
    reason: str = None

    def __post_init__(self):
        if type(self.is_known) is not bool:
            raise TypeError("is_known必须是布尔值")
        if self.is_known:
            if self.value is None or self.reason is not None:
                raise ValueError("已观测值必须有值且不能带unknown原因")
        elif self.value is not None or not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("unknown必须没有值并提供原因")

    @classmethod
    def observed(cls, value):
        return cls(is_known=True, value=value)

    @classmethod
    def unknown(cls, reason):
        return cls(is_known=False, reason=reason)

    def to_dict(self):
        if self.is_known:
            return {"known": True, "value": _thaw_json(self.value)}
        return {"known": False, "reason": self.reason}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("观测字段必须是对象")
        if data.get("known") is True and set(data) == {"known", "value"}:
            return cls.observed(data["value"])
        if data.get("known") is False and set(data) == {"known", "reason"}:
            return cls.unknown(data["reason"])
        raise ValueError("观测字段格式无效")


@dataclass(frozen=True)
class Observation:
    """One timestamped state sample with identity and unknowns preserved."""

    observed_at: datetime
    device_id: ObservedValue
    character_id: ObservedValue
    activity_id: ObservedValue
    rules_version: ObservedValue
    frame_id: ObservedValue
    page_id: ObservedValue
    board: ObservedValue
    energy: ObservedValue

    def __post_init__(self):
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at必须是datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at必须包含时区")
        for name in _OBSERVATION_FIELDS:
            field = getattr(self, name)
            if not isinstance(field, ObservedValue):
                raise TypeError(f"{name}必须显式使用ObservedValue或unknown")
        if self.board.is_known:
            object.__setattr__(self, "board", ObservedValue.observed(_freeze_json(self.board.value)))
        for name in _TEXT_FIELDS:
            field = getattr(self, name)
            if field.is_known and (not isinstance(field.value, str) or not field.value.strip()):
                raise ValueError(f"已观测的{name}必须是非空文本")
        if self.energy.is_known and (type(self.energy.value) is not int or self.energy.value < 0):
            raise ValueError("已观测的energy必须是非负整数；0是有效值")

    @property
    def unknown_fields(self):
        return tuple(name for name in _OBSERVATION_FIELDS if not getattr(self, name).is_known)

    def to_dict(self):
        data = {
            "schema_version": 1,
            "observed_at": self.observed_at.isoformat(timespec="microseconds"),
            **{name: getattr(self, name).to_dict() for name in _OBSERVATION_FIELDS},
            "unknown_fields": list(self.unknown_fields),
        }
        # Reject non-JSON state rather than silently stringifying board values.
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        return data

    @classmethod
    def from_dict(cls, data):
        expected = {"schema_version", "observed_at", *_OBSERVATION_FIELDS, "unknown_fields"}
        if (not isinstance(data, dict) or set(data) != expected
                or type(data.get("schema_version")) is not int
                or data.get("schema_version") != 1):
            raise ValueError("观察数据结构或版本无效")
        try:
            observed_at = datetime.fromisoformat(data["observed_at"])
        except (TypeError, ValueError):
            raise ValueError("observed_at格式无效") from None
        fields = {name: ObservedValue.from_dict(data[name]) for name in _OBSERVATION_FIELDS}
        observation = cls(observed_at=observed_at, **fields)
        if data["unknown_fields"] != list(observation.unknown_fields):
            raise ValueError("unknown_fields与各字段观测状态不一致")
        return observation
