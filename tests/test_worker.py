import time
import unittest
from threading import Event

from app.worker import OperationCancelled, SerialWorker


def wait_idle(worker):
    deadline = time.monotonic() + 2
    while worker.busy and time.monotonic() < deadline:
        time.sleep(0.005)
    if worker.busy:
        raise AssertionError("worker remained busy")


class WorkerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.worker = SerialWorker()

    def tearDown(self):
        self.worker.close()

    def test_stop_is_immediate_and_prevents_next_dispatch(self):
        started, release = Event(), Event()
        commands = []

        def action(token):
            token.dispatch(lambda: commands.append("already sent"))
            started.set()
            release.wait(2)
            token.dispatch(lambda: commands.append("must never send"))

        future = self.worker.submit(action)
        self.assertTrue(started.wait(1))
        self.worker.stop()
        self.assertFalse(future.done())
        self.assertTrue(self.worker.stopped)
        release.set()
        with self.assertRaises(OperationCancelled):
            future.result(2)
        wait_idle(self.worker)
        self.assertEqual(commands, ["already sent"])

    def test_repeated_requests_do_not_overlap(self):
        started, release = Event(), Event()
        future = self.worker.submit(lambda token: (started.set(), release.wait(2)))
        self.assertTrue(started.wait(1))
        with self.assertRaises(RuntimeError):
            self.worker.submit(lambda token: None)
        release.set()
        future.result(2)
        wait_idle(self.worker)

    def test_stopped_queue_requires_explicit_resume(self):
        self.worker.stop()
        with self.assertRaises(OperationCancelled):
            self.worker.submit(lambda token: "unexpected")
        self.assertEqual(self.worker.submit(lambda token: "resumed", resume=True).result(2), "resumed")
        wait_idle(self.worker)

    def test_failure_stops_following_operations(self):
        def fail(token):
            raise RuntimeError("result uncertain")

        future = self.worker.submit(fail)
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            future.result(2)
        wait_idle(self.worker)
        with self.assertRaises(OperationCancelled):
            self.worker.submit(lambda token: "unexpected")

    def test_close_rejects_new_work(self):
        self.worker.close()
        with self.assertRaises(RuntimeError):
            self.worker.submit(lambda token: None, resume=True)

