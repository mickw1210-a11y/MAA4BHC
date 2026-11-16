import copy
import unittest
from typing import get_type_hints

from app.minigames.simulation_state import SimulationState
from app.minigames.simulation_trace import SimulationTrace
from app.minigames.strategy_observation import StrategyObservation
from app.observation import ObservedValue
from app.strategy_contract import Strategy


class StrategyObservationTests(unittest.TestCase):
    def make_observation(self, fields=None):
        return StrategyObservation(
            game_id="candy-party",
            rules_version="fixture-v1",
            observation_schema="test-observation.v1",
            visible_fields=fields or {},
        )

    def test_strategy_protocol_accepts_only_the_observation_projection(self):
        hints = get_type_hints(Strategy.choose_action)
        self.assertIs(hints["state"], StrategyObservation)

    def test_projection_does_not_expose_full_state_trace_or_random_input_fields(self):
        view = self.make_observation({"board": ObservedValue.observed([[1, 2]])})
        for forbidden in (
            "state_data", "random_input", "future_random", "trace", "hidden_state",
        ):
            self.assertFalse(hasattr(view, forbidden))
        self.assertFalse(issubclass(StrategyObservation, SimulationState))
        self.assertFalse(issubclass(StrategyObservation, SimulationTrace))

    def test_visible_values_are_deeply_frozen_and_detached_from_input(self):
        source = {"tiles": [["red", "blue"]]}
        view = self.make_observation({"board": ObservedValue.observed(source)})
        source["tiles"][0][0] = "changed"
        self.assertEqual(view.visible_fields["board"].value["tiles"][0][0], "red")
        with self.assertRaises(TypeError):
            view.visible_fields["board"].value["tiles"][0][0] = "changed"

    def test_unknown_visible_fields_remain_unknown_in_round_trip(self):
        view = self.make_observation({
            "board": ObservedValue.unknown("screen not fully observed"),
            "energy": ObservedValue.observed(0),
        })
        restored = StrategyObservation.from_dict(view.to_dict())
        self.assertFalse(restored.visible_fields["board"].is_known)
        self.assertEqual(restored.visible_fields["board"].reason, "screen not fully observed")
        self.assertTrue(restored.visible_fields["energy"].is_known)
        self.assertEqual(restored.visible_fields["energy"].value, 0)

    def test_rejects_untyped_fields_and_non_json_values(self):
        with self.assertRaisesRegex(TypeError, "ObservedValue"):
            self.make_observation({"board": [[1, 2]]})
        with self.assertRaisesRegex(ValueError, "JSON数据"):
            self.make_observation({"board": ObservedValue.observed(object())})
        with self.assertRaisesRegex(ValueError, "非有限数字"):
            self.make_observation({"board": ObservedValue.observed(float("nan"))})

    def test_rejects_unknown_schema_version_and_extra_serialized_fields(self):
        data = self.make_observation().to_dict()
        wrong_version = copy.deepcopy(data)
        wrong_version["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "结构或版本"):
            StrategyObservation.from_dict(wrong_version)
        extra_field = copy.deepcopy(data)
        extra_field["future_draws"] = [1]
        with self.assertRaisesRegex(ValueError, "结构或版本"):
            StrategyObservation.from_dict(extra_field)

    def test_rejects_unknown_game_and_invalid_visible_field_name(self):
        with self.assertRaisesRegex(ValueError, "不支持此小游戏ID"):
            StrategyObservation("other-game", "fixture-v1", "view.v1", {})
        with self.assertRaisesRegex(ValueError, "非空文本"):
            self.make_observation({" ": ObservedValue.observed(1)})


if __name__ == "__main__":
    unittest.main()
