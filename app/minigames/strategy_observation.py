"""Read-only, current-turn information exposed to pure strategy code."""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.game_capability import SUPPORTED_GAME_IDS
from app.observation import ObservedValue


STRATEGY_OBSERVATION_SCHEMA_VERSION = 1
_SCHEMA_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class _FrozenObject(Mapping):
    __slots__ = ("_items",)

    def __init__(self, items):
        self._items = tuple(items)

    def __getitem__(self, key):
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _ in self._items)

    def __len__(self):
        return len(self._items)

    def __eq__(self, other):
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self._items) == dict(other.items())


def _freeze_json(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("visible_fields不能包含非有限数字")
        return value
    if isinstance(value, Mapping):
        items = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("visible_fields对象的键必须是文本")
            items.append((key, _freeze_json(item)))
        return _FrozenObject(tuple(sorted(items)))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("visible_fields值必须是JSON数据")


def _thaw_json(value):
    if isinstance(value, _FrozenObject):
        return {key: _thaw_json(item) for key, item in value._items}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class StrategyObservation:
    """Projection of visible current-turn fields; never carries a full simulation state."""

    game_id: str
    rules_version: str
    observation_schema: str
    visible_fields: Mapping[str, ObservedValue]

    def __post_init__(self):
        if self.game_id not in SUPPORTED_GAME_IDS:
            raise ValueError(f"v0.4不支持此小游戏ID：{self.game_id}")
        if not isinstance(self.rules_version, str) or not self.rules_version.strip():
            raise ValueError("rules_version必须是非空文本")
        if (not isinstance(self.observation_schema, str)
                or not _SCHEMA_PATTERN.fullmatch(self.observation_schema)):
            raise ValueError("observation_schema必须是稳定的小写英文标识")
        if not isinstance(self.visible_fields, Mapping):
            raise TypeError("visible_fields必须是映射")

        fields = []
        for name, observed in self.visible_fields.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("visible_fields名称必须是非空文本")
            if not isinstance(observed, ObservedValue):
                raise TypeError("visible_fields值必须是ObservedValue")
            if observed.is_known:
                value = ObservedValue.observed(_freeze_json(observed.value))
            else:
                value = ObservedValue.unknown(observed.reason)
            fields.append((name, value))
        object.__setattr__(self, "visible_fields", _FrozenObject(tuple(sorted(fields))))

    def to_dict(self):
        fields = {}
        for name, observed in self.visible_fields.items():
            if observed.is_known:
                fields[name] = {"known": True, "value": _thaw_json(observed.value)}
            else:
                fields[name] = {"known": False, "reason": observed.reason}
        return {
            "schema_version": STRATEGY_OBSERVATION_SCHEMA_VERSION,
            "game_id": self.game_id,
            "rules_version": self.rules_version,
            "observation_schema": self.observation_schema,
            "visible_fields": fields,
        }

    @classmethod
    def from_dict(cls, data):
        expected = {
            "schema_version", "game_id", "rules_version",
            "observation_schema", "visible_fields",
        }
        if (not isinstance(data, dict) or set(data) != expected
                or type(data.get("schema_version")) is not int
                or data["schema_version"] != STRATEGY_OBSERVATION_SCHEMA_VERSION
                or not isinstance(data["visible_fields"], dict)):
            raise ValueError("策略观察结构或版本无效")
        fields = {
            name: ObservedValue.from_dict(observed)
            for name, observed in data["visible_fields"].items()
        }
        return cls(
            game_id=data["game_id"],
            rules_version=data["rules_version"],
            observation_schema=data["observation_schema"],
            visible_fields=fields,
        )
