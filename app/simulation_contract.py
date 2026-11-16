"""Rule simulation interface separated from device execution."""

from typing import Protocol

from app.minigames.simulation_actions import ActionCandidate
from app.minigames.simulation_state import SimulationRandomInput, SimulationState
from app.minigames.simulation_transition import SimulationTransition


class SimulationRules(Protocol):
    """Pure game-specific rules model; random input is limited to this step."""

    def legal_actions(self, state: SimulationState) -> tuple[ActionCandidate, ...]:
        ...

    def apply(
        self,
        state: SimulationState,
        action: ActionCandidate,
        *,
        random_input: SimulationRandomInput,
    ) -> SimulationTransition:
        ...
