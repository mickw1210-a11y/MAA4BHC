import unittest
from datetime import datetime, timezone

from app.action_contract import (
    ActionIntent,
    ActionPreconditionError,
    FrameFingerprint,
    assert_action_precondition,
)
from app.observation import Observation, ObservedValue


class ActionFramePreconditionTests(unittest.TestCase):
    def make_observation(self, **overrides):
        fields = {
            "device_id": ObservedValue.observed("mumu-instance-1"),
            "character_id": ObservedValue.unknown("identity_not_read"),
            "activity_id": ObservedValue.unknown("activity_not_open"),
            "rules_version": ObservedValue.unknown("rules_not_verified"),
            "frame_id": ObservedValue.observed("capture-001"),
            "page_id": ObservedValue.observed("minigame-board"),
            "board": ObservedValue.unknown("board_not_read"),
            "energy": ObservedValue.unknown("energy_not_read"),
        }
        fields.update(overrides)
        return Observation(observed_at=datetime(2026, 11, 16, tzinfo=timezone.utc), **fields)

    def make_action(self, observation=None):
        observation = observation or self.make_observation()
        return ActionIntent(
            action_id="action-001",
            task_id="task-001",
            kind="select",
            target="slot:2",
            expected_cost=ObservedValue.unknown("cost_not_verified"),
            expected_postcondition="slot-2-selected",
            precondition=FrameFingerprint.from_observation(observation),
        )

    def test_matching_observation_accepts_action_precondition(self):
        observation = self.make_observation()
        self.assertIsNone(assert_action_precondition(self.make_action(observation), observation))

    def test_new_capture_invalidates_action_even_on_same_page(self):
        action = self.make_action()
        current = self.make_observation(frame_id=ObservedValue.observed("capture-002"))
        with self.assertRaisesRegex(ActionPreconditionError, "画面已变化") as raised:
            assert_action_precondition(action, current)
        self.assertEqual(raised.exception.code, "frame_id_changed")

    def test_page_change_invalidates_action_even_with_same_frame_id(self):
        action = self.make_action()
        current = self.make_observation(page_id=ObservedValue.observed("login-dialog"))
        with self.assertRaisesRegex(ActionPreconditionError, "页面") as raised:
            assert_action_precondition(action, current)
        self.assertEqual(raised.exception.code, "page_id_changed")

    def test_instance_change_invalidates_action(self):
        action = self.make_action()
        current = self.make_observation(device_id=ObservedValue.observed("mumu-instance-2"))
        with self.assertRaisesRegex(ActionPreconditionError, "实例") as raised:
            assert_action_precondition(action, current)
        self.assertEqual(raised.exception.code, "device_id_changed")

    def test_unknown_fingerprint_field_rejects_action(self):
        action = self.make_action()
        for field in ("device_id", "frame_id", "page_id"):
            with self.subTest(field=field):
                current = self.make_observation(**{
                    field: ObservedValue.unknown(f"{field}_not_confirmed")
                })
                with self.assertRaises(ActionPreconditionError) as raised:
                    assert_action_precondition(action, current)
                self.assertEqual(raised.exception.code, f"{field}_unknown")

    def test_invalid_observation_is_rejected(self):
        with self.assertRaisesRegex(ActionPreconditionError, "观察数据无效"):
            FrameFingerprint.from_observation(None)

    def test_action_fields_and_unknown_cost_are_explicit(self):
        action = self.make_action()
        self.assertEqual(action.expected_cost, ObservedValue.unknown("cost_not_verified"))
        with self.assertRaisesRegex(ValueError, "target"):
            ActionIntent(
                action_id="action-001",
                task_id="task-001",
                kind="select",
                target=" ",
                expected_cost=ObservedValue.unknown("cost_not_verified"),
                expected_postcondition="slot-2-selected",
                precondition=action.precondition,
            )

    def test_frame_fingerprint_rejects_blank_ids(self):
        with self.assertRaisesRegex(ValueError, "frame_id"):
            FrameFingerprint("mumu-instance-1", " ", "minigame-board")


if __name__ == "__main__":
    unittest.main()
