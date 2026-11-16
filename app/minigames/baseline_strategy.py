"""Deterministic legal-action baseline for simulation-only comparisons."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from app.minigames.simulation_state import SimulationState
from app.observation import ObservedValue
from app.strategy_contract import LogicalAction, StrategyDecision


def _validate_budget(budget):
    if not isinstance(budget, Mapping):
        raise TypeError("budget必须是资源到ObservedValue的映射")
    normalized = {}
    for resource_id, observed in budget.items():
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("budget资源ID必须是非空文本")
        if not isinstance(observed, ObservedValue):
            raise TypeError("budget值必须是ObservedValue")
        if observed.is_known:
            value = observed.value
            if (type(value) not in (int, float) or value < 0
                    or (type(value) is float and not isfinite(value))):
                raise ValueError("已知budget必须是有限非负数")
        normalized[resource_id] = observed
    return normalized


@dataclass(frozen=True, slots=True)
class DeterministicLegalActionBaseline:
    """Choose the lexically first supplied action; never sends or applies it."""

    def choose_action(self, *, state, legal_actions, budget):
        if not isinstance(state, SimulationState):
            raise TypeError("state必须是SimulationState")
        if not isinstance(legal_actions, tuple):
            raise TypeError("legal_actions必须是LogicalAction元组")
        if any(not isinstance(action, LogicalAction) for action in legal_actions):
            raise TypeError("legal_actions只能包含LogicalAction")
        identities = tuple((action.kind, action.target) for action in legal_actions)
        if len(set(identities)) != len(identities):
            raise ValueError("legal_actions不能重复")

        observed_budget = _validate_budget(budget)
        if not legal_actions:
            return StrategyDecision(pause_reason="no_candidates")
        if not observed_budget:
            return StrategyDecision(pause_reason="budget_unavailable")
        for resource_id in sorted(observed_budget):
            if not observed_budget[resource_id].is_known:
                return StrategyDecision(pause_reason=f"budget_unknown:{resource_id}")

        action = min(legal_actions, key=lambda item: (item.kind, item.target))
        return StrategyDecision(action=action)
