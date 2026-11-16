"""Explicit action submission and verification outcomes."""

from dataclasses import dataclass
from enum import Enum


class ActionOutcome(str, Enum):
    NOT_SUBMITTED = "not_submitted"
    SUBMITTED_UNKNOWN = "submitted_unknown"
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_FAILURE = "verified_failure"


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}必须是非空文本")


@dataclass(frozen=True)
class ActionResult:
    """Classification of one action attempt, separate from tool return codes."""

    action_id: str
    outcome: ActionOutcome
    reason: str | None = None
    verification_observation_id: str | None = None

    def __post_init__(self):
        _require_text(self.action_id, "action_id")
        try:
            outcome = ActionOutcome(self.outcome)
        except (TypeError, ValueError):
            raise ValueError("动作结果状态无效") from None
        object.__setattr__(self, "outcome", outcome)

        if self.reason is not None:
            _require_text(self.reason, "reason")
        if self.verification_observation_id is not None:
            _require_text(self.verification_observation_id, "verification_observation_id")

        verified = outcome in {
            ActionOutcome.VERIFIED_SUCCESS,
            ActionOutcome.VERIFIED_FAILURE,
        }
        if verified and self.verification_observation_id is None:
            raise ValueError("已核实结果必须引用后置观察证据")
        if not verified and self.verification_observation_id is not None:
            raise ValueError("未核实结果不能附带核实观察证据")
        if outcome in {
            ActionOutcome.NOT_SUBMITTED,
            ActionOutcome.SUBMITTED_UNKNOWN,
            ActionOutcome.VERIFIED_FAILURE,
        } and self.reason is None:
            raise ValueError("未提交、结果未知或核实失败必须说明原因")

    @property
    def was_submitted(self):
        return self.outcome is not ActionOutcome.NOT_SUBMITTED

    @property
    def is_verified(self):
        return self.outcome in {
            ActionOutcome.VERIFIED_SUCCESS,
            ActionOutcome.VERIFIED_FAILURE,
        }
