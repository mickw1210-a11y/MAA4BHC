import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT
from app.inventory_storage_sample import SampleStore


def rows(*pairs):
    return [{'name': name, 'quantity': value} for name, value in pairs]


class SampleStoreTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / '.cache/tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='inventory-store-', dir=root)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = SampleStore(self.directory)
        self.first = rows(('甲', '10'), ('乙', '4'), ('丙', '3'))
        self.second = rows(('甲', '12'), ('丙', '3'))

    def commit(self, snapshot, observation_id):
        return self.store.commit(snapshot, observation_id, reviewed=True, complete=True, order_verified=True)

    def selected(self, name):
        return self.directory / (self.directory / 'HEAD').read_text(encoding='ascii') / name

    def test_csv_baseline_current_changes_and_restart(self):
        self.commit(self.first, 'first')
        baseline = self.selected('baseline.csv').read_bytes()
        state = self.commit(self.second, 'second')
        self.assertEqual(self.selected('baseline.csv').read_bytes(), baseline)
        with self.selected('current.csv').open(encoding='utf-8-sig', newline='') as stream:
            current = list(csv.reader(stream))
        self.assertEqual(current[2][:3], ['乙', '0', '0'])
        with self.selected('changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            changes = list(csv.reader(stream))
        self.assertEqual([(r[0], r[1]) for r in changes[1:]], [('甲', '2'), ('乙', '-4')])
        self.assertEqual(SampleStore(self.directory).read(), state)
        third = rows(('甲', '13'), ('丙', '3'))
        self.commit(third, 'third')
        with self.selected('changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            next_changes = list(csv.reader(stream))
        self.assertEqual(next_changes[:len(changes)], changes)
        self.assertEqual(next_changes[-1][:2], ['甲', '1'])
        self.assertEqual(self.selected('baseline.csv').read_bytes(), baseline)

    def test_retry_same_round_is_idempotent_but_conflicting_input_stops(self):
        first = self.commit(self.first, 'first')
        self.assertEqual(self.commit(self.first, 'first'), first)
        self.assertEqual(len([p for p in self.directory.iterdir() if len(p.name) == 32]), 1)
        with self.assertRaises(ValueError):
            self.commit(self.second, 'first')
        self.assertEqual(self.store.read(), first)

    def test_failed_pointer_update_keeps_previous_committed_generation(self):
        old = self.commit(self.first, 'first')
        head = (self.directory / 'HEAD').read_bytes()
        with patch('app.inventory_storage_sample.os.replace', side_effect=OSError('中断')):
            with self.assertRaises(OSError):
                self.commit(self.second, 'second')
        self.assertEqual((self.directory / 'HEAD').read_bytes(), head)
        self.assertEqual(SampleStore(self.directory).read(), old)
        new = self.commit(self.second, 'second')
        self.assertEqual(len(new['changes']), 2)

    def test_first_commit_interruption_cannot_silently_create_new_baseline(self):
        with patch('app.inventory_storage_sample.os.replace', side_effect=OSError('中断')):
            with self.assertRaises(OSError):
                self.commit(self.first, 'first')
        with self.assertRaisesRegex(ValueError, '未完成'):
            self.commit(self.second, 'second')

    def test_corruption_and_unknown_files_are_not_overwritten(self):
        self.commit(self.first, 'first')
        target = self.selected('baseline.csv')
        target.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.commit(self.second, 'second')
        self.assertEqual(target.read_bytes(), b'broken')
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as temp:
            unknown = Path(temp) / 'other.csv'
            unknown.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                SampleStore(temp).commit(self.first, 'first', reviewed=True, complete=True, order_verified=True)
            self.assertEqual(unknown.read_bytes(), b'keep')

    def test_existing_or_stale_writer_lock_stops_update(self):
        old = self.commit(self.first, 'first')
        (self.directory / '.writer-lock').mkdir()
        with self.assertRaisesRegex(ValueError, '锁'):
            self.commit(self.second, 'second')
        self.assertEqual(self.store.read(), old)

    def test_external_data_directory_is_rejected(self):
        with self.assertRaises(ValueError):
            SampleStore(ROOT / 'data')

    def test_unsafe_spreadsheet_cells_are_rejected_before_writing(self):
        for snapshot, identifier in [(rows(('=1+1', '1')), 'first'),
                                     (rows(('甲', '=1+1')), 'first'),
                                     (rows(('甲', '1')), '=danger')]:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.commit(snapshot, identifier)
            self.assertFalse((self.directory / 'HEAD').exists())

    def test_abrupt_process_exit_preserves_previous_committed_generation(self):
        old = self.commit(self.first, 'first')
        script = '''
import os, sys
from app.inventory_storage_sample import SampleStore
import app.inventory_storage_sample as module
module.os.replace = lambda *args: os._exit(37)
SampleStore(sys.argv[1]).commit([{'name':'甲','quantity':'12'}, {'name':'丙','quantity':'3'}],
                               'second', reviewed=True, complete=True, order_verified=True)
'''
        process = subprocess.run([sys.executable, '-c', script, str(self.directory)], cwd=ROOT,
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(SampleStore(self.directory).read(), old)
        self.assertTrue((self.directory / '.writer-lock').is_dir())
        with self.assertRaisesRegex(ValueError, '锁'):
            self.commit(self.second, 'second')


if __name__ == '__main__':
    unittest.main()
