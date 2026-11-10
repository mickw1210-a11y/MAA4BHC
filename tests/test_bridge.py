import unittest
from concurrent.futures import Future
from threading import Event

from app.bridge import Bridge
from app.worker import OperationCancelled, SerialWorker
from tests.test_worker import wait_idle


class ForbiddenDevice:
    def __getattr__(self, name):
        raise AssertionError("No device access is permitted in this test: " + name)


class BridgeSafetyTests(unittest.TestCase):
    def test_read_only_mode_rejects_input_before_device_access(self):
        bridge = Bridge(read_only=True, device=ForbiddenDevice())
        bridge._status = "connected"
        bridge._frame = {"frame_id": "fixture", "width": 630, "height": 1120}
        try:
            self.assertTrue(bridge.get_state()["read_only"])
            self.assertFalse(bridge.click(1, 1)["ok"])
            self.assertFalse(bridge.swipe(1, 1, 2, 2, 300)["ok"])
            self.assertFalse(bridge._worker.busy)
        finally:
            bridge.shutdown()

    def test_offline_mode_cannot_reach_device(self):
        bridge = Bridge(offline=True, device=ForbiddenDevice())
        try:
            self.assertFalse(bridge.connect("C:/adb.exe", "127.0.0.1:16384")["ok"])
            self.assertFalse(bridge.screenshot()["ok"])
            self.assertFalse(bridge.click(1, 1)["ok"])
            self.assertFalse(bridge.swipe(1, 1, 2, 2, 300)["ok"])
            self.assertTrue(bridge.stop()["ok"])
            self.assertEqual(bridge.get_state()["status"], "stopped")
        finally:
            bridge.shutdown()

    def test_invalid_coordinates_and_duration_cannot_submit(self):
        bridge = Bridge(device=ForbiddenDevice())
        bridge._frame = {"width": 630, "height": 1120, "frame_id": "fixture"}
        bridge._status = "connected"
        try:
            for x, y in ((-1, 0), (630, 0), (0, 1120), (0.5, 0), (True, 0), ("1.2", 0)):
                self.assertFalse(bridge.click(x, y)["ok"])
            self.assertFalse(bridge.swipe(0, 0, 1, 1, 0)["ok"])
            self.assertFalse(bridge.swipe(0, 0, 1, 1, 3001)["ok"])
            self.assertFalse(bridge._worker.busy)
        finally:
            bridge.shutdown()

    def test_stop_cannot_publish_a_stale_screenshot(self):
        bridge = Bridge(device=ForbiddenDevice())
        bridge.stop()
        future = Future()
        future.set_result({"frame_id": "cancelled-frame", "width": 1, "height": 1})
        bridge._completed("screenshot", future)
        self.assertIsNone(bridge.get_state()["frame"])
        self.assertEqual(bridge.get_state()["status"], "stopped")
        bridge.shutdown()

    def test_native_failure_blocks_next_command(self):
        class FailedDevice:
            def screenshot(self, token):
                raise RuntimeError("connection lost")

        bridge = Bridge(device=FailedDevice())
        bridge._status = "connected"
        try:
            with self.assertLogs("m4b", level="ERROR"):
                self.assertTrue(bridge.screenshot()["ok"])
                wait_idle(bridge._worker)
            self.assertEqual(bridge.get_state()["status"], "error")
            self.assertFalse(bridge.screenshot()["ok"])
        finally:
            bridge.shutdown()

    def test_frame_payload_only_transfers_when_changed(self):
        bridge = Bridge(offline=True)
        bridge._frame = {"frame_id": "fixture", "width": 1, "height": 1, "data": "fixture-not-device"}
        try:
            self.assertIn("data", bridge.get_state("")["frame"])
            self.assertNotIn("data", bridge.get_state("fixture")["frame"])
            self.assertIn("data", bridge._frame)
        finally:
            bridge.shutdown()

    def test_input_requires_a_fresh_screenshot_before_next_input(self):
        class CompletedDevice:
            def click(self, x, y, token):
                return {"message": "fixture completed"}

        bridge = Bridge(device=CompletedDevice())
        bridge._status = "connected"
        bridge._frame = {"frame_id": "fixture", "width": 630, "height": 1120}
        try:
            self.assertTrue(bridge.click(10, 10)["ok"])
            wait_idle(bridge._worker)
            self.assertIsNone(bridge.get_state()["frame"])
            self.assertFalse(bridge.click(10, 10)["ok"])
        finally:
            bridge.shutdown()

