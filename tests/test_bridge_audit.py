"""Exercise retry boundaries and the real bridge without using a device."""
import base64
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.bridge import Bridge
from app.config import ROOT
from app.inventory import ManualInventory
from tests.test_worker import wait_idle


def picture(color):
    buffer = io.BytesIO()
    Image.new("RGB", (630, 1120), color).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


class BridgeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.inventory = ManualInventory(Path(self.temporary.name))

    def bridge(self, pictures, results):
        class ImageDevice:
            captures = 0

            def screenshot(device, token, *, save=True):
                self.assertFalse(save)
                value = pictures[min(device.captures, len(pictures) - 1)]
                device.captures += 1
                return {"data": value, "width": 630, "height": 1120,
                        "frame_id": str(device.captures), "time": "fixture"}

        class ResultOcr:
            calls = 0

            def read_inventory(engine, path, token):
                result = results[min(engine.calls, len(results) - 1)]
                engine.calls += 1
                return [], result

        device, engine = ImageDevice(), ResultOcr()
        with patch("app.bridge.ManualInventory", return_value=self.inventory):
            bridge = Bridge(inventory_capture=True, device=device)
        bridge._ocr = engine
        bridge._status = "connected"
        self.addCleanup(bridge.shutdown)
        return bridge, device, engine

    @staticmethod
    def result(name="测试道具", quantity="5", status="pending"):
        return {"rows": [{"name": name, "quantity": quantity}],
                "status": status, "message": "fixture"}

    def capture(self, bridge):
        self.assertTrue(bridge.screenshot()["ok"])
        wait_idle(bridge._worker)
        self.assertIsNotNone(bridge.get_state()["frame"])

    def test_spelling_variation_on_identical_image_does_not_stop_retry_early(self):
        bridge, device, engine = self.bridge([picture("white")], [self.result("测试道具"), self.result("测试道俱")])
        self.capture(bridge)
        self.assertEqual((device.captures, engine.calls), (3, 3))
        self.assertEqual(self.inventory.rows[0]["name"], "")
        report = self.inventory.ocr_reports[self.inventory.groups[0]["selected"]]
        self.assertEqual(report["status"], "pending")
        self.assertEqual(report["retry_conflicts"], 1)

    def test_changed_image_stops_before_running_ocr_on_another_page(self):
        bridge, device, engine = self.bridge([picture("white"), picture("black")], [self.result()])
        self.capture(bridge)
        self.assertEqual((device.captures, engine.calls), (2, 1))
        self.assertEqual(len(self.inventory.rows), 1)
        self.assertEqual(self.inventory.rows[0]["name"], "测试道具")
        self.assertEqual(len(self.inventory.groups), 1)
        self.assertEqual(self.inventory.groups[0]["selected"], self.inventory.shots[0])
        self.assertEqual(self.inventory.ocr_reports[self.inventory.shots[1]]["status"], "superseded")

    def test_quantity_disagreement_is_not_silently_selected(self):
        bridge, _, engine = self.bridge([picture("white")], [self.result(quantity="5"), self.result(quantity="6", status="recognized")])
        self.capture(bridge)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(self.inventory.rows[0]["quantity"], "")
        self.assertFalse(bridge.screenshot()["ok"])

    def test_signature_allows_small_luminance_noise_but_rejects_navigation(self):
        signature = ((630, 1120), (100,) * (64 * 96))
        self.assertTrue(Bridge._same_inventory_frame(signature, ((630, 1120), (103,) * (64 * 96))))
        self.assertFalse(Bridge._same_inventory_frame(signature, ((630, 1120), (160,) * (64 * 96))))
        self.assertFalse(Bridge._same_inventory_frame(signature, ((750, 1334), signature[1])))

    def test_batch_bridge_validates_all_indexes_before_changing_any_row(self):
        bridge, _, _ = self.bridge([picture("white")], [self.result()])
        self.inventory.add("道具甲", "1")
        self.inventory.add("道具乙", "2")
        self.assertFalse(bridge.inventory_action("invalidate_many", {"indexes": [0, 999]})["ok"])
        self.assertFalse(any(row.get("invalid") for row in self.inventory.rows))
        self.assertFalse(bridge.inventory_action("invalidate_many", {"indexes": [False]})["ok"])
        self.assertFalse(bridge.inventory_action("invalidate_many", [0])["ok"])
        self.assertTrue(bridge.inventory_action("invalidate_many", {"indexes": [0, 1]})["ok"])
        self.assertTrue(all(row.get("invalid") for row in self.inventory.rows))
        self.assertTrue(bridge.inventory_action("restore_many", {"indexes": [0, 1]})["ok"])
        self.assertFalse(any(row.get("invalid") for row in self.inventory.rows))
