"""Fail-closed classification and validation for simulated legal actions."""

from dataclasses import dataclass
from enum import Enum

from app.minigames.simulation_state import SimulationState
from app.strategy_contract import LogicalAction


class ActionClass(str, Enum):
    GAMEPLAY = "gameplay"
    AUXILIARY_ITEM = "auxiliary_item"
    PURCHASE = "purchase"
    RESTART = "restart"
    UNKNOWN = "unknown"


class UnsafeActionEnumerationError(ValueError):
    """Raised when an action set contains an unsafe or unclassified action."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    """A logical action with an explicit, source-linked safety classification."""

    action: LogicalAction
    action_class: ActionClass
    rule_evidence_ref: str = None

    def __post_init__(self):
        if not isinstance(self.action, LogicalAction):
            raise TypeError("action必须是LogicalAction")
        if not isinstance(self.action_class, ActionClass):
            raise TypeError("action_class必须是ActionClass")
        if self.rule_evidence_ref is not None and (
            not isinstance(self.rule_evidence_ref, str) or not self.rule_evidence_ref.strip()
        ):
            raise ValueError("rule_evidence_ref提供时必须是非空文本")
        if self.action_class is ActionClass.GAMEPLAY and not self.rule_evidence_ref:
            raise ValueError("游戏动作必须引用规则证据")


@dataclass(frozen=True, slots=True)
class LegalActionSet:
    """Validated game-only actions bound to one exact simulation state."""

    state: SimulationState
    candidates: tuple

    def __post_init__(self):
        if not isinstance(self.state, SimulationState):
            raise TypeError("state必须是SimulationState")
        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates必须是ActionCandidate元组")
        seen = set()
        for candidate in self.candidates:
            if not isinstance(candidate, ActionCandidate):
                raise TypeError("candidates只能包含ActionCandidate")
            if candidate.action_class is not ActionClass.GAMEPLAY:
                _raise_unsafe_candidate(candidate)
            identity = (candidate.action.kind, candidate.action.target)
            if identity in seen:
                raise UnsafeActionEnumerationError(
                    "duplicate_action", "合法动作列表含重复动作，模拟已停止",
                )
            seen.add(identity)
        object.__setattr__(self, "candidates", tuple(self.candidates))

    @classmethod
    def from_candidates(cls, state, candidates):
        if not isinstance(state, SimulationState):
            raise TypeError("state必须是SimulationState")
        try:
            normalized = tuple(candidates)
        except TypeError:
            raise TypeError("candidates必须是动作候选可迭代对象") from None
        return cls(state=state, candidates=normalized)

    @property
    def logical_actions(self):
        """Return actions suitable for the strategy protocol after validation."""
        return tuple(candidate.action for candidate in self.candidates)

    @property
    def state_fingerprint(self):
        return self.state.fingerprint

    @property
    def is_empty(self):
        """An empty set is only empty; terminal meaning is defined separately."""
        return not self.candidates


def _raise_unsafe_candidate(candidate):
    codes = {
        ActionClass.AUXILIARY_ITEM: ("auxiliary_item_forbidden", "辅助道具动作不能进入模拟合法动作集"),
        ActionClass.PURCHASE: ("purchase_forbidden", "购买动作不能进入模拟合法动作集"),
        ActionClass.RESTART: ("restart_forbidden", "重开动作不能进入模拟合法动作集"),
        ActionClass.UNKNOWN: ("action_class_unknown", "动作分类未知，合法动作集已停止"),
    }
    code, message = codes.get(
        candidate.action_class,
        ("action_class_unknown", "动作分类未知，合法动作集已停止"),
    )
    raise UnsafeActionEnumerationError(code, message)
