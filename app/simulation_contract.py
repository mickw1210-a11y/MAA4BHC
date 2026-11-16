"""Rule simulation interface separated from device execution."""

from typing import Protocol

from app.strategy_contract import LogicalAction


class SimulationRules(Protocol):
    """Pure rules model; random input is explicit and limited to this step."""

    def legal_actions(self, state: object) -> tuple[LogicalAction, ...]:
        ...

    def apply(
        self,
        state: object,
        action: LogicalAction,
        *,
        random_input: object,
    ) -> object:
        ...
