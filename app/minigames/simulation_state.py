"""Versioned JSON state and deterministic per-step random input for simulations."""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.game_capability import SUPPORTED_GAME_IDS


STATE_SCHEMA_VERSION = 1
RANDOM_INPUT_SCHEMA_VERSION = 1
RANDOM_INPUT_ALGORITHM = "sha256-counter-u32-v1"
_UNKNOWN_VERSION_MARKERS = {"unknown", "unverified", "未核实", "未知"}
_STATE_SCHEMA_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class _FrozenObject(Mapping):
    """Immutable mapping used to prevent a caller mutating a saved state."""

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
            raise ValueError("state_data不能包含非有限数字")
        return value
    if isinstance(value, Mapping):
        items = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("state_data对象的键必须是文本")
            items.append((key, _freeze_json(item)))
        return _FrozenObject(tuple(sorted(items)))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("state_data必须只包含JSON值")


def _thaw_json(value):
    if isinstance(value, _FrozenObject):
        return {key: _thaw_json(item) for key, item in value._items}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class SimulationState:
    """Opaque, game-specific JSON state; no shared board shape is assumed."""

    game_id: str
    rules_version: str
    state_schema: str
    state_data: Mapping

    def __post_init__(self):
        if self.game_id not in SUPPORTED_GAME_IDS:
            raise ValueError(f"v0.4不支持此小游戏ID：{self.game_id}")
        if not isinstance(self.rules_version, str) or not self.rules_version.strip():
            raise ValueError("rules_version必须是非空且已核实的版本标识")
        if self.rules_version.strip().casefold() in _UNKNOWN_VERSION_MARKERS:
            raise ValueError("规则版本unknown时不能建立可模拟状态")
        if (not isinstance(self.state_schema, str)
                or not _STATE_SCHEMA_PATTERN.fullmatch(self.state_schema)):
            raise ValueError("state_schema必须是稳定的小写英文版本标识")
        if not isinstance(self.state_data, Mapping):
            raise ValueError("state_data必须是游戏专属JSON对象")
        object.__setattr__(self, "state_data", _freeze_json(self.state_data))

    def to_dict(self):
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "game_id": self.game_id,
            "rules_version": self.rules_version,
            "state_schema": self.state_schema,
            "state_data": _thaw_json(self.state_data),
        }

    def copy_for_trial(self):
        """Return a detached, immutable copy for one strategy trial."""
        return type(self).from_dict(self.to_dict())

    @classmethod
    def from_dict(cls, data):
        expected = {"schema_version", "game_id", "rules_version", "state_schema", "state_data"}
        if (not isinstance(data, dict) or set(data) != expected
                or type(data.get("schema_version")) is not int
                or data["schema_version"] != STATE_SCHEMA_VERSION):
            raise ValueError("模拟状态结构或版本无效")
        return cls(
            game_id=data["game_id"],
            rules_version=data["rules_version"],
            state_schema=data["state_schema"],
            state_data=data["state_data"],
        )

    @property
    def canonical_json(self):
        return _canonical_json(self.to_dict())

    @property
    def fingerprint(self):
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulationRandomInput:
    """Finite random values for exactly one simulated action/transition."""

    seed: int
    step_index: int
    draws: tuple
    algorithm: str = RANDOM_INPUT_ALGORITHM

    def __post_init__(self):
        _validate_counter("seed", self.seed)
        _validate_counter("step_index", self.step_index)
        if not isinstance(self.draws, tuple):
            raise TypeError("draws必须是整数元组")
        if any(type(value) is not int or value < 0 or value > 0xFFFFFFFF for value in self.draws):
            raise ValueError("draws中的值必须是无符号32位整数")
        if self.algorithm != RANDOM_INPUT_ALGORITHM:
            raise ValueError("random input算法版本未知")
        expected_draws = tuple(
            _derive_draw(self.seed, self.step_index, index)
            for index in range(len(self.draws))
        )
        if self.draws != expected_draws:
            raise ValueError("随机输入与种子／步骤记录不一致")

    @classmethod
    def for_step(cls, seed, step_index, draw_count):
        """Create the reproducible random input for one action only."""
        _validate_counter("seed", seed)
        _validate_counter("step_index", step_index)
        if type(draw_count) is not int or draw_count < 0:
            raise ValueError("draw_count必须是非负整数")
        draws = tuple(
            _derive_draw(seed, step_index, draw_index)
            for draw_index in range(draw_count)
        )
        return cls(seed, step_index, draws)

    def draw(self, index):
        if type(index) is not int or index < 0:
            raise ValueError("随机输入索引必须是非负整数")
        if index >= len(self.draws):
            raise IndexError("本步随机输入已耗尽")
        return self.draws[index]

    def to_dict(self):
        return {
            "schema_version": RANDOM_INPUT_SCHEMA_VERSION,
            "algorithm": self.algorithm,
            "seed": self.seed,
            "step_index": self.step_index,
            "draws": list(self.draws),
        }

    @classmethod
    def from_dict(cls, data):
        expected = {"schema_version", "algorithm", "seed", "step_index", "draws"}
        if (not isinstance(data, dict) or set(data) != expected
                or type(data.get("schema_version")) is not int
                or data["schema_version"] != RANDOM_INPUT_SCHEMA_VERSION
                or not isinstance(data.get("draws"), list)):
            raise ValueError("随机输入结构或版本无效")
        result = cls(
            seed=data["seed"],
            step_index=data["step_index"],
            draws=tuple(data["draws"]),
            algorithm=data["algorithm"],
        )
        expected_draws = tuple(
            _derive_draw(result.seed, result.step_index, index)
            for index in range(len(result.draws))
        )
        if result.draws != expected_draws:
            raise ValueError("随机输入与种子／步骤记录不一致")
        return result


def _validate_counter(name, value):
    if type(value) is not int or value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"{name}必须是无符号64位整数")


def _derive_draw(seed, step_index, draw_index):
    payload = (
        b"m4b-sim-random-v1\0"
        + seed.to_bytes(8, "big")
        + step_index.to_bytes(8, "big")
        + draw_index.to_bytes(8, "big")
    )
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")
