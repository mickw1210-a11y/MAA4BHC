import unittest

from app.minigames.simulation_actions import (
    ActionCandidate,
    ActionClass,
    LegalActionSet,
    UnsafeActionEnumerationError,
)
from app.minigames.simulation_state import SimulationState
from app.strategy_contract import LogicalAction


class SimulationActionSetTests(unittest.TestCase):
    def state(self):
        return SimulationState(
            game_id="candy-party",
            rules_version="fixture-v1",
            state_schema="test-fixture.v1",
            state_data={"step": 0},
        )

    def candidate(self, target, action_class=ActionClass.GAMEPLAY, evidence="fixture-rule-1"):
        return ActionCandidate(
            action=LogicalAction("select", target),
            action_class=action_class,
            rule_evidence_ref=evidence,
        )

    def test_verified_gameplay_candidates_bind_to_state_and_reach_strategy(self):
        state = self.state()
        candidates = (
            self.candidate("slot:1"),
            self.candidate("slot:2", evidence="fixture-rule-2"),
        )
        action_set = LegalActionSet.from_candidates(state, iter(candidates))
        self.assertEqual(action_set.state_fingerprint, state.fingerprint)
        self.assertEqual(
            action_set.logical_actions,
            tuple(item.action for item in candidates),
        )
        self.assertFalse(action_set.is_empty)

    def test_auxiliary_purchase_restart_and_unknown_candidates_are_rejected(self):
        blocked = (
            (ActionClass.AUXILIARY_ITEM, "auxiliary_item_forbidden"),
            (ActionClass.PURCHASE, "purchase_forbidden"),
            (ActionClass.RESTART, "restart_forbidden"),
            (ActionClass.UNKNOWN, "action_class_unknown"),
        )
        for category, expected_code in blocked:
            with self.subTest(category=category):
                with self.assertRaises(UnsafeActionEnumerationError) as error:
                    LegalActionSet.from_candidates(
                        self.state(), (self.candidate("target", category, evidence=None),),
                    )
                self.assertEqual(error.exception.code, expected_code)

    def test_unknown_rule_classification_and_unlinked_gameplay_fail_closed(self):
        with self.assertRaisesRegex(TypeError, "ActionClass"):
            ActionCandidate(LogicalAction("select", "slot:1"), "gameplay", "rule-1")
        with self.assertRaisesRegex(ValueError, "规则证据"):
            ActionCandidate(LogicalAction("select", "slot:1"), ActionClass.GAMEPLAY)
        with self.assertRaisesRegex(ValueError, "非空文本"):
            ActionCandidate(
                LogicalAction("select", "slot:1"), ActionClass.GAMEPLAY, " ",
            )

    def test_duplicate_logical_actions_are_rejected(self):
        candidate = self.candidate("slot:1")
        with self.assertRaisesRegex(UnsafeActionEnumerationError, "重复") as error:
            LegalActionSet.from_candidates(self.state(), (candidate, candidate))
        self.assertEqual(error.exception.code, "duplicate_action")

    def test_empty_set_is_not_mislabeled_as_terminal_or_deadlock(self):
        action_set = LegalActionSet.from_candidates(self.state(), ())
        self.assertTrue(action_set.is_empty)
        self.assertEqual(action_set.logical_actions, ())

    def test_direct_constructor_cannot_bypass_action_class_gate(self):
        unsafe = self.candidate("buy:item", ActionClass.PURCHASE, evidence=None)
        with self.assertRaises(UnsafeActionEnumerationError):
            LegalActionSet(self.state(), (unsafe,))

    def test_bad_candidate_container_and_candidate_types_are_rejected(self):
        with self.assertRaisesRegex(TypeError, "可迭代"):
            LegalActionSet.from_candidates(self.state(), None)
        with self.assertRaisesRegex(TypeError, "ActionCandidate"):
            LegalActionSet(self.state(), (LogicalAction("select", "slot:1"),))


if __name__ == "__main__":
    unittest.main()
