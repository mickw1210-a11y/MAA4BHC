"""English CSV names for new sessions and safe legacy-session handling."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.bag_capture import BagCollector
from app.config import ROOT
from app.inventory import ManualInventory, active_inventory_paths


class InventoryFilenameTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.cache/tmp').mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_new_manual_session_uses_english_and_keeps_name_after_restart(self):
        inv = ManualInventory(self.root)
        self.assertEqual(inv.output.name, 'inventory.csv')
        inv.add('道具', '1')
        self.assertEqual(ManualInventory(self.root).output, inv.output)

    def test_new_csv_preserves_chinese_headers_and_item_names(self):
        inv = ManualInventory(self.root)
        inv.add('中文道具', '1.2万')
        inv.finish(True)
        with inv.output.open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(list(csv.reader(stream)), [['道具名称', '数量'], ['中文道具', '1.2万']])

    def test_existing_legacy_csv_blocks_new_export_without_rename(self):
        old = self.root / 'data/背包道具统计.csv'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'legacy inventory')
        inv = ManualInventory(self.root)
        self.assertEqual(inv.output, old)
        inv.add('道具', '1')
        with self.assertRaisesRegex(ValueError, '已存在'):
            inv.finish(True)
        self.assertEqual(old.read_bytes(), b'legacy inventory')
        self.assertFalse((old.parent / 'inventory.csv').exists())

    def test_legacy_draft_preserves_old_target_even_when_csv_does_not_exist(self):
        inv = ManualInventory(self.root)
        inv.add('道具', '1')
        state = json.loads(inv.session.read_text(encoding='utf-8'))
        state['csv_path'] = 'data/背包道具统计.csv'
        inv.session.write_text(json.dumps(state), encoding='utf-8')
        restored = ManualInventory(self.root)
        self.assertEqual(restored.output.name, '背包道具统计.csv')
        self.assertFalse(restored.output.exists())
        restored.finish(True)
        self.assertTrue(restored.output.exists())
        self.assertFalse((self.root / 'data/inventory.csv').exists())

    def test_legacy_session_without_saved_path_still_protects_old_csv(self):
        inv = ManualInventory(self.root)
        inv.add('道具', '1')
        state = json.loads(inv.session.read_text(encoding='utf-8'))
        state.pop('csv_path')
        inv.session.write_text(json.dumps(state), encoding='utf-8')
        old = self.root / 'data/背包道具统计.csv'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'legacy inventory')
        restored = ManualInventory(self.root)
        self.assertEqual(restored.output, old)
        with self.assertRaisesRegex(ValueError, '已存在'):
            restored.finish(True)
        self.assertEqual(old.read_bytes(), b'legacy inventory')

    def test_saved_output_cannot_escape_project(self):
        inv = ManualInventory(self.root)
        inv.add('道具', '1')
        state = json.loads(inv.session.read_text(encoding='utf-8'))
        state['csv_path'] = '../outside.csv'
        inv.session.write_text(json.dumps(state), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '超出项目'):
            ManualInventory(self.root)

    def test_new_automatic_session_uses_english_filename(self):
        collector = BagCollector(Mock(), root=self.root, pause=lambda *_: None)
        self.assertEqual(collector.inventory.output.name, 'inventory.csv')
        collector._activate()
        self.assertEqual(active_inventory_paths(self.root)['output'], collector.inventory.output)

    def test_existing_automatic_pointer_keeps_legacy_target(self):
        directory = self.root / 'runtime/auto-inventory/old'
        directory.mkdir(parents=True)
        pointer = self.root / 'runtime/manual-inventory/active.json'
        pointer.parent.mkdir(parents=True)
        pointer.write_text(json.dumps({'directory': directory.relative_to(self.root).as_posix(),
                                       'output': (directory / '背包道具统计.csv').relative_to(self.root).as_posix()}), encoding='utf-8')
        restored = ManualInventory(self.root, **active_inventory_paths(self.root))
        self.assertEqual(restored.output.name, '背包道具统计.csv')


if __name__ == '__main__':
    unittest.main()
