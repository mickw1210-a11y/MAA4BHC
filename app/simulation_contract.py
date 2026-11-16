"""Rule simulation interface separated from device execution."""

from typing import Protocol

from app.minigames.simulation_state import SimulationRandomInput, SimulationState
from app.strategy_contract import LogicalAction


class SimulationRules(Protocol):
    """Pure game-specific rules model; random input is limited to this step."""

    def legal_actions(self, state: SimulationState) -> tuple[LogicalAction, ...]:
        ...

    def apply(
        self,
        state: SimulationState,
        action: LogicalAction,
        *,
        random_input: SimulationRandomInput,
    ) -> SimulationState:
        ...
