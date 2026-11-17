import multiprocessing
import os
from pathlib import Path
import time
from tempfile import TemporaryDirectory
import unittest

from app.config import ROOT
from app.device_identity import DeviceInstanceIdentity, DeviceLocator
from app.device_lease import (
    DeviceLeaseError,
    DeviceLeaseState,
    LeaseOwnerInfo,
    ProcessLiveness,
    WindowsInstanceLease,
    owner_process_liveness,
    read_local_lease_events,
)


def _compete_for_lease(identity, project_root, result_queue, release_event):
    lease = WindowsInstanceLease(identity, project_root=project_root)
    state = lease.acquire()
    owner = lease.owner_info
    result_queue.put({
        "state": state.value,
        "owner": owner.to_dict() if owner else None,
        "liveness": lease.owner_liveness.value,
    })
    if state is DeviceLeaseState.ACQUIRED:
        release_event.wait(10)
        lease.close()


def _exit_while_holding_lease(identity, project_root, connection):
    lease = WindowsInstanceLease(identity, project_root=project_root)
    state = lease.acquire()
    connection.send(state.value)
    os._exit(23 if state is DeviceLeaseState.ACQUIRED else 24)


@unittest.skipUnless(os.name == "nt", "Windows named mutex is required")
class WindowsInstanceLeaseTests(unittest.TestCase):
    def identity(self):
        return DeviceInstanceIdentity(
            "mumu12",
            f"index=0;created_timestamp={time.time_ns()}",
        )

    def test_separate_processes_and_project_copies_share_one_device_lease(self):
        identity = self.identity()
        first_locator = DeviceLocator("C:/project-copy-a", "C:/MuMu/adb.exe", "127.0.0.1:16384")
        second_locator = DeviceLocator("D:/project-copy-b", "D:/tools/adb.exe", "127.0.0.1:7555")
        self.assertNotEqual(first_locator, second_locator)

        test_root = ROOT / ".cache" / "tmp"
        test_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=test_root) as project_a, TemporaryDirectory(dir=test_root) as project_b:
            owner = WindowsInstanceLease(identity, project_root=project_a)
            self.assertIs(owner.acquire(), DeviceLeaseState.ACQUIRED)
            context = multiprocessing.get_context("spawn")
            result_queue = context.Queue()
            release_event = context.Event()
            competitor = context.Process(
                target=_compete_for_lease,
                args=(identity, project_b, result_queue, release_event),
            )
            try:
                competitor.start()
                result = result_queue.get(timeout=15)
                self.assertEqual(result["state"], DeviceLeaseState.CONFLICT.value)
                self.assertEqual(result["owner"]["process_id"], os.getpid())
                self.assertEqual(result["owner"]["identity_digest"], identity.lease_key)
                self.assertEqual(result["liveness"], ProcessLiveness.ALIVE.value)
                competitor.join(timeout=15)
                self.assertFalse(competitor.is_alive())
                self.assertEqual(competitor.exitcode, 0)
                events = read_local_lease_events(project_a, identity)
                self.assertEqual([event["event"] for event in events], ["acquired"])
                self.assertNotIn("127.0.0.1:16384", repr(events))
                self.assertNotIn(str(project_a), repr(events))
            finally:
                if competitor.is_alive():
                    competitor.terminate()
                    competitor.join(timeout=5)
                owner.close()
                result_queue.close()
                result_queue.join_thread()

    def test_released_lease_can_be_acquired_by_another_process(self):
        identity = self.identity()
        test_root = ROOT / ".cache" / "tmp"
        test_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=test_root) as project_a, TemporaryDirectory(dir=test_root) as project_b:
            owner = WindowsInstanceLease(identity, project_root=project_a)
            self.assertIs(owner.acquire(), DeviceLeaseState.ACQUIRED)
            owner.close()

            context = multiprocessing.get_context("spawn")
            result_queue = context.Queue()
            release_event = context.Event()
            competitor = context.Process(
                target=_compete_for_lease,
                args=(identity, project_b, result_queue, release_event),
            )
            try:
                competitor.start()
                result = result_queue.get(timeout=15)
                self.assertEqual(result["state"], DeviceLeaseState.ACQUIRED.value)
                release_event.set()
                competitor.join(timeout=15)
                self.assertFalse(competitor.is_alive())
                self.assertEqual(competitor.exitcode, 0)
                events = read_local_lease_events(project_a, identity)
                self.assertEqual([event["event"] for event in events], ["acquired", "release_requested"])
            finally:
                release_event.set()
                if competitor.is_alive():
                    competitor.terminate()
                    competitor.join(timeout=5)
                result_queue.close()
                result_queue.join_thread()

    def test_crash_marker_is_not_persistent_after_last_handle_closes(self):
        identity = self.identity()
        context = multiprocessing.get_context("spawn")
        test_root = ROOT / ".cache" / "tmp"
        test_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=test_root) as project_a, TemporaryDirectory(dir=test_root) as project_b:
            self._assert_crash_record_is_local_only(identity, project_a, project_b, context)

    def test_diagnostics_cannot_be_written_outside_the_project(self):
        with self.assertRaisesRegex(ValueError, "当前项目内"):
            WindowsInstanceLease(self.identity(), project_root=ROOT.parent)

    def test_corrupt_local_journal_fails_closed(self):
        identity = self.identity()
        test_root = ROOT / ".cache" / "tmp"
        test_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=test_root) as project_root:
            path = Path(project_root) / "runtime" / "logs" / "device-leases" / f"{identity.lease_key}.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(DeviceLeaseError, "身份不匹配"):
                read_local_lease_events(project_root, identity)

    def _assert_crash_record_is_local_only(self, identity, project_a, project_b, context):
        parent_connection, child_connection = context.Pipe(duplex=False)
        owner = context.Process(
            target=_exit_while_holding_lease,
            args=(identity, project_a, child_connection),
        )
        owner.start()
        child_connection.close()
        try:
            self.assertTrue(parent_connection.poll(15))
            self.assertEqual(parent_connection.recv(), DeviceLeaseState.ACQUIRED.value)
            owner.join(timeout=15)
            self.assertFalse(owner.is_alive())
            self.assertEqual(owner.exitcode, 23)
        finally:
            parent_connection.close()
            if owner.is_alive():
                owner.terminate()
                owner.join(timeout=5)

        events = read_local_lease_events(project_a, identity)
        self.assertEqual([event["event"] for event in events], ["acquired"])
        self.assertEqual(owner_process_liveness(LeaseOwnerInfo.from_dict(events[0])), ProcessLiveness.EXITED)

        # The diagnostic journal stays in project A. The mutex itself has no
        # persistent marker, so project B cannot see project A's crash record.
        self.assertEqual(read_local_lease_events(project_b, identity), ())
        reacquirer = WindowsInstanceLease(identity, project_root=project_b)
        self.assertIs(reacquirer.acquire(), DeviceLeaseState.ACQUIRED)
        reacquirer.close()


if __name__ == "__main__":
    unittest.main()
