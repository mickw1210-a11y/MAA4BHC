"""Separate terminal and interrupted outcomes for one simulated episode."""

from dataclasses import dataclass, replace
from enum import Enum

from app.minigames.simulation_actions import LegalActionSet
from app.minigames.simulation_state import SimulationState


class EpisodeEndReason(str, Enum):
    NORMAL_COMPLETION = "normal_completion"
    NO_LEGAL_ACTIONS = "no_legal_actions"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    THRESHOLD_STOP = "threshold_stop"


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是非空文本")


@dataclass(frozen=True, slots=True)
class SimulationEpisodeOutcome:
    """One exclusive episode result, attached to its last known state."""

    last_state: SimulationState
    end_reason: EpisodeEndReason
    evidence_ref: str = None
    detail: str = None
    legal_actions: LegalActionSet = None

    def __post_init__(self):
        if not isinstance(self.last_state, SimulationState):
            raise TypeError("last_state必须是SimulationState")
        if not isinstance(self.end_reason, EpisodeEndReason):
            raise TypeError("end_reason必须是EpisodeEndReason")
        if self.evidence_ref is not None:
            _require_text(self.evidence_ref, "evidence_ref")
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise ValueError("detail提供时必须是非空文本")

        if self.end_reason is EpisodeEndReason.NORMAL_COMPLETION:
            _require_text(self.evidence_ref, "正常完成的规则证据")
            if self.legal_actions is not None:
                raise ValueError("正常完成不能附带无合法动作断言")
        elif self.end_reason is EpisodeEndReason.NO_LEGAL_ACTIONS:
            _require_text(self.evidence_ref, "无合法动作的规则证据")
            if not isinstance(self.legal_actions, LegalActionSet):
                raise TypeError("无合法动作结果必须引用已校验的LegalActionSet")
            if self.legal_actions.state_fingerprint != self.last_state.fingerprint:
                raise ValueError("合法动作集合必须绑定最后一个已知状态")
            if not self.legal_actions.is_empty:
                raise ValueError("存在合法动作时不能记录为无合法动作")
        else:
            _require_text(self.detail, "非正常终止原因")
            if self.legal_actions is not None:
                raise ValueError("unknown／超时／阈值停止不能附带无合法动作断言")

    @classmethod
    def completed(cls, last_state, *, evidence_ref):
        return cls(
            last_state=last_state,
            end_reason=EpisodeEndReason.NORMAL_COMPLETION,
            evidence_ref=evidence_ref,
        )

    @classmethod
    def no_legal_actions(cls, last_state, legal_actions, *, evidence_ref):
        return cls(
            last_state=last_state,
            end_reason=EpisodeEndReason.NO_LEGAL_ACTIONS,
            evidence_ref=evidence_ref,
            legal_actions=legal_actions,
        )

    @classmethod
    def unknown(cls, last_state, *, detail):
        return cls(last_state, EpisodeEndReason.UNKNOWN, detail=detail)

    @classmethod
    def timeout(cls, last_state, *, detail):
        return cls(last_state, EpisodeEndReason.TIMEOUT, detail=detail)

    @classmethod
    def threshold_stop(cls, last_state, *, detail):
        return cls(last_state, EpisodeEndReason.THRESHOLD_STOP, detail=detail)


@dataclass(frozen=True, slots=True)
class SimulationOutcomeCounts:
    """Independent counts; no aggregate field treats non-completion as victory."""

    normal_completion: int = 0
    no_legal_actions: int = 0
    unknown: int = 0
    timeout: int = 0
    threshold_stop: int = 0

    def __post_init__(self):
        for name in EpisodeEndReason:
            value = getattr(self, name.value)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name.value}计数必须是非负整数")

    @property
    def total(self):
        return sum(getattr(self, reason.value) for reason in EpisodeEndReason)

    def record(self, outcome):
        if not isinstance(outcome, SimulationEpisodeOutcome):
            raise TypeError("outcome必须是SimulationEpisodeOutcome")
        field = outcome.end_reason.value
        return replace(self, **{field: getattr(self, field) + 1})

    @classmethod
    def from_outcomes(cls, outcomes):
        try:
            iterator = iter(outcomes)
        except TypeError:
            raise TypeError("outcomes必须是模拟结果可迭代对象") from None
        counts = cls()
        for outcome in iterator:
            counts = counts.record(outcome)
        return counts

    def to_dict(self):
        return {
            reason.value: getattr(self, reason.value)
            for reason in EpisodeEndReason
        }
