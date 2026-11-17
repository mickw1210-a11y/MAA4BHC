import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.action_result import ActionOutcome, ActionResult
from app.config import ROOT
from app.device_identity import DeviceInstanceIdentity
from app.device_lease import LeaseOwnerInfo, ProcessLiveness
from app.device_recovery import (
    RecoveryAssessment,
    RecoveryAuthorityConfig,
    RecoveryDisposition,
    RecoveryError,
    RecoveryObservation,
    RecoveryStore,
)


class DeviceRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / ".cache" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temporary.name)
        self.project_a = self.root / "copy-a"
        self.project_b = self.root / "copy-b"
        self.project_a.mkdir()
        self.project_b.mkdir()
        self.identity = DeviceInstanceIdentity("synthetic", "offline-recovery")
        self.config, self.store_a = RecoveryStore.provision(
            self.project_a,
            self.project_a / "runtime" / "device-recovery",
            self.identity,
        )
        self.owner_a = self.owner(3101, 7101)
        self.owner_b = self.owner(3102, 7102)

    def tearDown(self):
        self.temporary.cleanup()

    def owner(self, process_id, created):
        return LeaseOwnerInfo(
            process_id=process_id,
            thread_id=process_id + 1,
            process_created_filetime=created,
            acquired_at="2026-11-17T00:00:00+00:00",
            identity_digest=self.identity.lease_key,
        )

    def copy_b_store(self):
        store = RecoveryStore.open(self.config, self.identity)
        self.assertTrue(store.directory.is_relative_to(self.project_a.resolve()))
        self.assertNotEqual(store.directory, self.project_b)
        return store

    def begin_first_use(self, store=None, owner=None):
        store = store or self.store_a
        owner = owner or self.owner_a
        result = store.begin_lease(owner)
        self.assertIs(result.disposition, RecoveryDisposition.FIRST_USE)
        return result

    def prepare_action(self, store=None, owner=None, action_id="action-1", plan_id="plan-1"):
        store = store or self.store_a
        owner = owner or self.owner_a
        store.prepare_action(
            owner,
            action_id=action_id,
            plan_id=plan_id,
            precondition_observation_id="observation-before",
            payload_sha256=hashlib.sha256(b"synthetic command").hexdigest(),
        )

    def test_first_use_requires_explicit_provisioning_and_records_no_project_paths(self):
        self.begin_first_use()
        state = json.loads(self.store_a.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["authority_id"], self.config.authority_id)
        self.assertEqual(state["events"][0]["data"]["predecessor_status"], "first_use")
        self.assertNotIn(str(self.project_a), self.store_a.state_path.read_text(encoding="utf-8"))
        self.assertNotIn("127.0.0.1", self.store_a.state_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(RecoveryError, "不得覆盖"):
            RecoveryStore.provision(
                self.project_a,
                self.project_a / "runtime" / "device-recovery",
                self.identity,
            )

    def test_configured_b_copy_discovers_a_authority_and_normal_release(self):
        self.begin_first_use()
        self.store_a.release_lease(self.owner_a)
        store_b = self.copy_b_store()
        assessment = store_b.begin_lease(self.owner_b)
        self.assertIs(assessment.disposition, RecoveryDisposition.READY)
        self.assertEqual(
            [event["kind"] for event in store_b.read_events()],
            ["lease_started", "lease_released", "lease_started"],
        )

    def test_active_or_unknown_previous_owner_blocks_new_lease_record(self):
        self.begin_first_use()
        for liveness, expected in (
            (ProcessLiveness.ALIVE, RecoveryDisposition.OWNER_ACTIVE),
            (ProcessLiveness.UNKNOWN, RecoveryDisposition.OWNER_UNKNOWN),
        ):
            store_b = self.copy_b_store()
            assessment = store_b.begin_lease(
                self.owner_b,
                liveness_check=lambda owner, value=liveness: value,
            )
            self.assertIsInstance(assessment, RecoveryAssessment)
            self.assertIs(assessment.disposition, expected)
            self.assertEqual(len(store_b.read_events()), 1)

    def test_pid_reuse_counts_as_prior_process_exit(self):
        self.begin_first_use()
        store_b = self.copy_b_store()
        assessment = store_b.begin_lease(
            self.owner_b,
            liveness_check=lambda owner: ProcessLiveness.PID_REUSED,
        )
        self.assertIs(assessment.disposition, RecoveryDisposition.READY)
        self.assertIs(assessment.previous_owner_liveness, ProcessLiveness.PID_REUSED)

    def test_intent_write_failure_and_submission_marker_failure_never_call_sender(self):
        self.begin_first_use()
        sends = []

        def submit(action_id, plan_id):
            self.store_a.prepare_action(
                self.owner_a,
                action_id=action_id,
                plan_id=plan_id,
                precondition_observation_id="observation-before",
                payload_sha256=hashlib.sha256(b"synthetic command").hexdigest(),
            )
            self.store_a.mark_submission_possible(self.owner_a, action_id)
            sends.append(action_id)

        with patch.object(self.store_a, "_write_state", side_effect=OSError("simulated intent write failure")):
            with self.assertRaisesRegex(RecoveryError, "禁止发送"):
                submit("action-fail", "plan-fail")
        self.assertEqual(sends, [])
        self.prepare_action(action_id="action-marker", plan_id="plan-marker")
        with patch.object(self.store_a, "_write_state", side_effect=OSError("simulated marker failure")):
            with self.assertRaisesRegex(RecoveryError, "禁止发送"):
                self.store_a.mark_submission_possible(self.owner_a, "action-marker")
                sends.append("action-marker")
        self.assertEqual(sends, [])
        self.assertIs(
            self.store_a.assess_current(self.owner_a).disposition,
            RecoveryDisposition.REPLAN_REQUIRED,
        )

    def test_crash_after_prepared_intent_is_closed_as_not_submitted_without_replay(self):
        self.begin_first_use()
        self.prepare_action()
        store_b = self.copy_b_store()
        assessment = store_b.begin_lease(
            self.owner_b,
            liveness_check=lambda owner: ProcessLiveness.EXITED,
        )
        self.assertIs(assessment.disposition, RecoveryDisposition.REPLAN_REQUIRED)
        self.assertIs(assessment.action_result.outcome, ActionOutcome.NOT_SUBMITTED)
        self.assertIs(
            store_b.assess_current(self.owner_b).disposition,
            RecoveryDisposition.REPLAN_REQUIRED,
        )
        self.assertEqual(
            [event["kind"] for event in store_b.read_events()].count("action_result"),
            1,
        )
        with self.assertRaisesRegex(RecoveryError, "原动作不得重放"):
            store_b.prepare_action(
                self.owner_b,
                action_id="action-1",
                plan_id="plan-2",
                precondition_observation_id="observation-fresh",
                payload_sha256=hashlib.sha256(b"synthetic command").hexdigest(),
            )

    def test_crash_after_submission_boundary_is_unknown_and_never_replayed(self):
        self.begin_first_use()
        self.prepare_action()
        self.store_a.mark_submission_possible(self.owner_a, "action-1")
        simulated_sends = []

        def simulated_sender():
            simulated_sends.append("action-1")

        simulated_sender()
        store_b = self.copy_b_store()
        assessment = store_b.begin_lease(
            self.owner_b,
            liveness_check=lambda owner: ProcessLiveness.EXITED,
        )
        self.assertIs(assessment.disposition, RecoveryDisposition.VERIFY_REQUIRED)
        self.assertIs(assessment.action_result.outcome, ActionOutcome.SUBMITTED_UNKNOWN)
        self.assertIn("禁止重放", assessment.action_result.reason)
        first_snapshot = store_b.read_events()
        again = store_b.assess_current(self.owner_b)
        self.assertIs(again.disposition, RecoveryDisposition.VERIFY_REQUIRED)
        self.assertEqual(store_b.read_events(), first_snapshot)
        self.assertEqual(simulated_sends, ["action-1"])
        with self.assertRaisesRegex(RecoveryError, "不能改记为未提交"):
            store_b.record_result(
                self.owner_b,
                ActionResult(
                    "action-1",
                    ActionOutcome.NOT_SUBMITTED,
                    reason="不允许抹掉已可能提交的边界",
                ),
            )
        self.assertIs(
            store_b.assess_current(self.owner_b).action_result.outcome,
            ActionOutcome.SUBMITTED_UNKNOWN,
        )
        with self.assertRaisesRegex(RecoveryError, "未决动作"):
            store_b.prepare_action(
                self.owner_b,
                action_id="action-2",
                plan_id="plan-2",
                precondition_observation_id="observation-fresh",
                payload_sha256=hashlib.sha256(b"next command").hexdigest(),
            )

    def test_only_matching_fresh_observation_can_resolve_unknown_action(self):
        self.begin_first_use()
        self.prepare_action()
        self.store_a.mark_submission_possible(self.owner_a, "action-1")
        store_b = self.copy_b_store()
        store_b.begin_lease(
            self.owner_b,
            liveness_check=lambda owner: ProcessLiveness.EXITED,
        )
        submission_time = next(
            event["at"] for event in store_b.read_events()
            if event["kind"] == "submission_possible"
        )
        stale = RecoveryObservation(
            "action-1",
            self.identity.lease_key,
            "observation-after",
            "2020-01-01T00:00:00+00:00",
            ActionOutcome.VERIFIED_SUCCESS,
            "synthetic-observation:stale",
        )
        result = ActionResult(
            "action-1",
            ActionOutcome.VERIFIED_SUCCESS,
            verification_observation_id="observation-after",
        )
        with self.assertRaisesRegex(RecoveryError, "晚于"):
            store_b.record_result(self.owner_b, result, observation=stale)

        mismatched = RecoveryObservation(
            "action-1",
            "0" * 64,
            "observation-after",
            "2099-01-01T00:00:00+00:00",
            ActionOutcome.VERIFIED_SUCCESS,
            "synthetic-observation:mismatch",
        )
        with self.assertRaisesRegex(RecoveryError, "不匹配"):
            store_b.record_result(self.owner_b, result, observation=mismatched)

        fresh = RecoveryObservation(
            "action-1",
            self.identity.lease_key,
            "observation-after",
            datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            ActionOutcome.VERIFIED_SUCCESS,
            "synthetic-observation:verified",
        )
        store_b.record_result(self.owner_b, result, observation=fresh)
        assessment = store_b.assess_current(self.owner_b)
        self.assertIs(assessment.disposition, RecoveryDisposition.READY)
        self.assertEqual(assessment.action_result.verification_observation_id, "observation-after")
        self.assertEqual(assessment.evidence_ref, "synthetic-observation:verified")
        result_event = [event for event in store_b.read_events() if event["kind"] == "action_result"][-1]
        self.assertEqual(result_event["data"]["evidence_ref"], "synthetic-observation:verified")
        self.assertEqual(result_event["data"]["observation"]["identity_digest"], self.identity.lease_key)
        self.assertGreater(
            RecoveryObservation.from_dict(result_event["data"]["observation"]).observed_at,
            submission_time,
        )
        store_b.release_lease(self.owner_b)

    def test_missing_corrupt_wrong_identity_and_wrong_authority_fail_closed(self):
        state_path = self.store_a.state_path
        state_path.unlink()
        with self.assertRaisesRegex(RecoveryError, "不能按首次使用"):
            RecoveryStore.open(self.config, self.identity)

        replacement_config, replacement = RecoveryStore.provision(
            self.project_a,
            self.project_a / "runtime" / "replacement-authority",
            self.identity,
        )
        wrong_config = RecoveryAuthorityConfig(
            replacement_config.authority_project_root,
            replacement_config.authority_root,
            "0" * 32,
        )
        with self.assertRaisesRegex(RecoveryError, "不匹配"):
            RecoveryStore.open(wrong_config, self.identity)

        replacement.state_path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(RecoveryError, "损坏"):
            RecoveryStore.open(replacement_config, self.identity)

        unused_identity = DeviceInstanceIdentity("synthetic", "different-device")
        with self.assertRaisesRegex(RecoveryError, "缺失|不匹配"):
            RecoveryStore.open(replacement_config, unused_identity)

    def test_authority_path_must_stay_inside_the_designated_project(self):
        with self.assertRaisesRegex(RecoveryError, "项目目录内"):
            RecoveryStore.provision(self.project_a, ROOT.parent, self.identity)

    def test_hash_chain_corruption_is_detected(self):
        self.begin_first_use()
        state = json.loads(self.store_a.state_path.read_text(encoding="utf-8"))
        state["events"][0]["data"]["predecessor_status"] = "released"
        self.store_a.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(RecoveryError, "校验失败|链断裂"):
            RecoveryStore.open(self.config, self.identity)


if __name__ == "__main__":
    unittest.main()
