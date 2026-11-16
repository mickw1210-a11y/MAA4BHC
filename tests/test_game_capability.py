import unittest

from app.game_capability import (
    CapabilityEvidence,
    CapabilityState,
    GameCapability,
    SUPPORTED_GAME_IDS,
    initial_game_capabilities,
)


class GameCapabilityTests(unittest.TestCase):
    def test_only_the_five_confirmed_games_are_registered(self):
        self.assertEqual(
            SUPPORTED_GAME_IDS,
            ("candy-party", "skewer-master", "burger-day", "starlight-mix", "animal-bath"),
        )
        capabilities = initial_game_capabilities()
        self.assertEqual(tuple(item.game_id for item in capabilities), SUPPORTED_GAME_IDS)
        self.assertTrue(all(item.state is CapabilityState.RULES_UNVERIFIED for item in capabilities))
        self.assertTrue(all(not item.execution_ready for item in capabilities))

    def test_rules_verified_without_simulator_has_distinct_state(self):
        capability = GameCapability("candy-party", CapabilityEvidence(rules_verified=True))
        self.assertIs(capability.state, CapabilityState.RULES_VERIFIED)
        self.assertEqual(
            capability.evidence.blockers,
            ("simulation_not_passed", "no_deadlock_not_verified", "real_adapter_not_verified"),
        )

    def test_simulation_passed_alone_remains_simulation_only(self):
        evidence = CapabilityEvidence(rules_verified=True, simulation_passed=True)
        capability = GameCapability("skewer-master", evidence)
        self.assertIs(capability.state, CapabilityState.SIMULATION_ONLY)
        self.assertFalse(capability.execution_ready)

    def test_no_deadlock_and_adapter_are_both_required(self):
        no_adapter = CapabilityEvidence(
            rules_verified=True,
            simulation_passed=True,
            no_deadlock_passed=True,
        )
        adapter_only = CapabilityEvidence(
            rules_verified=True,
            simulation_passed=True,
            real_adapter_verified=True,
        )
        for evidence in (no_adapter, adapter_only):
            with self.subTest(evidence=evidence):
                self.assertIs(GameCapability("burger-day", evidence).state,
                              CapabilityState.SIMULATION_ONLY)

    def test_execution_readiness_requires_all_evidence(self):
        evidence = CapabilityEvidence(
            rules_verified=True,
            simulation_passed=True,
            no_deadlock_passed=True,
            real_adapter_verified=True,
        )
        capability = GameCapability("starlight-mix", evidence)
        self.assertIs(capability.state, CapabilityState.EXECUTION_READY)
        self.assertTrue(capability.execution_ready)
        self.assertEqual(evidence.blockers, ())

    def test_invalid_evidence_order_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "规则未核实"):
            CapabilityEvidence(simulation_passed=True)
        with self.assertRaisesRegex(ValueError, "模拟未通过"):
            CapabilityEvidence(rules_verified=True, no_deadlock_passed=True)
        with self.assertRaisesRegex(ValueError, "模拟未通过"):
            CapabilityEvidence(rules_verified=True, real_adapter_verified=True)

    def test_evidence_flags_require_actual_booleans(self):
        with self.assertRaisesRegex(TypeError, "布尔证据"):
            CapabilityEvidence(rules_verified=1)

    def test_out_of_scope_game_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            GameCapability("other-game")

    def test_evidence_object_must_be_explicit(self):
        with self.assertRaisesRegex(TypeError, "CapabilityEvidence"):
            GameCapability("animal-bath", evidence=None)


if __name__ == "__main__":
    unittest.main()
