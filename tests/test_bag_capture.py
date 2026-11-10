import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.bag_capture import BagCollector
from app.config import ROOT
from app.inventory import ManualInventory, active_inventory_paths
from app.ocr import _grid_geometry
from app.worker import OperationCancelled


class Token:
    def check(self): pass
    def dispatch(self, action): return action()


class BagCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".cache/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device = Mock()
        self.collector = BagCollector(self.device, root=self.root, pause=lambda *_: None)
        self.collector._assert_bag = Mock()
        self.collector._settle = Mock(side_effect=[(Path("after1.png"), {}), (Path("after2.png"), {})])

    @staticmethod
    def match(shift, reliable=True):
        return {"reliable": reliable, "shift": shift, "unchanged": shift == 0}

    def test_small_step_uses_measured_displacement_without_reverse_corrections(self):
        with patch("app.bag_capture.estimate_vertical_shift", side_effect=[self.match(243), self.match(222)]):
            _, moved, endpoint = self.collector._move(Token(), Path("first.png"), "up")
        self.assertEqual(moved, 243)
        self.assertFalse(endpoint)
        self.assertEqual([call.args[:2] for call in self.device.swipe_inventory.call_args_list], [("up", 100)])

    def test_one_unchanged_frame_is_not_enough_to_claim_endpoint(self):
        with patch("app.bag_capture.estimate_vertical_shift", side_effect=[self.match(0), self.match(0)]):
            _, moved, endpoint = self.collector._move(Token(), Path("first.png"), "down")
        self.assertTrue(endpoint)
        self.assertEqual(moved, 0)
        self.assertEqual(self.device.swipe_inventory.call_count, 2)

    def test_ambiguous_alignment_stops_without_next_swipe(self):
        with patch("app.bag_capture.estimate_vertical_shift", return_value=self.match(None, False)):
            with self.assertRaisesRegex(RuntimeError, "无法可靠对齐"):
                self.collector._move(Token(), Path("first.png"), "up")
        self.assertEqual(self.device.swipe_inventory.call_count, 1)

    def test_opposite_movement_stops(self):
        with patch("app.bag_capture.estimate_vertical_shift", return_value=self.match(-100)):
            with self.assertRaisesRegex(RuntimeError, "方向或距离异常"):
                self.collector._move(Token(), Path("first.png"), "up")
        self.assertEqual(self.device.swipe_inventory.call_count, 1)

    def test_stop_prevents_device_input(self):
        token = Token()
        token.check = Mock(side_effect=OperationCancelled("stopped"))
        with self.assertRaises(OperationCancelled):
            self.collector._move(token, Path("first.png"), "up")
        self.device.swipe_inventory.assert_not_called()

    def test_new_active_session_preserves_old_draft_and_csv(self):
        old = ManualInventory(self.root)
        old.add("旧道具", "1")
        old.output.parent.mkdir(parents=True)
        old.output.write_text("old CSV", encoding="utf-8")
        old_data, old_csv = old.session.read_bytes(), old.output.read_bytes()
        self.collector._activate()
        paths = active_inventory_paths(self.root)
        self.assertEqual(paths["directory"], self.collector.directory)
        active = ManualInventory(self.root, **paths)
        active.add("新道具", "2")
        self.assertEqual(old.session.read_bytes(), old_data)
        self.assertEqual(old.output.read_bytes(), old_csv)
        self.assertNotEqual(active.output, old.output)

    def test_active_pointer_cannot_redirect_outside_automatic_directory(self):
        pointer = self.root / "runtime/manual-inventory/active.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(json.dumps({"directory": "../../outside", "output": "../../outside/x.csv"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            active_inventory_paths(self.root)

    def test_interrupted_run_is_not_marked_complete_or_exported(self):
        self.collector._capture = Mock(return_value=(Path("initial.png"), {}))
        self.collector._move = Mock(side_effect=OperationCancelled("stop"))
        with self.assertRaises(OperationCancelled):
            self.collector.run(Token())
        self.assertFalse(self.collector.status["capture_complete"])
        self.assertEqual(self.collector.status["phase"], "stopped")
        self.assertFalse(self.collector.inventory.output.exists())

    def test_overlapping_scroll_captures_complete_text_without_requiring_whole_icons(self):
        tokens = [{'text': '测试道具', 'score': .99,
                   'box': [30 + col * 116, 200 + row * 155, 100, 20]}
                  for row in range(5) for col in range(5)]
        geometry = _grid_geometry(tokens, scrolling=True)
        self.assertEqual(geometry['row_name_tops'], [200, 355, 510, 665, 820])

    def test_terminal_tail_chooses_last_five_rows_and_keeps_last_two_items(self):
        tokens = [{'text': '测试道具', 'score': .99,
                   'box': [30 + col * 116, 200 + row * 155, 100, 20]}
                  for row in range(6) for col in range(2 if row == 5 else 5)]
        geometry = _grid_geometry(tokens, scrolling=True, prefer_last=True)
        self.assertEqual(geometry['row_name_tops'], [355, 510, 665, 820, 975])
        self.assertEqual(geometry['row_support'][-1], 2)

    def test_boundary_text_candidate_falls_back_to_next_valid_row(self):
        tokens = [{'text': '测试道具', 'score': .99,
                   'box': [30 + col * 116, 188 + row * 155, 100, 20]}
                  for row in range(6) for col in range(5)]
        geometry = _grid_geometry(tokens, scrolling=True)
        self.assertEqual(geometry['row_name_tops'], [343, 498, 653, 808, 963])

    def test_raw_capture_evidence_is_cleaned_only_after_csv_verified(self):
        inv = self.collector.inventory
        path = inv._capture_path('frame-001-initial.png')
        path.write_bytes(b'fixture capture evidence')
        inv.capture_files.append(path.name)
        inv.add('道具', '3')
        with self.assertRaises(ValueError): inv.finish(False)
        self.assertTrue(path.exists())
        inv.finish(True)
        self.assertFalse(path.exists())
        self.assertTrue(inv.output.exists())

    def test_reset_targets_only_active_round_and_clears_progress(self):
        old = ManualInventory(self.root)
        old.add('旧道具', '1')
        self.collector._activate()
        inv = self.collector.inventory
        path = inv._capture_path('frame-001-initial.png')
        path.write_bytes(b'evidence')
        inv.capture_files.append(path.name)
        inv._save()
        self.collector._publish('review', 'test')
        from app.reset import reset_project
        reset_project(self.root)
        self.assertFalse(path.exists())
        self.assertEqual(ManualInventory(self.root).rows[0]['name'], '旧道具')
        self.assertEqual(json.loads((inv.directory / 'progress.json').read_text(encoding='utf-8'))['phase'], 'idle')

    def test_interrupted_automatic_round_cannot_export_even_if_read_fields_are_complete(self):
        self.collector._activate()
        self.collector.inventory.add('已读道具', '10')
        self.collector._publish('error', '未到底，中途失败')
        with self.assertRaisesRegex(ValueError, '未完整到达底部'):
            self.collector.inventory.finish(True)
        self.assertFalse(self.collector.inventory.output.exists())

    def test_auto_entry_connects_on_explicit_start_without_manual_connect_step(self):
        from app.bridge import Bridge
        from tests.test_worker import wait_idle
        adb = self.root / 'adb.exe'
        adb.write_bytes(b'fixture path, never executed')
        device = Mock()
        inventory = ManualInventory(self.root)
        result = {'frame_id': 'fixture', 'width': 630, 'height': 1120, 'data': '', 'time': 'fixture'}
        with patch('app.bridge.ManualInventory', return_value=inventory), patch('app.bag_capture.BagCollector') as factory:
            factory.return_value.run.return_value = result
            bridge = Bridge(inventory_capture=True, device=device)
            try:
                self.assertTrue(bridge.auto_inventory(str(adb), '127.0.0.1:16544')['ok'])
                wait_idle(bridge._worker)
                device.connect.assert_called_once()
                factory.return_value.run.assert_called_once()
            finally:
                bridge.shutdown()
