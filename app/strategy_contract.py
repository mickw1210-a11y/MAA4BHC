"""Pure strategy-facing data and interface; no device controller imports."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.observation import ObservedValue
from app.minigames.strategy_observation import StrategyObservation


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}必须是非空文本")


@dataclass(frozen=True)
class LogicalAction:
    """Rule-level target without screen coordinates or device identity."""

    kind: str
    target: str

    def __post_init__(self):
        _require_text(self.kind, "kind")
        _require_text(self.target, "target")


@dataclass(frozen=True)
class StrategyDecision:
    action: LogicalAction | None = None
    pause_reason: str | None = None

    def __post_init__(self):
        if self.action is not None and not isinstance(self.action, LogicalAction):
            raise TypeError("action必须是LogicalAction或None")
        if self.action is None:
            _require_text(self.pause_reason, "pause_reason")
        elif self.pause_reason is not None:
            raise ValueError("策略选择动作时不能同时返回暂停原因")


class Strategy(Protocol):
    """Pure planner that returns one logical action or an explicit pause."""

    def choose_action(
        self,
        *,
        state: StrategyObservation,
        legal_actions: tuple[LogicalAction, ...],
        budget: Mapping[str, ObservedValue],
    ) -> StrategyDecision:
        ...
