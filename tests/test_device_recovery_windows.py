"""Target-Windows, two-process recovery checks using synthetic identities only."""

import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from app.config import ROOT
from app.device_identity import DeviceInstanceIdentity
from app.device_lease import DeviceLeaseState, WindowsInstanceLease
from app.device_recovery import (
    RecoveryDisposition,
    RecoveryStore,
)


def _lease_holder_worker(identity, project_root, config, phase, connection, release_event):
    lease = WindowsInstanceLease(identity, project_root=project_root, startup_timeout=5)
    try:
        state = lease.acquire()
        if state is not DeviceLeaseState.ACQUIRED:
            connection.send({"error": f"lease state: {state.value}"})
            return
        store = RecoveryStore.open(config, identity)
        owner = lease.owner_info
        assessment = store.begin_lease(owner)
        connection.send({
            "state": state.value,
            "disposition": assessment.disposition.value,
            "owner_pid": owner.process_id,
            "owner_created": owner.process_created_filetime,
        })

        if phase == "hold":
            if not release_event.wait(20):
                os._exit(71)
            store.release_lease(owner)
            lease.close()
            connection.send({"released": True})
            return

        if phase == "prepared":
            store.prepare_action(
                owner,
                action_id="synthetic-action-prepared",
                plan_id="synthetic-plan-prepared",
                precondition_observation_id="synthetic-observation-before",
                payload_sha256="1" * 64,
            )
            connection.send({"prepared": True})
            os._exit(23)

        if phase == "submitted":
            store.prepare_action(
                owner,
                action_id="synthetic-action-submitted",
                plan_id="synthetic-plan-submitted",
                precondition_observation_id="synthetic-observation-before",
                payload_sha256="2" * 64,
            )
            store.mark_submission_possible(owner, "synthetic-action-submitted")
            send_count_path = Path(project_root) / "simulated-send-count.txt"
            with send_count_path.open("x", encoding="ascii") as stream:
                stream.write("1")
                stream.flush()
                os.fsync(stream.fileno())
            connection.send({"submitted_once": True})
            os._exit(23)
        connection.send({"error": "unknown worker phase"})
    except BaseException as error:
        try:
            connection.send({"error": f"{type(error).__name__}: {error}"})
        except (BrokenPipeError, OSError):
            pass
        raise
    finally:
        connection.close()


@unittest.skipUnless(os.name == "nt", "Windows-only named-mutex recovery integration")
class DeviceRecoveryWindowsTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / ".cache" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.root = Path(self.temporary.name)
        self.project_a = self.root / "copy-a"
        self.project_b = self.root / "copy-b"
        self.project_a.mkdir()
        self.project_b.mkdir()
        self.identity = DeviceInstanceIdentity("synthetic", f"w03-04-{uuid.uuid4().hex}")
        self.config, _ = RecoveryStore.provision(
            self.project_a,
            self.project_a / "runtime" / "device-recovery",
            self.identity,
        )
        self.context = multiprocessing.get_context("spawn")

    def tearDown(self):
        self.temporary.cleanup()

    def start_holder(self, phase):
        parent, child = self.context.Pipe(duplex=False)
        release_event = self.context.Event()
        process = self.context.Process(
            target=_lease_holder_worker,
            args=(self.identity, str(self.project_a), self.config, phase, child, release_event),
        )
        process.start()
        child.close()
        return process, parent, release_event

    def acquire_b(self):
        lease = WindowsInstanceLease(self.identity, project_root=self.project_b, startup_timeout=5)
        self.assertIs(lease.acquire(), DeviceLeaseState.ACQUIRED)
        return lease

    def test_active_conflict_then_normal_release_allows_cross_copy_recovery(self):
        process, connection, release_event = self.start_holder("hold")
        lease_b = None
        try:
            self.assertTrue(connection.poll(15))
            started = connection.recv()
            self.assertEqual(started["state"], DeviceLeaseState.ACQUIRED.value)
            self.assertEqual(started["disposition"], RecoveryDisposition.FIRST_USE.value)

            competing = WindowsInstanceLease(self.identity, project_root=self.project_b, startup_timeout=1)
            self.assertIs(competing.acquire(), DeviceLeaseState.CONFLICT)

            release_event.set()
            self.assertTrue(connection.poll(15))
            self.assertEqual(connection.recv(), {"released": True})
            process.join(timeout=15)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)

            lease_b = self.acquire_b()
            store_b = RecoveryStore.open(self.config, self.identity)
            assessment = store_b.begin_lease(lease_b.owner_info)
            self.assertIs(assessment.disposition, RecoveryDisposition.READY)
            store_b.release_lease(lease_b.owner_info)
            lease_b.close()
            lease_b = None
        finally:
            release_event.set()
            connection.close()
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if lease_b is not None:
                lease_b.close()

    def _assert_crash_recovered(self, phase, expected_disposition, expected_outcome=None):
        process, connection, _ = self.start_holder(phase)
        lease_b = None
        try:
            self.assertTrue(connection.poll(15))
            started = connection.recv()
            self.assertEqual(started["state"], DeviceLeaseState.ACQUIRED.value)
            self.assertEqual(started["disposition"], RecoveryDisposition.FIRST_USE.value)
            self.assertTrue(connection.poll(15))
            phase_result = connection.recv()
            self.assertTrue(phase_result.get("prepared") or phase_result.get("submitted_once"), phase_result)
            process.join(timeout=15)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 23)

            lease_b = self.acquire_b()
            store_b = RecoveryStore.open(self.config, self.identity)
            assessment = store_b.begin_lease(lease_b.owner_info)
            self.assertIs(assessment.disposition, expected_disposition)
            if expected_outcome is not None:
                self.assertIs(assessment.action_result.outcome, expected_outcome)

            # Repeated recovery inspection has no dispatcher and cannot replay
            # the original action. The synthetic send marker must stay stable.
            again = store_b.assess_current(lease_b.owner_info)
            self.assertIs(again.disposition, expected_disposition)
            send_count = self.project_a / "simulated-send-count.txt"
            if phase == "submitted":
                self.assertEqual(send_count.read_text(encoding="ascii"), "1")
                self.assertEqual(
                    [event["kind"] for event in store_b.read_events()].count("submission_possible"),
                    1,
                )
            else:
                self.assertFalse(send_count.exists())

            if expected_disposition is RecoveryDisposition.REPLAN_REQUIRED:
                store_b.release_lease(lease_b.owner_info)
                lease_b.close()
                lease_b = None
        finally:
            connection.close()
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if lease_b is not None:
                # Unresolved actions intentionally have no normal journal close.
                lease_b.close()

    def test_last_mutex_handle_close_preserves_prepared_action_as_not_submitted(self):
        from app.action_result import ActionOutcome
        self._assert_crash_recovered(
            "prepared",
            RecoveryDisposition.REPLAN_REQUIRED,
            ActionOutcome.NOT_SUBMITTED,
        )

    def test_last_mutex_handle_close_preserves_possible_submission_as_unknown(self):
        from app.action_result import ActionOutcome
        self._assert_crash_recovered(
            "submitted",
            RecoveryDisposition.VERIFY_REQUIRED,
            ActionOutcome.SUBMITTED_UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main()
