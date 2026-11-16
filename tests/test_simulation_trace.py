import copy
import unittest

from app.minigames.simulation_actions import ActionCandidate, ActionClass, LegalActionSet
from app.minigames.simulation_outcome import SimulationEpisodeOutcome
from app.minigames.simulation_state import SimulationRandomInput, SimulationState
from app.minigames.simulation_trace import (
    SimulationTrace,
    SimulationTraceStep,
)
from app.minigames.simulation_transition import (
    ResourceCost,
    SimulationCost,
    SimulationTransition,
    TransitionStatus,
)
from app.strategy_contract import LogicalAction


class SimulationTraceTests(unittest.TestCase):
    seed = 17

    def state(self, step, *, rules_version="fixture-v1"):
        return SimulationState(
            game_id="candy-party",
            rules_version=rules_version,
            state_schema="test-fixture.v1",
            state_data={"step": step},
        )

    def action(self):
        return ActionCandidate(
            LogicalAction("select", "slot:1"),
            ActionClass.GAMEPLAY,
            "fixture-action-rule",
        )

    def applied(self, before, after):
        return SimulationTransition.applied(
            before,
            self.action(),
            SimulationCost.known(
                (ResourceCost("fixture-move", 1),), evidence_ref="fixture-cost-rule",
            ),
            after,
            effect_evidence_ref="fixture-effect-rule",
        )

    def step(self, index, transition, *, seed=None):
        actual_seed = self.seed if seed is None else seed
        return SimulationTraceStep(
            step_index=index,
            random_input=SimulationRandomInput.for_step(actual_seed, index, 2),
            transition=transition,
        )

    def test_multi_step_trace_round_trips_json_with_states_costs_and_random_inputs(self):
        initial = self.state(0)
        middle = self.state(1)
        final = self.state(2)
        trace = SimulationTrace(
            game_id="candy-party",
            rules_version="fixture-v1",
            seed=self.seed,
            initial_state=initial,
            steps=(
                self.step(0, self.applied(initial, middle)),
                self.step(1, self.applied(middle, final)),
            ),
            outcome=SimulationEpisodeOutcome.completed(
                final, evidence_ref="fixture-completion-rule",
            ),
        )

        decoded = SimulationTrace.from_json(trace.to_json())
        self.assertEqual(decoded, trace)
        self.assertEqual(decoded.steps[1].random_input.draws, trace.steps[1].random_input.draws)
        self.assertEqual(decoded.steps[0].transition.state_after.fingerprint, middle.fingerprint)
        self.assertEqual(decoded.outcome.last_state.fingerprint, final.fingerprint)

    def test_no_action_episode_round_trips_with_explicit_terminal_evidence(self):
        state = self.state(0)
        outcome = SimulationEpisodeOutcome.no_legal_actions(
            state,
            LegalActionSet.from_candidates(state, ()),
            evidence_ref="fixture-empty-action-rule",
        )
        trace = SimulationTrace(
            "candy-party", "fixture-v1", self.seed, state, (), outcome,
        )
        self.assertEqual(SimulationTrace.from_dict(trace.to_dict()), trace)

    def test_unknown_transition_must_be_last_and_match_unknown_outcome(self):
        state = self.state(0)
        unknown = SimulationTransition.unknown(
            state, self.action(), reason="fixture transition unknown",
        )
        trace = SimulationTrace(
            "candy-party",
            "fixture-v1",
            self.seed,
            state,
            (self.step(0, unknown),),
            SimulationEpisodeOutcome.unknown(state, detail="fixture transition unknown"),
        )
        self.assertEqual(SimulationTrace.from_json(trace.to_json()), trace)

        with self.assertRaisesRegex(ValueError, "终止原因"):
            SimulationTrace(
                "candy-party", "fixture-v1", self.seed, state,
                (self.step(0, unknown),),
                SimulationEpisodeOutcome.timeout(state, detail="fixture timeout"),
            )

    def test_unknown_transition_cannot_have_a_later_step(self):
        state = self.state(0)
        unknown = SimulationTransition.unknown(
            state, self.action(), reason="fixture transition unknown",
        )
        after = self.state(1)
        with self.assertRaisesRegex(ValueError, "必须是最后一步"):
            SimulationTrace(
                "candy-party",
                "fixture-v1",
                self.seed,
                state,
                (self.step(0, unknown), self.step(1, self.applied(state, after))),
                SimulationEpisodeOutcome.unknown(after, detail="fixture unknown"),
            )

    def test_each_step_must_continue_from_previous_known_state(self):
        initial = self.state(0)
        skipped = self.state(9)
        final = self.state(2)
        with self.assertRaisesRegex(ValueError, "接续前一步"):
            SimulationTrace(
                "candy-party",
                "fixture-v1",
                self.seed,
                initial,
                (
                    self.step(0, self.applied(initial, self.state(1))),
                    self.step(1, self.applied(skipped, final)),
                ),
                SimulationEpisodeOutcome.completed(final, evidence_ref="fixture-rule"),
            )

    def test_seed_and_step_indices_must_match_random_inputs_and_trace(self):
        initial = self.state(0)
        final = self.state(1)
        transition = self.applied(initial, final)
        with self.assertRaisesRegex(ValueError, "轨迹seed"):
            SimulationTrace(
                "candy-party", "fixture-v1", self.seed, initial,
                (self.step(0, transition, seed=self.seed + 1),),
                SimulationEpisodeOutcome.completed(final, evidence_ref="fixture-rule"),
            )

        wrong_index = SimulationTraceStep(
            2, SimulationRandomInput.for_step(self.seed, 2, 2), transition,
        )
        with self.assertRaisesRegex(ValueError, "从0开始连续"):
            SimulationTrace(
                "candy-party", "fixture-v1", self.seed, initial,
                (wrong_index,),
                SimulationEpisodeOutcome.completed(final, evidence_ref="fixture-rule"),
            )

    def test_outcome_must_match_last_known_trace_state(self):
        initial = self.state(0)
        after = self.state(1)
        other = self.state(99)
        with self.assertRaisesRegex(ValueError, "最后一个已知状态"):
            SimulationTrace(
                "candy-party", "fixture-v1", self.seed, initial,
                (self.step(0, self.applied(initial, after)),),
                SimulationEpisodeOutcome.completed(other, evidence_ref="fixture-rule"),
            )

    def test_trace_rejects_game_or_rule_version_mismatch(self):
        initial = self.state(0)
        outcome = SimulationEpisodeOutcome.completed(initial, evidence_ref="fixture-rule")
        with self.assertRaisesRegex(ValueError, "game_id／rules_version"):
            SimulationTrace(
                "animal-bath", "fixture-v1", self.seed, initial, (), outcome,
            )
        with self.assertRaisesRegex(ValueError, "game_id／rules_version"):
            SimulationTrace(
                "candy-party", "fixture-v2", self.seed, initial, (), outcome,
            )

    def test_deserializer_rejects_unknown_schema_and_extra_fields(self):
        state = self.state(0)
        trace = SimulationTrace(
            "candy-party",
            "fixture-v1",
            self.seed,
            state,
            (),
            SimulationEpisodeOutcome.completed(state, evidence_ref="fixture-rule"),
        )
        unknown_version = copy.deepcopy(trace.to_dict())
        unknown_version["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "schema版本"):
            SimulationTrace.from_dict(unknown_version)
        extra_field = copy.deepcopy(trace.to_dict())
        extra_field["hidden_future_state"] = {"step": 100}
        with self.assertRaisesRegex(ValueError, "结构或字段"):
            SimulationTrace.from_dict(extra_field)

    def test_non_json_input_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "必须是文本"):
            SimulationTrace.from_json({})
        with self.assertRaisesRegex(ValueError, "JSON无效"):
            SimulationTrace.from_json("not-json")
        with self.assertRaisesRegex(ValueError, "JSON常量无效"):
            SimulationTrace.from_json('{"bad": NaN}')
        with self.assertRaisesRegex(ValueError, "JSON字段重复"):
            SimulationTrace.from_json('{"schema_version": 1, "schema_version": 1}')


if __name__ == "__main__":
    unittest.main()
