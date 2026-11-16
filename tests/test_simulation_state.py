import json
import unittest
from datetime import datetime, timezone

from app.minigames.simulation_state import SimulationRandomInput, SimulationState
from app.observation import Observation, ObservedValue
from app.strategy_contract import LogicalAction


class SimulationStateTests(unittest.TestCase):
    def make_state(self, state_data=None, rules_version="fixture-rules-v1"):
        return SimulationState(
            game_id="candy-party",
            rules_version=rules_version,
            state_schema="test-fixture.v1",
            state_data=state_data if state_data is not None else {"counter": 0, "items": []},
        )

    def test_state_round_trip_is_canonical_and_does_not_alias_input(self):
        source = {"counter": 0, "nested": {"values": [1, 2]}}
        state = self.make_state(source)
        source["nested"]["values"].append(3)
        restored = SimulationState.from_dict(state.to_dict())
        self.assertEqual(state, restored)
        self.assertEqual(state.fingerprint, restored.fingerprint)
        self.assertEqual(json.loads(state.canonical_json), state.to_dict())
        self.assertEqual(list(state.state_data["nested"]["values"]), [1, 2])

    def test_trial_copy_is_detached_and_strategy_payload_cannot_mutate_observation(self):
        observation = Observation(
            observed_at=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc),
            device_id=ObservedValue.observed("fixture-device"),
            character_id=ObservedValue.unknown("not_read"),
            activity_id=ObservedValue.unknown("not_read"),
            rules_version=ObservedValue.unknown("not_verified"),
            frame_id=ObservedValue.observed("frame-1"),
            page_id=ObservedValue.observed("page-1"),
            board=ObservedValue.observed({"slots": [[1, None], [2, 3]]}),
            energy=ObservedValue.unknown("not_read"),
        )
        original_observation = observation.to_dict()
        state = self.make_state({"observation": original_observation})
        trial = state.copy_for_trial()

        self.assertIsNot(trial, state)
        self.assertIsNot(trial.state_data, state.state_data)
        self.assertIsNot(trial.state_data["observation"], state.state_data["observation"])
        self.assertEqual(trial.fingerprint, state.fingerprint)
        with self.assertRaises(TypeError):
            trial.state_data["observation"]["page_id"] = {"known": True, "value": "changed"}

        strategy_payload = trial.to_dict()["state_data"]
        strategy_payload["observation"]["board"]["value"]["slots"][0][0] = "trial-only"
        self.assertEqual(observation.to_dict(), original_observation)
        self.assertEqual(state.to_dict()["state_data"]["observation"], original_observation)
        self.assertEqual(trial.to_dict()["state_data"]["observation"], original_observation)

    def test_unknown_rule_version_cannot_be_simulated(self):
        for version in ("unknown", "unverified", "未知", " "):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.make_state(rules_version=version)

    def test_state_rejects_unknown_games_schema_and_non_json_values(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            SimulationState("other-game", "v1", "fixture.v1", {})
        with self.assertRaisesRegex(ValueError, "state_schema"):
            SimulationState("candy-party", "v1", "Upper Schema", {})
        with self.assertRaisesRegex(ValueError, "非有限"):
            self.make_state({"value": float("nan")})
        with self.assertRaisesRegex(ValueError, "JSON值"):
            self.make_state({"value": object()})

    def test_state_deserialization_rejects_schema_drift_and_bad_version_type(self):
        record = self.make_state().to_dict()
        extra = {**record, "hidden_future": [1]}
        with self.assertRaisesRegex(ValueError, "结构或版本"):
            SimulationState.from_dict(extra)
        with self.assertRaisesRegex(ValueError, "结构或版本"):
            SimulationState.from_dict({**record, "schema_version": True})

    def test_random_input_is_deterministic_and_scoped_to_one_step(self):
        first = SimulationRandomInput.for_step(seed=1234, step_index=7, draw_count=3)
        repeat = SimulationRandomInput.for_step(seed=1234, step_index=7, draw_count=3)
        other_seed = SimulationRandomInput.for_step(seed=1235, step_index=7, draw_count=3)
        other_step = SimulationRandomInput.for_step(seed=1234, step_index=8, draw_count=3)
        self.assertEqual(first.draws, repeat.draws)
        self.assertNotEqual(first.draws, other_seed.draws)
        self.assertNotEqual(first.draws, other_step.draws)
        with self.assertRaisesRegex(IndexError, "已耗尽"):
            first.draw(3)

    def test_random_input_round_trip_checks_seed_step_and_algorithm(self):
        random_input = SimulationRandomInput.for_step(seed=99, step_index=2, draw_count=2)
        restored = SimulationRandomInput.from_dict(random_input.to_dict())
        self.assertEqual(random_input, restored)
        tampered = {**random_input.to_dict(), "draws": [0, 0]}
        with self.assertRaisesRegex(ValueError, "不一致"):
            SimulationRandomInput.from_dict(tampered)
        with self.assertRaisesRegex(ValueError, "算法版本"):
            SimulationRandomInput(1, 0, (), algorithm="unknown")
        with self.assertRaisesRegex(ValueError, "不一致"):
            SimulationRandomInput(1, 0, (0,))

    def test_same_seed_state_and_action_reproduce_virtual_transition(self):
        state = self.make_state({"moves": []})
        action = LogicalAction("select", "slot:2")

        def fixture_transition(current, logical_action, random_input):
            payload = current.to_dict()["state_data"]
            payload["moves"].append({
                "kind": logical_action.kind,
                "target": logical_action.target,
                "draw": random_input.draw(0),
            })
            return SimulationState(
                game_id=current.game_id,
                rules_version=current.rules_version,
                state_schema=current.state_schema,
                state_data=payload,
            )

        first = fixture_transition(
            state, action, SimulationRandomInput.for_step(42, 0, 1),
        )
        repeat = fixture_transition(
            state, action, SimulationRandomInput.for_step(42, 0, 1),
        )
        other_seed = fixture_transition(
            state, action, SimulationRandomInput.for_step(43, 0, 1),
        )
        self.assertEqual(first, repeat)
        self.assertNotEqual(first, other_seed)

    def test_random_input_rejects_bool_and_out_of_range_counters(self):
        for seed in (True, -1, 1 << 64):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                SimulationRandomInput.for_step(seed, 0, 0)
        with self.assertRaisesRegex(ValueError, "非负整数"):
            SimulationRandomInput.for_step(1, 0, True)


if __name__ == "__main__":
    unittest.main()
