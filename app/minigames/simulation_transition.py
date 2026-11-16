"""Explicit cost and effect outcomes for one pure simulated action."""

from dataclasses import dataclass
from enum import Enum

from app.minigames.simulation_actions import ActionCandidate, ActionClass
from app.minigames.simulation_state import SimulationState


class CostStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class TransitionStatus(str, Enum):
    APPLIED = "applied"
    INVALID = "invalid"
    UNKNOWN = "unknown"


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是非空文本")


@dataclass(frozen=True, slots=True)
class ResourceCost:
    """One source-backed resource amount, without assuming resource names."""

    resource_id: str
    amount: int

    def __post_init__(self):
        _require_text(self.resource_id, "resource_id")
        if type(self.amount) is not int or self.amount < 0:
            raise ValueError("amount必须是非负整数")


@dataclass(frozen=True, slots=True)
class SimulationCost:
    """Known cost vector or explicit unknown; empty known vector means zero."""

    status: CostStatus
    entries: tuple = ()
    evidence_ref: str = None
    reason: str = None

    def __post_init__(self):
        if not isinstance(self.status, CostStatus):
            raise TypeError("status必须是CostStatus")
        if not isinstance(self.entries, tuple) or any(
            not isinstance(entry, ResourceCost) for entry in self.entries
        ):
            raise TypeError("entries必须是ResourceCost元组")
        resource_ids = tuple(entry.resource_id for entry in self.entries)
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("同一成本中resource_id不能重复")

        if self.status is CostStatus.KNOWN:
            _require_text(self.evidence_ref, "evidence_ref")
            if self.reason is not None:
                raise ValueError("已知成本不能带unknown原因")
        else:
            if self.entries or self.evidence_ref is not None:
                raise ValueError("unknown成本不能带数值或来源引用")
            _require_text(self.reason, "reason")

    @classmethod
    def known(cls, entries=(), *, evidence_ref=None):
        try:
            normalized = tuple(entries)
        except TypeError:
            raise TypeError("entries必须是成本条目可迭代对象") from None
        return cls(CostStatus.KNOWN, normalized, evidence_ref=evidence_ref)

    @classmethod
    def unknown(cls, reason):
        return cls(CostStatus.UNKNOWN, reason=reason)

    @property
    def is_zero(self):
        return self.status is CostStatus.KNOWN and not self.entries


@dataclass(frozen=True, slots=True)
class SimulationTransition:
    """Outcome bound to the exact input state and a classified gameplay action."""

    state_before: SimulationState
    action: ActionCandidate
    status: TransitionStatus
    cost: SimulationCost
    state_after: SimulationState = None
    effect_evidence_ref: str = None
    reason: str = None

    def __post_init__(self):
        if not isinstance(self.state_before, SimulationState):
            raise TypeError("state_before必须是SimulationState")
        if not isinstance(self.action, ActionCandidate):
            raise TypeError("action必须是ActionCandidate")
        if self.action.action_class is not ActionClass.GAMEPLAY:
            raise ValueError("模拟转移只接受已分类的gameplay动作")
        if not isinstance(self.status, TransitionStatus):
            raise TypeError("status必须是TransitionStatus")
        if not isinstance(self.cost, SimulationCost):
            raise TypeError("cost必须是SimulationCost")

        if self.status is TransitionStatus.APPLIED:
            if self.cost.status is not CostStatus.KNOWN:
                raise ValueError("应用动作前成本必须已知")
            self._require_compatible_state_after()
            _require_text(self.effect_evidence_ref, "effect_evidence_ref")
            if self.reason is not None:
                raise ValueError("已应用结果不能带unknown原因")
        elif self.status is TransitionStatus.INVALID:
            if not self.cost.is_zero:
                raise ValueError("非法动作必须明确为零成本")
            self._require_compatible_state_after()
            if self.state_after.fingerprint != self.state_before.fingerprint:
                raise ValueError("非法动作不能改变模拟状态")
            _require_text(self.effect_evidence_ref, "effect_evidence_ref")
            _require_text(self.reason, "reason")
        else:
            if self.state_after is not None:
                raise ValueError("unknown效果不能声称有已知后置状态")
            _require_text(self.reason, "reason")
            if self.effect_evidence_ref is not None:
                raise ValueError("unknown效果不能附带已核实规则引用")

    def _require_compatible_state_after(self):
        if not isinstance(self.state_after, SimulationState):
            raise TypeError("已知效果必须返回SimulationState")
        before = self.state_before
        after = self.state_after
        if (after.game_id, after.rules_version, after.state_schema) != (
            before.game_id, before.rules_version, before.state_schema,
        ):
            raise ValueError("效果前后必须属于同一游戏、规则版本和状态schema")

    @classmethod
    def applied(cls, state_before, action, cost, state_after, *, effect_evidence_ref):
        return cls(
            state_before=state_before,
            action=action,
            status=TransitionStatus.APPLIED,
            cost=cost,
            state_after=state_after,
            effect_evidence_ref=effect_evidence_ref,
        )

    @classmethod
    def invalid(cls, state_before, action, *, cost_evidence_ref, effect_evidence_ref, reason):
        return cls(
            state_before=state_before,
            action=action,
            status=TransitionStatus.INVALID,
            cost=SimulationCost.known(evidence_ref=cost_evidence_ref),
            state_after=state_before,
            effect_evidence_ref=effect_evidence_ref,
            reason=reason,
        )

    @classmethod
    def unknown(cls, state_before, action, *, reason, cost=None):
        return cls(
            state_before=state_before,
            action=action,
            status=TransitionStatus.UNKNOWN,
            cost=cost or SimulationCost.unknown(reason),
            reason=reason,
        )
