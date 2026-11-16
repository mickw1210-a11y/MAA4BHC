"""Versioned, serializable records for replaying pure simulation episodes."""

import json
from dataclasses import dataclass

from app.minigames.simulation_actions import ActionCandidate, ActionClass, LegalActionSet
from app.minigames.simulation_outcome import (
    EpisodeEndReason,
    SimulationEpisodeOutcome,
)
from app.minigames.simulation_state import SimulationRandomInput, SimulationState
from app.minigames.simulation_transition import (
    CostStatus,
    ResourceCost,
    SimulationCost,
    SimulationTransition,
    TransitionStatus,
)
from app.strategy_contract import LogicalAction


TRACE_SCHEMA_VERSION = 1


def _require_object(data, expected_keys, field):
    if not isinstance(data, dict) or set(data) != set(expected_keys):
        raise ValueError(f"{field}结构或字段无效")


def _require_uint64(name, value):
    if type(value) is not int or value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"{name}必须是无符号64位整数")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON字段重复：{key}")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"JSON常量无效：{value}")


def _candidate_to_dict(candidate):
    return {
        "kind": candidate.action.kind,
        "target": candidate.action.target,
        "action_class": candidate.action_class.value,
        "rule_evidence_ref": candidate.rule_evidence_ref,
    }


def _candidate_from_dict(data):
    _require_object(
        data,
        {"kind", "target", "action_class", "rule_evidence_ref"},
        "动作候选",
    )
    return ActionCandidate(
        action=LogicalAction(data["kind"], data["target"]),
        action_class=ActionClass(data["action_class"]),
        rule_evidence_ref=data["rule_evidence_ref"],
    )


def _cost_to_dict(cost):
    return {
        "status": cost.status.value,
        "entries": [
            {"resource_id": entry.resource_id, "amount": entry.amount}
            for entry in cost.entries
        ],
        "evidence_ref": cost.evidence_ref,
        "reason": cost.reason,
    }


def _cost_from_dict(data):
    _require_object(data, {"status", "entries", "evidence_ref", "reason"}, "成本")
    if not isinstance(data["entries"], list):
        raise ValueError("成本entries必须是列表")
    entries = []
    for entry in data["entries"]:
        _require_object(entry, {"resource_id", "amount"}, "资源成本")
        entries.append(ResourceCost(entry["resource_id"], entry["amount"]))
    return SimulationCost(
        status=CostStatus(data["status"]),
        entries=tuple(entries),
        evidence_ref=data["evidence_ref"],
        reason=data["reason"],
    )


def _transition_to_dict(transition):
    return {
        "state_before": transition.state_before.to_dict(),
        "action": _candidate_to_dict(transition.action),
        "status": transition.status.value,
        "cost": _cost_to_dict(transition.cost),
        "state_after": (
            transition.state_after.to_dict() if transition.state_after is not None else None
        ),
        "effect_evidence_ref": transition.effect_evidence_ref,
        "reason": transition.reason,
    }


def _transition_from_dict(data):
    _require_object(
        data,
        {
            "state_before", "action", "status", "cost", "state_after",
            "effect_evidence_ref", "reason",
        },
        "模拟转移",
    )
    state_after = (
        SimulationState.from_dict(data["state_after"])
        if data["state_after"] is not None else None
    )
    return SimulationTransition(
        state_before=SimulationState.from_dict(data["state_before"]),
        action=_candidate_from_dict(data["action"]),
        status=TransitionStatus(data["status"]),
        cost=_cost_from_dict(data["cost"]),
        state_after=state_after,
        effect_evidence_ref=data["effect_evidence_ref"],
        reason=data["reason"],
    )


def _outcome_to_dict(outcome):
    legal_actions = None
    if outcome.legal_actions is not None:
        legal_actions = {
            "state_fingerprint": outcome.legal_actions.state_fingerprint,
            "candidates": [
                _candidate_to_dict(candidate)
                for candidate in outcome.legal_actions.candidates
            ],
        }
    return {
        "last_state": outcome.last_state.to_dict(),
        "end_reason": outcome.end_reason.value,
        "evidence_ref": outcome.evidence_ref,
        "detail": outcome.detail,
        "legal_actions": legal_actions,
    }


def _outcome_from_dict(data):
    _require_object(
        data,
        {"last_state", "end_reason", "evidence_ref", "detail", "legal_actions"},
        "episode结果",
    )
    last_state = SimulationState.from_dict(data["last_state"])
    legal_data = data["legal_actions"]
    legal_actions = None
    if legal_data is not None:
        _require_object(legal_data, {"state_fingerprint", "candidates"}, "合法动作集合")
        if not isinstance(legal_data["candidates"], list):
            raise ValueError("合法动作candidates必须是列表")
        if legal_data["state_fingerprint"] != last_state.fingerprint:
            raise ValueError("合法动作集合指纹与episode结果状态不符")
        legal_actions = LegalActionSet.from_candidates(
            last_state,
            tuple(_candidate_from_dict(item) for item in legal_data["candidates"]),
        )
    return SimulationEpisodeOutcome(
        last_state=last_state,
        end_reason=EpisodeEndReason(data["end_reason"]),
        evidence_ref=data["evidence_ref"],
        detail=data["detail"],
        legal_actions=legal_actions,
    )


@dataclass(frozen=True, slots=True)
class SimulationTraceStep:
    """One action and its exact random input and transition result."""

    step_index: int
    random_input: SimulationRandomInput
    transition: SimulationTransition

    def __post_init__(self):
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("step_index必须是非负整数")
        if not isinstance(self.random_input, SimulationRandomInput):
            raise TypeError("random_input必须是SimulationRandomInput")
        if self.random_input.step_index != self.step_index:
            raise ValueError("step_index必须与random_input一致")
        if not isinstance(self.transition, SimulationTransition):
            raise TypeError("transition必须是SimulationTransition")


@dataclass(frozen=True, slots=True)
class SimulationTrace:
    """A complete serializable episode trace, not a game rules adapter."""

    game_id: str
    rules_version: str
    seed: int
    initial_state: SimulationState
    steps: tuple
    outcome: SimulationEpisodeOutcome

    def __post_init__(self):
        if not isinstance(self.game_id, str) or not self.game_id.strip():
            raise ValueError("game_id必须是非空文本")
        if not isinstance(self.rules_version, str) or not self.rules_version.strip():
            raise ValueError("rules_version必须是非空文本")
        _require_uint64("seed", self.seed)
        if not isinstance(self.initial_state, SimulationState):
            raise TypeError("initial_state必须是SimulationState")
        if (self.initial_state.game_id, self.initial_state.rules_version) != (
            self.game_id, self.rules_version,
        ):
            raise ValueError("轨迹game_id／rules_version必须与初始状态一致")
        if not isinstance(self.steps, tuple) or any(
            not isinstance(step, SimulationTraceStep) for step in self.steps
        ):
            raise TypeError("steps必须是SimulationTraceStep元组")
        if not isinstance(self.outcome, SimulationEpisodeOutcome):
            raise TypeError("outcome必须是SimulationEpisodeOutcome")

        current_state = self.initial_state
        for expected_index, step in enumerate(self.steps):
            if step.step_index != expected_index:
                raise ValueError("轨迹step_index必须从0开始连续递增")
            if step.random_input.seed != self.seed:
                raise ValueError("每步random_input必须使用轨迹seed")
            transition = step.transition
            before = transition.state_before
            if (before.game_id, before.rules_version, before.state_schema) != (
                self.game_id, self.rules_version, self.initial_state.state_schema,
            ):
                raise ValueError("每步状态必须保持轨迹游戏、规则版本和schema")
            if before.fingerprint != current_state.fingerprint:
                raise ValueError("每步state_before必须接续前一步已知状态")
            if transition.status is TransitionStatus.UNKNOWN:
                if expected_index != len(self.steps) - 1:
                    raise ValueError("unknown转移必须是最后一步")
                if self.outcome.end_reason is not EpisodeEndReason.UNKNOWN:
                    raise ValueError("unknown转移必须以unknown作为episode终止原因")
            else:
                current_state = transition.state_after

        outcome_state = self.outcome.last_state
        if (outcome_state.game_id, outcome_state.rules_version, outcome_state.state_schema) != (
            self.game_id, self.rules_version, self.initial_state.state_schema,
        ):
            raise ValueError("episode结果必须保持轨迹游戏、规则版本和schema")
        if outcome_state.fingerprint != current_state.fingerprint:
            raise ValueError("episode结果状态必须等于轨迹最后一个已知状态")

    def to_dict(self):
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "game_id": self.game_id,
            "rules_version": self.rules_version,
            "seed": self.seed,
            "initial_state": self.initial_state.to_dict(),
            "steps": [
                {
                    "step_index": step.step_index,
                    "random_input": step.random_input.to_dict(),
                    "transition": _transition_to_dict(step.transition),
                }
                for step in self.steps
            ],
            "outcome": _outcome_to_dict(self.outcome),
        }

    def to_json(self):
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, data):
        _require_object(
            data,
            {"schema_version", "game_id", "rules_version", "seed", "initial_state", "steps", "outcome"},
            "模拟轨迹",
        )
        if type(data["schema_version"]) is not int or data["schema_version"] != TRACE_SCHEMA_VERSION:
            raise ValueError("模拟轨迹schema版本无效")
        if not isinstance(data["steps"], list):
            raise ValueError("steps必须是列表")
        steps = []
        for item in data["steps"]:
            _require_object(item, {"step_index", "random_input", "transition"}, "轨迹步骤")
            steps.append(SimulationTraceStep(
                step_index=item["step_index"],
                random_input=SimulationRandomInput.from_dict(item["random_input"]),
                transition=_transition_from_dict(item["transition"]),
            ))
        return cls(
            game_id=data["game_id"],
            rules_version=data["rules_version"],
            seed=data["seed"],
            initial_state=SimulationState.from_dict(data["initial_state"]),
            steps=tuple(steps),
            outcome=_outcome_from_dict(data["outcome"]),
        )

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, str):
            raise TypeError("模拟轨迹JSON必须是文本")
        try:
            decoded = json.loads(
                data,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, RecursionError):
            raise ValueError("模拟轨迹JSON无效") from None
        return cls.from_dict(decoded)
