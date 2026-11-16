import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.action_contract import ActionIntent, FrameFingerprint
from app.conflict_guard import DeviceConflictError, check_pre_dispatch
from app.device_identity import DeviceInstanceIdentity
from app.device_lease import DeviceLeaseState
from app.external_operator_probe import OperatorProbeReport, OperatorProbeState
from app.observation import Observation, ObservedValue


class PreDispatchConflictGuardTests(unittest.TestCase):
    now = datetime(2026, 11, 16, 12, 0, 1, tzinfo=timezone.utc)

    def identity(self):
        return DeviceInstanceIdentity("mumu12", "index=0;created_timestamp=1721180910349678")

    def observation(self, *, device_id=None, frame_id="frame-001", page_id="game-board", observed_at=None):
        return Observation(
            observed_at=observed_at or self.now,
            device_id=ObservedValue.observed(device_id or self.identity().canonical),
            character_id=ObservedValue.unknown("not_read"),
            activity_id=ObservedValue.unknown("not_read"),
            rules_version=ObservedValue.unknown("not_verified"),
            frame_id=ObservedValue.observed(frame_id),
            page_id=ObservedValue.observed(page_id),
            board=ObservedValue.unknown("not_read"),
            energy=ObservedValue.unknown("not_read"),
        )

    def action(self, observation=None):
        observation = observation or self.observation()
        return ActionIntent(
            action_id="action-1",
            task_id="task-1",
            kind="tap",
            target="logical:confirm",
            expected_cost=ObservedValue.unknown("not_verified"),
            expected_postcondition="next-page",
            precondition=FrameFingerprint.from_observation(observation),
        )

    def clear_report(self, *, sampled_at=None):
        return OperatorProbeReport(
            state=OperatorProbeState.CLEAR,
            observed_adb_client_pids=(),
            external_adb_client_pids=(),
            sampled_at=(sampled_at or self.now - timedelta(milliseconds=100)).isoformat(),
        )

    def check(self, **overrides):
        observation = overrides.pop("observation", self.observation())
        action = overrides.pop("action", self.action(observation))
        values = {
            "lease_state": DeviceLeaseState.ACQUIRED,
            "lease_identity": self.identity(),
            "operator_report": self.clear_report(),
            "now": self.now,
            "max_snapshot_age_seconds": 1.0,
        }
        values.update(overrides)
        return check_pre_dispatch(action, observation, **values)

    def test_known_signals_and_exact_current_frame_return_limited_permit(self):
        permit = self.check()
        self.assertEqual(permit.fingerprint.device_id, self.identity().canonical)
        self.assertEqual(permit.coverage, "adb-server-default-port-snapshot")
        self.assertFalse(permit.exclusive_control_confirmed)
        permit.assert_fresh(now=self.now)

    def test_lease_conflict_abandoned_or_unknown_blocks(self):
        for state in (DeviceLeaseState.CONFLICT, DeviceLeaseState.ABANDONED, None):
            with self.subTest(state=state), self.assertRaisesRegex(DeviceConflictError, "租约"):
                self.check(lease_state=state)

    def test_adb_conflict_or_unknown_blocks(self):
        conflict = OperatorProbeReport(
            OperatorProbeState.CONFLICT, (4321,), (4321,), self.clear_report().sampled_at,
        )
        unknown = replace(self.clear_report(), state=OperatorProbeState.UNKNOWN, reason="scan_failed")
        for report in (conflict, unknown):
            with self.subTest(state=report.state), self.assertRaises(DeviceConflictError):
                self.check(operator_report=report)

    def test_stale_or_future_snapshot_blocks(self):
        for sample_time in (self.now - timedelta(seconds=2), self.now + timedelta(seconds=1)):
            report = self.clear_report(sampled_at=sample_time)
            with self.subTest(sample_time=sample_time), self.assertRaisesRegex(DeviceConflictError, "过期"):
                self.check(operator_report=report)

    def test_frame_must_be_captured_after_operator_snapshot(self):
        report = self.clear_report(sampled_at=self.now)
        older = self.observation(observed_at=self.now - timedelta(milliseconds=1))
        with self.assertRaisesRegex(DeviceConflictError, "早于冲突检查"):
            self.check(observation=older, action=self.action(older), operator_report=report)

    def test_action_from_old_frame_or_page_is_rejected(self):
        original = self.observation()
        action = self.action(original)
        report = self.clear_report(sampled_at=self.now - timedelta(milliseconds=200))
        changed_frame = self.observation(frame_id="frame-002", observed_at=self.now)
        with self.assertRaisesRegex(DeviceConflictError, "画面已变化") as frame_error:
            self.check(observation=changed_frame, action=action, operator_report=report)
        self.assertEqual(frame_error.exception.code, "frame_id_changed")

        changed_page = self.observation(page_id="login-dialog", observed_at=self.now)
        with self.assertRaisesRegex(DeviceConflictError, "页面") as page_error:
            self.check(observation=changed_page, action=action, operator_report=report)
        self.assertEqual(page_error.exception.code, "page_id_changed")

    def test_action_identity_must_match_acquired_lease(self):
        observation = self.observation(device_id="another-instance")
        with self.assertRaisesRegex(DeviceConflictError, "租约身份"):
            self.check(observation=observation, action=self.action(observation))

    def test_inconsistent_clear_report_is_unknown(self):
        report = OperatorProbeReport(
            OperatorProbeState.CLEAR, (4321,), (4321,), self.clear_report().sampled_at,
        )
        with self.assertRaises(DeviceConflictError):
            self.check(operator_report=report)

    def test_permit_expires_after_short_window(self):
        permit = self.check()
        with self.assertRaisesRegex(DeviceConflictError, "已过期"):
            permit.assert_fresh(now=permit.expires_at + timedelta(microseconds=1))


if __name__ == "__main__":
    unittest.main()
