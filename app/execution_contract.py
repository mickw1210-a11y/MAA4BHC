"""Device execution interface with no concrete controller import."""

from typing import Protocol

from app.action_contract import ActionIntent
from app.action_result import ActionResult
from app.observation import Observation


class DeviceExecutor(Protocol):
    """Boundary for a later adapter that submits one guarded action."""

    def submit(
        self,
        action: ActionIntent,
        current_observation: Observation,
    ) -> ActionResult:
        ...
