import json
import unittest
from datetime import datetime, timedelta, timezone

from app.observation import Observation, ObservedValue


class ObservationContractTests(unittest.TestCase):
    def make_observation(self, **overrides):
        fields = {
            "device_id": ObservedValue.observed("mumu-instance-1"),
            "character_id": ObservedValue.unknown("identity_not_read"),
            "activity_id": ObservedValue.unknown("activity_not_open"),
            "rules_version": ObservedValue.unknown("rules_not_verified"),
            "frame_id": ObservedValue.observed("frame-001"),
            "page_id": ObservedValue.unknown("page_not_classified"),
            "board": ObservedValue.unknown("board_not_visible"),
            "energy": ObservedValue.observed(0),
        }
        fields.update(overrides)
        return Observation(
            observed_at=datetime(2026, 11, 16, 20, 0, tzinfo=timezone(timedelta(hours=8))),
            **fields,
        )

    def test_zero_is_known_and_unknown_reason_survives_json_round_trip(self):
        observation = self.make_observation()
        payload = json.loads(json.dumps(observation.to_dict(), ensure_ascii=False))
        restored = Observation.from_dict(payload)
        self.assertEqual(restored.energy, ObservedValue.observed(0))
        self.assertEqual(restored.character_id, ObservedValue.unknown("identity_not_read"))
        self.assertEqual(restored.unknown_fields,
                         ("character_id", "activity_id", "rules_version", "page_id", "board"))

    def test_unknown_energy_is_not_serialized_as_zero(self):
        observation = self.make_observation(energy=ObservedValue.unknown("energy_not_read"))
        payload = observation.to_dict()
        self.assertEqual(payload["energy"], {"known": False, "reason": "energy_not_read"})
        self.assertIn("energy", payload["unknown_fields"])

    def test_board_is_a_deep_immutable_snapshot(self):
        source = {"tiles": [[{"kind": "candy"}]]}
        observation = self.make_observation(board=ObservedValue.observed(source))
        source["tiles"][0][0]["kind"] = "changed"
        source["tiles"].append([])

        board = observation.board.value
        self.assertEqual(board["tiles"][0][0]["kind"], "candy")
        with self.assertRaises(TypeError):
            board["kind"] = "changed"
        with self.assertRaises(TypeError):
            board["tiles"][0][0]["kind"] = "changed"
        self.assertEqual(
            observation.to_dict()["board"]["value"],
            {"tiles": [[{"kind": "candy"}]]},
        )

    def test_board_rejects_values_that_are_not_safe_json(self):
        for value in ({1: "not a text key"}, {"bad": float("nan")}, object()):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.make_observation(board=ObservedValue.observed(value))

    def test_all_fields_must_be_explicit(self):
        with self.assertRaises(TypeError):
            Observation(observed_at=datetime.now(timezone.utc))

    def test_naive_timestamp_is_rejected(self):
        fields = self.make_observation().__dict__.copy()
        fields["observed_at"] = datetime(2026, 11, 16, 20, 0)
        with self.assertRaisesRegex(ValueError, "时区"):
            Observation(**fields)

    def test_known_identity_must_be_nonempty_text(self):
        with self.assertRaisesRegex(ValueError, "device_id"):
            self.make_observation(device_id=ObservedValue.observed(" "))

    def test_energy_requires_nonnegative_integer_and_accepts_zero(self):
        for value in (True, -1, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "非负整数"):
                    self.make_observation(energy=ObservedValue.observed(value))

    def test_observed_value_rejects_ambiguous_unknowns(self):
        with self.assertRaisesRegex(ValueError, "unknown必须"):
            ObservedValue.unknown("")
        with self.assertRaisesRegex(ValueError, "已观测值"):
            ObservedValue(is_known=True, value=None)

    def test_serialized_unknown_index_must_match_fields(self):
        payload = self.make_observation().to_dict()
        payload["unknown_fields"] = []
        with self.assertRaisesRegex(ValueError, "不一致"):
            Observation.from_dict(payload)

    def test_boolean_schema_version_is_rejected(self):
        payload = self.make_observation().to_dict()
        payload["schema_version"] = True
        with self.assertRaisesRegex(ValueError, "结构或版本"):
            Observation.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
