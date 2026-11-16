import unittest

from app.minigames.simulation_actions import ActionCandidate, ActionClass
from app.minigames.simulation_state import SimulationState
from app.minigames.simulation_transition import (
    CostStatus,
    ResourceCost,
    SimulationCost,
    SimulationTransition,
    TransitionStatus,
)
from app.strategy_contract import LogicalAction


class SimulationTransitionTests(unittest.TestCase):
    def state(self, step=0, *, game_id="candy-party", rules_version="fixture-v1"):
        return SimulationState(
            game_id=game_id,
            rules_version=rules_version,
            state_schema="test-fixture.v1",
            state_data={"step": step},
        )

    def action(self, action_class=ActionClass.GAMEPLAY):
        return ActionCandidate(
            LogicalAction("select", "slot:1"),
            action_class,
            "fixture-rule-action" if action_class is ActionClass.GAMEPLAY else None,
        )

    def test_applied_effect_requires_known_cost_and_rule_basis(self):
        before = self.state()
        after = self.state(step=1)
        cost = SimulationCost.known(
            (ResourceCost("fixture-resource", 2),), evidence_ref="fixture-cost-rule",
        )
        result = SimulationTransition.applied(
            before, self.action(), cost, after, effect_evidence_ref="fixture-effect-rule",
        )
        self.assertIs(result.status, TransitionStatus.APPLIED)
        self.assertEqual(result.cost.entries[0].amount, 2)
        self.assertEqual(result.effect_evidence_ref, "fixture-effect-rule")

    def test_unknown_cost_never_becomes_zero_or_an_applied_effect(self):
        self.assertIs(SimulationCost.unknown("成本规则未核实").status, CostStatus.UNKNOWN)
        with self.assertRaisesRegex(ValueError, "成本必须已知"):
            SimulationTransition.applied(
                self.state(), self.action(), SimulationCost.unknown("未核实"), self.state(step=1),
                effect_evidence_ref="fixture-effect-rule",
            )

    def test_known_zero_cost_requires_evidence(self):
        cost = SimulationCost.known(evidence_ref="fixture-free-rule")
        self.assertTrue(cost.is_zero)
        with self.assertRaisesRegex(ValueError, "evidence_ref"):
            SimulationCost.known()

    def test_invalid_action_has_zero_cost_and_unchanged_state(self):
        before = self.state()
        result = SimulationTransition.invalid(
            before,
            self.action(),
            cost_evidence_ref="fixture-invalid-cost-rule",
            effect_evidence_ref="fixture-invalid-action-rule",
            reason="fixture action is not legal in this state",
        )
        self.assertIs(result.status, TransitionStatus.INVALID)
        self.assertTrue(result.cost.is_zero)
        self.assertEqual(result.state_after.fingerprint, before.fingerprint)

    def test_invalid_action_rejects_cost_or_changed_state(self):
        before = self.state()
        with self.assertRaisesRegex(ValueError, "零成本"):
            SimulationTransition(
                before, self.action(), TransitionStatus.INVALID,
                SimulationCost.known((ResourceCost("fixture-resource", 1),), evidence_ref="cost"),
                before, "rule", "invalid",
            )
        with self.assertRaisesRegex(ValueError, "不能改变"):
            SimulationTransition(
                before, self.action(), TransitionStatus.INVALID,
                SimulationCost.known(evidence_ref="cost"), self.state(step=1), "rule", "invalid",
            )

    def test_unknown_effect_has_no_asserted_post_state(self):
        result = SimulationTransition.unknown(
            self.state(), self.action(), reason="转移规则未核实",
        )
        self.assertIs(result.status, TransitionStatus.UNKNOWN)
        self.assertIsNone(result.state_after)
        self.assertIs(result.cost.status, CostStatus.UNKNOWN)
        self.assertEqual(result.cost.reason, "转移规则未核实")

    def test_unknown_transition_can_preserve_known_cost_without_claiming_effect(self):
        known_cost = SimulationCost.known(
            (ResourceCost("fixture-resource", 1),), evidence_ref="fixture-cost-rule",
        )
        result = SimulationTransition.unknown(
            self.state(), self.action(), reason="效果规则缺失", cost=known_cost,
        )
        self.assertIs(result.cost.status, CostStatus.KNOWN)
        self.assertIsNone(result.state_after)

    def test_effect_cannot_change_game_version_or_schema(self):
        with self.assertRaisesRegex(ValueError, "同一游戏"):
            SimulationTransition.applied(
                self.state(), self.action(), SimulationCost.known(evidence_ref="cost"),
                self.state(step=1, game_id="animal-bath"), effect_evidence_ref="effect",
            )
        with self.assertRaisesRegex(ValueError, "同一游戏"):
            SimulationTransition.applied(
                self.state(), self.action(), SimulationCost.known(evidence_ref="cost"),
                self.state(step=1, rules_version="fixture-v2"), effect_evidence_ref="effect",
            )

    def test_only_gameplay_candidates_can_have_simulation_transitions(self):
        with self.assertRaisesRegex(ValueError, "gameplay"):
            SimulationTransition.unknown(
                self.state(), self.action(ActionClass.PURCHASE), reason="禁止购买",
            )

    def test_resource_cost_validation_is_explicit_and_unique(self):
        with self.assertRaisesRegex(ValueError, "非负整数"):
            ResourceCost("fixture-resource", True)
        with self.assertRaisesRegex(ValueError, "不能重复"):
            SimulationCost.known(
                (ResourceCost("fixture-resource", 1), ResourceCost("fixture-resource", 2)),
                evidence_ref="fixture-cost-rule",
            )
        with self.assertRaisesRegex(ValueError, "unknown成本"):
            SimulationCost(CostStatus.UNKNOWN, (ResourceCost("fixture-resource", 1),), reason="unknown")


if __name__ == "__main__":
    unittest.main()
