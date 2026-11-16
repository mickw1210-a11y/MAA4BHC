import unittest

from app.minigames.simulation_actions import LegalActionSet
from app.minigames.simulation_outcome import (
    EpisodeEndReason,
    SimulationEpisodeOutcome,
    SimulationOutcomeCounts,
)
from app.minigames.simulation_state import SimulationState


class SimulationOutcomeTests(unittest.TestCase):
    def state(self, step=0):
        return SimulationState(
            game_id="candy-party",
            rules_version="fixture-v1",
            state_schema="test-fixture.v1",
            state_data={"step": step},
        )

    def test_five_end_reasons_are_explicit_and_counted_separately(self):
        state = self.state()
        empty = LegalActionSet.from_candidates(state, ())
        outcomes = (
            SimulationEpisodeOutcome.completed(state, evidence_ref="fixture-complete-rule"),
            SimulationEpisodeOutcome.no_legal_actions(
                state, empty, evidence_ref="fixture-action-enumerator-rule",
            ),
            SimulationEpisodeOutcome.unknown(state, detail="fixture unknown reason"),
            SimulationEpisodeOutcome.timeout(state, detail="fixture time budget exhausted"),
            SimulationEpisodeOutcome.threshold_stop(state, detail="fixture stop threshold reached"),
        )

        self.assertEqual(
            tuple(outcome.end_reason for outcome in outcomes),
            tuple(EpisodeEndReason),
        )
        counts = SimulationOutcomeCounts.from_outcomes(outcomes)
        self.assertEqual(counts.to_dict(), {reason.value: 1 for reason in EpisodeEndReason})
        self.assertEqual(counts.total, 5)

    def test_no_legal_actions_requires_empty_set_bound_to_last_state(self):
        state = self.state()
        with self.assertRaisesRegex(ValueError, "存在合法动作"):
            SimulationEpisodeOutcome.no_legal_actions(
                state,
                LegalActionSet.from_candidates(state, (self._candidate(),)),
                evidence_ref="fixture-rule",
            )
        with self.assertRaisesRegex(ValueError, "绑定最后一个"):
            SimulationEpisodeOutcome.no_legal_actions(
                self.state(step=1),
                LegalActionSet.from_candidates(state, ()),
                evidence_ref="fixture-rule",
            )

    def test_no_legal_actions_requires_an_explicit_rule_reference(self):
        state = self.state()
        empty = LegalActionSet.from_candidates(state, ())
        with self.assertRaisesRegex(ValueError, "evidence_ref"):
            SimulationEpisodeOutcome.no_legal_actions(state, empty, evidence_ref=" ")

    def test_normal_completion_requires_rule_evidence(self):
        with self.assertRaisesRegex(ValueError, "evidence_ref"):
            SimulationEpisodeOutcome.completed(self.state(), evidence_ref=" ")

    def test_other_outcomes_require_details_and_do_not_claim_no_actions(self):
        state = self.state()
        with self.assertRaisesRegex(ValueError, "detail"):
            SimulationEpisodeOutcome.timeout(state, detail=" ")
        empty = LegalActionSet.from_candidates(state, ())
        with self.assertRaisesRegex(ValueError, "不能附带无合法动作断言"):
            SimulationEpisodeOutcome(
                state,
                EpisodeEndReason.TIMEOUT,
                detail="fixture timeout",
                legal_actions=empty,
            )

    def test_counts_are_immutable_and_each_record_updates_only_its_reason(self):
        state = self.state()
        before = SimulationOutcomeCounts()
        after = before.record(SimulationEpisodeOutcome.unknown(state, detail="fixture unknown"))
        self.assertEqual(before.total, 0)
        self.assertEqual(after.unknown, 1)
        self.assertEqual(after.no_legal_actions, 0)
        self.assertEqual(after.normal_completion, 0)

    def test_counts_reject_negative_and_boolean_values(self):
        with self.assertRaisesRegex(ValueError, "非负整数"):
            SimulationOutcomeCounts(timeout=-1)
        with self.assertRaisesRegex(ValueError, "非负整数"):
            SimulationOutcomeCounts(timeout=True)

    def test_counting_rejects_non_outcome_values(self):
        with self.assertRaisesRegex(TypeError, "outcome必须"):
            SimulationOutcomeCounts().record(object())
        with self.assertRaisesRegex(TypeError, "可迭代"):
            SimulationOutcomeCounts.from_outcomes(None)

    def _candidate(self):
        from app.minigames.simulation_actions import ActionCandidate, ActionClass
        from app.strategy_contract import LogicalAction

        return ActionCandidate(
            LogicalAction("select", "slot:1"),
            ActionClass.GAMEPLAY,
            "fixture-action-rule",
        )


if __name__ == "__main__":
    unittest.main()
