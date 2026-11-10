"""Data-boundary regressions using isolated project-local synthetic data."""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import ROOT
from app.inventory import ManualInventory


class InventoryAuditTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.cache/tmp').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.addCleanup(self.temp.cleanup)
        self.inventory = ManualInventory(Path(self.temp.name))
        stream = io.BytesIO()
        Image.new('RGB', (4, 8), 'white').save(stream, 'PNG')
        self.image = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()

    def shot(self):
        self.inventory.import_image(self.image)
        return self.inventory.shots[-1]

    def grid(self, prefix='道具'):
        return {'rows': [{'name': prefix + str(i), 'quantity': str(i), 'slot': i}
                         for i in range(1, 26)],
                'layout': 'bag_grid_5cols', 'expected_cells': 25,
                'status': 'recognized', 'message': '字段齐全'}

    def test_partial_grid_is_expanded_in_slot_order_and_remains_pending(self):
        shot, result = self.shot(), self.grid()
        result['rows'] = [result['rows'][24], result['rows'][0]]
        report = self.inventory.apply_ocr(shot, [], result)
        self.assertEqual([row['grid_slot'] for row in self.inventory.rows], list(range(1, 26)))
        self.assertEqual(self.inventory.rows[1]['name'], '')
        self.assertEqual(report['status'], 'pending')
        with self.assertRaises(ValueError):
            self.inventory.review(shot)

    def test_cross_page_exact_duplicate_keeps_all_slots_and_is_explicit(self):
        first = self.shot()
        self.inventory.apply_ocr(first, [], self.grid())
        second = self.shot()
        report = self.inventory.apply_ocr(second, [], self.grid())
        self.assertEqual(len(self.inventory.rows), 50)
        self.assertEqual([row['grid_slot'] for row in self.inventory.rows[25:]], list(range(1, 26)))
        self.assertEqual(self.inventory.rows[25]['invalid_reason'], 'duplicate')
        self.assertEqual(self.inventory.rows[25]['duplicate_of'], 0)
        self.assertEqual(report['status'], 'pending')
        with self.assertRaises(ValueError):
            self.inventory.restore(25)
        self.inventory.review(second)
        self.inventory.finish(True)

    def test_conflicting_page_keeps_both_counts_and_requires_resolution(self):
        self.inventory.apply_ocr(self.shot(), [], self.grid())
        second, result = self.shot(), self.grid('另一道具')
        result['rows'][0].update(name='道具1', quantity='99')
        report = self.inventory.apply_ocr(second, [], result)
        self.assertEqual(self.inventory.rows[0]['quantity'], '1')
        self.assertEqual(self.inventory.rows[25]['quantity'], '99')
        self.assertEqual(report['conflicts'], 1)
        with self.assertRaises(ValueError):
            self.inventory.review(second)
        self.inventory.remove(25)
        self.inventory.review(second)

    def test_later_page_never_fills_old_missing_quantity_from_another_frame(self):
        result = self.grid()
        result['rows'][0]['quantity'] = ''
        self.inventory.apply_ocr(self.shot(), [], result)
        second, result = self.shot(), self.grid('另一道具')
        result['rows'][0]['name'] = '道具1'
        self.inventory.apply_ocr(second, [], result)
        self.assertEqual(self.inventory.rows[0]['quantity'], '')
        self.assertEqual(self.inventory.rows[25]['quantity'], '1')

    def test_same_page_duplicate_names_are_not_silently_discarded(self):
        shot, result = self.shot(), self.grid()
        result['rows'][1].update(name='道具1', quantity='1')
        self.inventory.apply_ocr(shot, [], result)
        self.assertEqual(len(self.inventory.rows), 25)
        self.assertFalse(self.inventory.rows[1].get('invalid'))
        with self.assertRaises(ValueError):
            self.inventory.review(shot)

    def test_invalid_or_duplicate_slots_commit_nothing(self):
        for slot in [True, 0, 26, 1]:
            shot, result = self.shot(), self.grid()
            result['rows'][1]['slot'] = slot
            before = self.inventory.snapshot()
            with self.assertRaises(ValueError):
                self.inventory.apply_ocr(shot, [], result)
            self.assertEqual(self.inventory.snapshot(), before)

    def test_bad_field_at_last_slot_does_not_commit_a_partial_page(self):
        shot, result = self.shot(), self.grid()
        result['rows'][24]['name'] = '=FORMULA'
        with self.assertRaises(ValueError):
            self.inventory.apply_ocr(shot, [], result)
        self.assertEqual(self.inventory.rows, [])

    def test_reapplying_committed_page_never_overwrites_manual_correction(self):
        shot = self.shot()
        self.inventory.apply_ocr(shot, [], self.grid())
        self.inventory.update_cell(0, 'quantity', '999')
        with self.assertRaises(ValueError):
            self.inventory.apply_ocr(shot, [], self.grid())
        self.assertEqual(self.inventory.rows[0]['quantity'], '999')

    def test_batch_validation_is_atomic_and_persists_once(self):
        for name in ['甲', '乙', '丙']:
            self.inventory.add(name, '1')
        before = self.inventory.snapshot()
        for indexes in [[0, 99], [True], [], '0']:
            with self.assertRaises(ValueError):
                self.inventory.set_invalid_many(indexes, True)
            self.assertEqual(self.inventory.snapshot(), before)
        with patch.object(self.inventory, '_save', wraps=self.inventory._save) as save:
            self.inventory.set_invalid_many([0, 1, 1], True)
            self.assertEqual(save.call_count, 1)
        self.inventory.set_invalid_many([0, 1], False)
        self.assertEqual([row['name'] for row in self.inventory.rows], ['甲', '乙', '丙'])
        self.assertTrue(all(not row.get('invalid') for row in self.inventory.rows))

    def test_snapshot_nested_reports_do_not_mutate_live_data(self):
        self.inventory.apply_ocr(self.shot(), [], self.grid())
        state = self.inventory.snapshot()
        next(iter(state['ocr_reports'].values()))['rows'][0]['name'] = '外部更改'
        self.assertEqual(self.inventory.rows[0]['name'], '道具1')
        self.assertNotEqual(next(iter(self.inventory.ocr_reports.values()))['rows'][0]['name'], '外部更改')

    def test_bad_image_does_not_create_empty_groups(self):
        with self.assertRaises(ValueError):
            self.inventory.import_image('bad image')
        self.assertEqual(self.inventory.groups, [])
        self.assertFalse(self.inventory.session.exists())

    def test_save_failure_rolls_back_memory_and_preserves_draft(self):
        self.inventory.add('甲', '1')
        before = self.inventory.session.read_bytes()
        with patch.object(Path, 'replace', side_effect=PermissionError('fixture disk failure')):
            with self.assertRaises(PermissionError):
                self.inventory.update_cell(0, 'quantity', '99')
        self.assertEqual(self.inventory.rows[0]['quantity'], '1')
        self.assertEqual(self.inventory.session.read_bytes(), before)

    def test_import_session_save_failure_removes_new_file_and_rolls_back_group(self):
        self.inventory.add('甲', '1')
        before = self.inventory.snapshot()
        with patch.object(Path, 'replace', side_effect=PermissionError('fixture disk failure')):
            with self.assertRaises(PermissionError):
                self.inventory.import_image(self.image)
        self.assertEqual(self.inventory.snapshot(), before)
        self.assertEqual(list(self.inventory.images.iterdir()), [])

    def test_image_write_failure_does_not_leave_partial_file_or_group(self):
        def save(image, path, **kwargs):
            path.write_bytes(b'partial image')
            raise PermissionError('fixture image failure')
        with patch.object(Image.Image, 'save', save):
            with self.assertRaises(PermissionError):
                self.inventory.import_image(self.image)
        self.assertEqual(self.inventory.groups, [])
        self.assertEqual(self.inventory.shots, [])
        self.assertEqual(list(self.inventory.images.iterdir()), [])

    def test_export_permission_failure_keeps_every_screenshot_and_draft(self):
        shot = self.shot()
        self.inventory.add('甲', '1')
        actual = Path.open
        def open_file(path, mode='r', *args, **kwargs):
            if path == self.inventory.output and mode == 'x':
                raise PermissionError('fixture output permission failure')
            return actual(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            with self.assertRaises(PermissionError):
                self.inventory.finish(True)
        resumed = ManualInventory(self.inventory.root)
        self.assertEqual(resumed.phase, 'draft')
        self.assertEqual(resumed.rows, self.inventory.rows)
        self.assertEqual(resumed.export_intent, self.inventory.export_intent)
        self.assertTrue(resumed._image_path(shot).exists())
        self.assertFalse(resumed.output.exists())
        self.assertEqual(resumed.finish(True)['phase'], 'completed')

    def test_partial_csv_is_never_accepted_or_followed_by_image_cleanup(self):
        shot = self.shot()
        self.inventory.add('甲', '1')
        actual = Path.open
        def open_file(path, mode='r', *args, **kwargs):
            if path == self.inventory.output and mode == 'x':
                path.write_bytes(b'partial output')
                raise PermissionError('fixture interrupted output write')
            return actual(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            with self.assertRaises(PermissionError):
                self.inventory.finish(True)
        resumed = ManualInventory(self.inventory.root)
        with self.assertRaises(ValueError):
            resumed.finish(True)
        self.assertTrue(resumed._image_path(shot).exists())
        self.assertEqual(resumed.phase, 'draft')

    def test_export_phase_save_failure_can_recover_own_csv_after_restart(self):
        self.shot()
        self.inventory.add('甲', '1')
        actual = Path.replace
        def replace(path, target):
            if self.inventory.phase == 'exported':
                raise PermissionError('fixture session phase failure')
            return actual(path, target)
        with patch.object(Path, 'replace', replace):
            with self.assertRaises(PermissionError):
                self.inventory.finish(True)
        self.assertEqual(self.inventory.phase, 'draft')
        self.assertTrue(self.inventory.output.exists())
        saved = self.inventory.output.read_bytes()
        resumed = ManualInventory(self.inventory.root)
        self.assertEqual(resumed.finish(True)['phase'], 'completed')
        self.assertEqual(saved, resumed.output.read_bytes())

    def test_invalid_cleanup_path_is_validated_before_any_screenshot_deletion(self):
        shot = self.shot()
        self.inventory.add('甲', '1')
        image = self.inventory._image_path(shot)
        self.inventory.shots.append('../outside.png')
        with self.assertRaises(ValueError):
            self.inventory.finish(True)
        self.assertTrue(image.exists())

    def test_reset_save_failure_never_deletes_previous_draft_images(self):
        shot = self.shot()
        self.inventory.add('甲', '1')
        with patch.object(Path, 'replace', side_effect=PermissionError('fixture disk failure')):
            with self.assertRaises(PermissionError):
                self.inventory.reset()
        self.assertEqual(self.inventory.rows[0]['name'], '甲')
        self.assertTrue(self.inventory._image_path(shot).exists())

    def test_csv_revalidates_loaded_duplicate_names_and_unsafe_fields(self):
        self.inventory.add('甲', '1')
        state = self.inventory.snapshot()
        state['rows'].append({'name': '甲', 'quantity': '2'})
        self.inventory.session.write_text(json.dumps(state), encoding='utf-8')
        with self.assertRaises(ValueError):
            ManualInventory(self.inventory.root).finish(True)
        state['rows'][1] = {'name': '乙', 'quantity': '=1+2'}
        self.inventory.session.write_text(json.dumps(state), encoding='utf-8')
        with self.assertRaises(ValueError):
            ManualInventory(self.inventory.root).finish(True)
        self.assertFalse(self.inventory.output.exists())

    def test_orphan_interrupted_draft_is_not_silently_replaced_by_empty_session(self):
        self.inventory.directory.mkdir(parents=True)
        self.inventory.session.with_suffix('.tmp').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            ManualInventory(self.inventory.root)


if __name__ == '__main__':
    unittest.main()
