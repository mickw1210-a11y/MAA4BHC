"""Pure action intents and frame-freshness checks; no device access."""

from dataclasses import dataclass

from app.observation import Observation, ObservedValue


class ActionPreconditionError(ValueError):
    """Raised when an action no longer matches the observed device frame."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}必须是非空文本")


@dataclass(frozen=True)
class FrameFingerprint:
    """Identity of the device, exact captured frame, and classified page."""

    device_id: str
    frame_id: str
    page_id: str

    def __post_init__(self):
        _require_text(self.device_id, "device_id")
        _require_text(self.frame_id, "frame_id")
        _require_text(self.page_id, "page_id")

    @classmethod
    def from_observation(cls, observation):
        if not isinstance(observation, Observation):
            raise ActionPreconditionError("observation_invalid", "当前观察数据无效")
        values = {}
        for name in ("device_id", "frame_id", "page_id"):
            observed = getattr(observation, name)
            if not observed.is_known:
                raise ActionPreconditionError(
                    f"{name}_unknown", f"无法确认{name}，拒绝使用该画面动作"
                )
            values[name] = observed.value
        return cls(**values)


@dataclass(frozen=True)
class ActionIntent:
    """Logical action proposal tied to one exact observation fingerprint."""

    action_id: str
    task_id: str
    kind: str
    target: str
    expected_cost: ObservedValue
    expected_postcondition: str
    precondition: FrameFingerprint

    def __post_init__(self):
        for name in (
            "action_id",
            "task_id",
            "kind",
            "target",
            "expected_postcondition",
        ):
            _require_text(getattr(self, name), name)
        if not isinstance(self.expected_cost, ObservedValue):
            raise TypeError("expected_cost必须显式使用ObservedValue或unknown")
        if not isinstance(self.precondition, FrameFingerprint):
            raise TypeError("precondition必须是FrameFingerprint")


def assert_action_precondition(action, current_observation):
    """Reject unknown or stale device/frame/page identity before any dispatch."""
    if not isinstance(action, ActionIntent):
        raise ActionPreconditionError("action_invalid", "动作意图无效")
    current = FrameFingerprint.from_observation(current_observation)
    expected = action.precondition
    for name in ("device_id", "frame_id", "page_id"):
        if getattr(expected, name) != getattr(current, name):
            messages = {
                "device_id": "当前实例与动作生成时不同",
                "frame_id": "画面已变化，旧画面生成的动作已失效",
                "page_id": "当前页面与动作生成时不同",
            }
            raise ActionPreconditionError(f"{name}_changed", messages[name])
