import base64
import csv
import io
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app.config import ROOT
from app.inventory import ManualInventory
from app.bridge import Bridge
from app.reset import SessionLease, reset_project


class ResetAndGroupingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inventory = ManualInventory(self.root)
        stream = io.BytesIO()
        Image.new('RGB', (6, 10), 'white').save(stream, format='PNG')
        self.image = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()

    def test_invalid_unknown_row_can_be_skipped_without_shifting_other_slots(self):
        inv = self.inventory
        inv.import_image(self.image)
        shot = inv.shots[0]
        inv.apply_ocr(shot, [], {'rows': [{'name': '', 'quantity': '', 'slot': 1},
                                        {'name': '有效道具', 'quantity': '3', 'slot': 2}],
                               'layout': 'bag_grid_5cols', 'status': 'pending', 'message': '缺项'})
        inv.remove(0)
        self.assertEqual(len(inv.rows), 25)
        self.assertTrue(inv.rows[0]['invalid'])
        self.assertEqual(inv.rows[1]['grid_slot'], 2)
        inv.set_invalid_many(list(range(2, 25)), True)
        inv.review(shot)
        inv.finish(True)
        with inv.output.open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(list(csv.reader(stream)), [['道具名称', '数量'], ['有效道具', '3']])

    def test_invalid_marker_can_be_restored(self):
        self.inventory.add('道具', '1')
        self.inventory.remove(0)
        self.inventory.restore(0)
        self.assertFalse(self.inventory.rows[0]['invalid'])

    def test_one_retry_group_has_multiple_files_and_one_selected_image(self):
        inv = self.inventory
        group_id = inv.create_group()
        for _ in range(3):
            inv.import_image(self.image, group_id=group_id)
        inv.select_group(group_id, inv.shots[1])
        resumed = ManualInventory(self.root)
        self.assertEqual(len(resumed.groups), 1)
        self.assertEqual(len(resumed.groups[0]['images']), 3)
        self.assertEqual(resumed.groups[0]['selected'], inv.shots[1])

    def test_legacy_retry_images_are_grouped_without_changing_rows(self):
        inv = self.inventory
        for _ in range(3):
            inv.import_image(self.image)
        state = inv.snapshot()
        state.pop('groups')
        state['ocr_reports'] = {inv.shots[0]: {'status': 'pending'},
                                inv.shots[1]: {'status': 'superseded'},
                                inv.shots[2]: {'status': 'superseded'}}
        inv.session.write_text(json.dumps(state), encoding='utf-8')
        resumed = ManualInventory(self.root)
        self.assertEqual(len(resumed.groups), 1)
        self.assertEqual(len(resumed.groups[0]['images']), 3)
        self.assertEqual(resumed.rows, inv.rows)

    def test_offline_reset_clears_only_current_generated_images_and_rows(self):
        inv = self.inventory
        inv.import_image(self.image)
        inv.add('道具', '1')
        exported = self.root / 'data/背包道具统计.csv'
        exported.parent.mkdir()
        exported.write_text('keep exported CSV', encoding='utf-8')
        reference = inv.images / 'user-reference.png'
        reference.write_bytes(b'keep reference')
        history = self.root / 'docs/history/example.png'
        history.parent.mkdir(parents=True)
        history.write_bytes(b'keep history')
        result = reset_project(self.root)
        self.assertEqual(result, {'cleared_rows': 1, 'cleared_screenshots': 1})
        resumed = ManualInventory(self.root)
        self.assertEqual(resumed.rows, [])
        self.assertEqual(resumed.shots, [])
        self.assertEqual(resumed.groups, [])
        self.assertEqual(reference.read_bytes(), b'keep reference')
        self.assertEqual(history.read_bytes(), b'keep history')
        self.assertEqual(exported.read_text(encoding='utf-8'), 'keep exported CSV')

    def test_session_lock_prevents_two_record_writers(self):
        first = SessionLease(self.root)
        second = SessionLease(self.root)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.close()
        self.assertTrue(second.acquire())

    def test_reset_command_hands_off_to_running_window_owner(self):
        inv = self.inventory
        inv.import_image(self.image)
        inv.add('道具', '1')
        owner = SessionLease(self.root)
        self.assertTrue(owner.acquire())
        self.addCleanup(owner.close)
        with patch('app.bridge.ManualInventory', return_value=inv):
            bridge = Bridge(manual_inventory=True)
        self.addCleanup(bridge.shutdown)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(reset_project, self.root, timeout=4)
            deadline = time.monotonic() + 4
            while not future.done() and time.monotonic() < deadline:
                bridge.get_state()
                time.sleep(.02)
            result = future.result(timeout=1)
        self.assertEqual(result['cleared_rows'], 1)
        self.assertEqual(inv.rows, [])
        self.assertEqual(bridge.get_state()['status'], 'disconnected')
        self.assertEqual(bridge.get_state()['reset_version'], 1)

    def test_reset_rejects_bad_image_path_before_any_deletion(self):
        inv = self.inventory
        inv.import_image(self.image)
        tracked = inv._image_path(inv.shots[0])
        inv.shots.append('../outside.png')
        with self.assertRaises(ValueError):
            inv.reset()
        self.assertTrue(tracked.exists())
