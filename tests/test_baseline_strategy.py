import unittest

from app.minigames.baseline_strategy import DeterministicLegalActionBaseline
from app.minigames.simulation_state import SimulationState
from app.observation import ObservedValue
from app.strategy_contract import LogicalAction, StrategyDecision


class DeterministicLegalActionBaselineTests(unittest.TestCase):
    def setUp(self):
        self.strategy = DeterministicLegalActionBaseline()
        self.state = SimulationState(
            game_id="candy-party",
            rules_version="fixture-v1",
            state_schema="test-fixture.v1",
            state_data={"step": 0},
        )
        self.budget = {"fixture-energy": ObservedValue.observed(3)}
        self.actions = (
            LogicalAction("match", "slot:2"),
            LogicalAction("match", "slot:1"),
            LogicalAction("swap", "slot:3"),
        )

    def choose(self, *, actions=None, budget=None):
        return self.strategy.choose_action(
            state=self.state,
            legal_actions=self.actions if actions is None else actions,
            budget=self.budget if budget is None else budget,
        )

    def test_selects_same_sorted_legal_action_independent_of_input_order(self):
        expected = StrategyDecision(action=LogicalAction("match", "slot:1"))
        self.assertEqual(self.choose(), expected)
        self.assertEqual(self.choose(actions=tuple(reversed(self.actions))), expected)

    def test_empty_candidates_pause_without_claiming_episode_terminal(self):
        result = self.choose(actions=())
        self.assertIsNone(result.action)
        self.assertEqual(result.pause_reason, "no_candidates")

    def test_missing_or_unknown_budget_pauses(self):
        self.assertEqual(self.choose(budget={}).pause_reason, "budget_unavailable")
        result = self.choose(budget={
            "fixture-energy": ObservedValue.unknown("fixture budget unread"),
        })
        self.assertEqual(result.pause_reason, "budget_unknown:fixture-energy")

    def test_unknown_budget_pause_is_independent_of_mapping_order(self):
        budget_a = {
            "zeta": ObservedValue.unknown("unknown"),
            "alpha": ObservedValue.unknown("unknown"),
        }
        budget_b = dict(reversed(tuple(budget_a.items())))
        self.assertEqual(self.choose(budget=budget_a), self.choose(budget=budget_b))
        self.assertEqual(self.choose(budget=budget_a).pause_reason, "budget_unknown:alpha")

    def test_rejects_invalid_budget_values(self):
        for value in (True, -1, float("inf"), "3"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "有限非负数"):
                    self.choose(budget={"fixture-energy": ObservedValue.observed(value)})
        with self.assertRaisesRegex(TypeError, "ObservedValue"):
            self.choose(budget={"fixture-energy": 3})

    def test_large_integer_budget_remains_a_valid_observed_integer(self):
        result = self.choose(budget={
            "fixture-energy": ObservedValue.observed(10 ** 1000),
        })
        self.assertEqual(result.action, LogicalAction("match", "slot:1"))

    def test_rejects_invalid_state_or_action_shapes(self):
        with self.assertRaisesRegex(TypeError, "SimulationState"):
            self.strategy.choose_action(
                state={}, legal_actions=self.actions, budget=self.budget,
            )
        with self.assertRaisesRegex(TypeError, "元组"):
            self.choose(actions=list(self.actions))
        with self.assertRaisesRegex(TypeError, "LogicalAction"):
            self.choose(actions=(object(),))
        with self.assertRaisesRegex(ValueError, "不能重复"):
            self.choose(actions=(self.actions[0], self.actions[0]))

    def test_does_not_mutate_state_actions_or_budget(self):
        actions = self.actions
        budget = dict(self.budget)
        state_fingerprint = self.state.fingerprint
        self.choose(actions=actions, budget=budget)
        self.assertEqual(actions, self.actions)
        self.assertEqual(budget, self.budget)
        self.assertEqual(self.state.fingerprint, state_fingerprint)


if __name__ == "__main__":
    unittest.main()
