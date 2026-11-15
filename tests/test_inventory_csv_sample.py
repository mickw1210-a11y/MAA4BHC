import csv
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from app.config import ROOT
from app.bag_capture import BagCollector
from app.inventory import ManualInventory
from app.inventory_comparison import read_inventory_csv
from app.inventory_csv_sample import CsvSampleStore


def rows(*pairs):
    return [{'name': name, 'quantity': quantity} for name, quantity in pairs]


class CsvSampleTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / '.cache/tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='csv-transaction-', dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = CsvSampleStore(self.path)
        self.first = rows(('甲', '10'), ('乙', '4'), ('丙', '3'))
        self.second = rows(('甲', '12'), ('丙', '3'))

    def commit(self, snapshot, identifier):
        timestamp = {'first': '2026-11-14T08:00:00+08:00', 'second': '2026-11-15T09:30:00+08:00'}[identifier]
        return self.store.commit(snapshot, identifier, scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                                 observed_at=timestamp, started_at=timestamp)

    def test_csv_updates_and_retries_preserve_baseline_and_append_changes(self):
        self.commit(self.first, 'first')
        baseline = (self.path / 'baseline.csv').read_bytes()
        before_changes = (self.path / 'changes.csv').read_bytes()
        self.commit(self.second, 'second')
        after_changes = (self.path / 'changes.csv').read_bytes()
        self.assertTrue(after_changes.startswith(before_changes))
        self.assertEqual((self.path / 'baseline.csv').read_bytes(), baseline)
        with (self.path / 'current.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(list(csv.reader(stream))[2], ['乙', '0'])
        with (self.path / 'inventory-status.csv').open(encoding='utf-8-sig', newline='') as stream:
            status = list(csv.DictReader(stream))[1]
        self.assertEqual((status['道具名称'], status['本次观察'], status['推断轮次'], status['左侧参照'], status['右侧参照']),
                         ('乙', '否', 'second', '甲', '丙'))
        new = self.commit(self.second, 'second')
        self.assertEqual((self.path / 'changes.csv').read_bytes(), after_changes)
        self.assertEqual(CsvSampleStore(self.path).read(), new)
        with self.assertRaises(ValueError):
            self.commit(self.first, 'second')

    def test_interrupted_replace_recovers_on_next_read(self):
        self.commit(self.first, 'first')
        actual = os.replace
        def replace(source, target):
            if Path(target).name == 'state.json':
                raise PermissionError('模拟中断')
            return actual(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=replace):
            with self.assertRaises(PermissionError):
                self.commit(self.second, 'second')
        self.assertTrue((self.path / 'transaction.json').exists())
        state = CsvSampleStore(self.path).read()
        self.assertEqual(state['observations'], ['first', 'second'])
        self.assertEqual([(r['name'], r['delta']) for r in state['changes']], [('甲', 2), ('乙', -4)])
        self.assertFalse((self.path / 'transaction.json').exists())
        self.commit(self.second, 'second')
        self.assertEqual(len(self.store.read()['changes']), 2)

    def test_partial_append_recovers_without_duplicate_or_truncation(self):
        self.commit(self.first, 'first')
        real_replace = os.replace
        def fail_before_state(source, target):
            if Path(target).name == 'state.json':
                raise PermissionError('模拟中断')
            return real_replace(source, target)
        old = (self.path / 'changes.csv').read_bytes()
        with patch('app.inventory_csv_sample.os.replace', side_effect=fail_before_state):
            with self.assertRaises(PermissionError):
                self.commit(self.second, 'second')
        path = self.path / 'changes.csv'
        complete = path.read_bytes()
        self.assertGreater(len(complete), len(old) + 4)
        path.write_bytes(complete[:len(old) + 4])
        self.store.read()
        self.assertEqual(path.read_bytes(), complete)

    def test_short_write_is_detected_and_recovered_without_duplicate(self):
        self.commit(self.first, 'first')
        actual_open = Path.open
        class ShortWriter:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def write(self, data):
                return self.stream.write(data[:5])
            def flush(self):
                return self.stream.flush()
            def fileno(self):
                return self.stream.fileno()
        def open_file(path, mode='r', *args, **kwargs):
            stream = actual_open(path, mode, *args, **kwargs)
            if path.name == 'changes.csv' and mode == 'ab':
                return ShortWriter(stream)
            return stream
        with patch.object(Path, 'open', open_file):
            with self.assertRaisesRegex(OSError, '未完整写入'):
                self.commit(self.second, 'second')
        self.assertTrue((self.path / 'transaction.json').exists())
        state = CsvSampleStore(self.path).read()
        self.assertEqual([(r['name'], r['delta']) for r in state['changes']], [('甲', 2), ('乙', -4)])

    def test_short_staging_write_never_replaces_current_file(self):
        self.commit(self.first, 'first')
        original_current = (self.path / 'current.csv').read_bytes()
        actual_open = Path.open
        count = []
        class ShortWriter:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def write(self, data): return self.stream.write(data[:5])
            def flush(self): return self.stream.flush()
            def fileno(self): return self.stream.fileno()
        def open_file(path, mode='r', *args, **kwargs):
            stream = actual_open(path, mode, *args, **kwargs)
            if path.name.startswith('.stage-') and mode == 'xb':
                count.append(1)
                if len(count) == 2:  # journal staging is first; current CSV is second
                    return ShortWriter(stream)
            return stream
        with patch.object(Path, 'open', open_file):
            with self.assertRaisesRegex(OSError, '未完整写入'):
                self.commit(self.second, 'second')
        self.assertEqual((self.path / 'current.csv').read_bytes(), original_current)
        self.assertTrue((self.path / 'transaction.json').exists())
        self.assertEqual(CsvSampleStore(self.path).read()['observations'], ['first', 'second'])

    def test_append_recovers_at_multiple_byte_boundaries(self):
        for cut in (0, 1, 2, 7, -1):
            with self.subTest(cut=cut), tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as directory:
                store = CsvSampleStore(directory)
                flags = dict(scope='ordinary-items', reviewed=True, complete=True, order_verified=True)
                store.commit(self.first, 'first', **flags, observed_at='2026-11-14T08:00:00+08:00', started_at='2026-11-14T08:00:00+08:00')
                path = Path(directory) / 'changes.csv'
                before = path.read_bytes()
                real = os.replace
                def interrupt(source, target):
                    if Path(target).name == 'state.json':
                        raise PermissionError('中断')
                    return real(source, target)
                with patch('app.inventory_csv_sample.os.replace', side_effect=interrupt):
                    with self.assertRaises(PermissionError):
                        store.commit(self.second, 'second', **flags, observed_at='2026-11-15T09:30:00+08:00', started_at='2026-11-15T09:30:00+08:00')
                complete = path.read_bytes()
                appended = complete[len(before):]
                count = len(appended) - 1 if cut == -1 else min(cut, len(appended))
                path.write_bytes(before + appended[:count])
                self.assertEqual(len(CsvSampleStore(directory).read()['changes']), 2)
                self.assertEqual(path.read_bytes(), complete)

    def test_external_edit_stops_recovery_without_overwrite(self):
        self.commit(self.first, 'first')
        real_replace = os.replace
        def fail_before_state(source, target):
            if Path(target).name == 'state.json':
                raise PermissionError('模拟中断')
            return real_replace(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=fail_before_state):
            with self.assertRaises(PermissionError):
                self.commit(self.second, 'second')
        path = self.path / 'changes.csv'
        with path.open('ab') as stream:
            stream.write(b'foreign-data')
        modified = path.read_bytes()
        with self.assertRaisesRegex(ValueError, '修改'):
            self.store.read()
        self.assertEqual(path.read_bytes(), modified)
        self.assertTrue((self.path / 'transaction.json').exists())

    def test_external_edit_during_commit_is_checked_again_before_append(self):
        self.commit(self.first, 'first')
        import app.inventory_csv_sample as module
        original = module._atomic_replace
        changes = self.path / 'changes.csv'
        def modify_during_commit(directory, target, data):
            result = original(directory, target, data)
            if target.name == 'current.csv':
                with changes.open('ab') as stream:
                    stream.write(b'foreign-data')
            return result
        with patch('app.inventory_csv_sample._atomic_replace', side_effect=modify_during_commit):
            with self.assertRaisesRegex(ValueError, '修改'):
                self.commit(self.second, 'second')
        self.assertTrue(changes.read_bytes().endswith(b'foreign-data'))
        self.assertTrue((self.path / 'transaction.json').exists())

    def test_abrupt_exit_releases_lock_and_recovers(self):
        self.commit(self.first, 'first')
        script = '''
import os, sys
from pathlib import Path
import app.inventory_csv_sample as module
real = os.replace
def fail(source, target):
    if Path(target).name == 'state.json': os._exit(37)
    return real(source, target)
module.os.replace = fail
module.CsvSampleStore(sys.argv[1]).commit([{'name':'甲','quantity':'12'}, {'name':'丙','quantity':'3'}],
                                        'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                                        observed_at='2026-11-15T09:30:00+08:00', started_at='2026-11-15T09:30:00+08:00')
'''
        process = subprocess.run([sys.executable, '-c', script, str(self.path)], cwd=ROOT,
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(CsvSampleStore(self.path).read()['observations'], ['first', 'second'])

    def test_process_exit_after_each_committed_file_recovers_whole_round(self):
        script = '''
import os, sys
from pathlib import Path
import app.inventory_csv_sample as module
real = os.replace
def crash_after(source, target):
    real(source, target)
    if Path(target).name == sys.argv[2]: os._exit(37)
module.os.replace = crash_after
module.CsvSampleStore(sys.argv[1]).commit([{'name':'甲','quantity':'12'}, {'name':'丙','quantity':'3'}],
                                        'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                                        observed_at='2026-11-15T09:30:00+08:00', started_at='2026-11-15T09:30:00+08:00')
'''
        for target_name in ('transaction.json', 'current.csv', 'inventory-status.csv', 'state.json'):
            with self.subTest(target=target_name), tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as directory:
                store = CsvSampleStore(directory)
                store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                             observed_at='2026-11-14T08:00:00+08:00', started_at='2026-11-14T08:00:00+08:00')
                process = subprocess.run([sys.executable, '-c', script, directory, target_name],
                                         cwd=ROOT, capture_output=True, timeout=20)
                self.assertEqual(process.returncode, 37)
                restored = CsvSampleStore(directory).read()
                self.assertEqual(restored['observations'], ['first', 'second'])
                self.assertEqual(len(restored['changes']), 2)
                self.assertFalse((Path(directory) / 'transaction.json').exists())

    def test_real_process_exit_during_partial_utf8_append_recovers(self):
        self.commit(self.first, 'first')
        script = '''
import os, sys
from pathlib import Path
import app.inventory_csv_sample as module
original = Path.open
class CrashAfterPartial:
    def __init__(self, stream): self.stream = stream
    def __enter__(self): return self
    def __exit__(self, *args): self.stream.close()
    def write(self, data):
        self.stream.write(data[:7]); self.stream.flush(); os.fsync(self.stream.fileno())
        os._exit(38)
def open_file(path, mode='r', *args, **kwargs):
    stream = original(path, mode, *args, **kwargs)
    if path.name == 'changes.csv' and mode == 'ab': return CrashAfterPartial(stream)
    return stream
Path.open = open_file
module.CsvSampleStore(sys.argv[1]).commit([{'name':'甲','quantity':'12'}, {'name':'丙','quantity':'3'}],
                                        'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                                        started_at='2026-11-15T09:00:00+08:00',
                                        observed_at='2026-11-15T09:30:00+08:00')
'''
        process = subprocess.run([sys.executable, '-c', script, str(self.path)], cwd=ROOT,
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 38)
        state = CsvSampleStore(self.path).read()
        self.assertEqual(len(state['changes']), 2)
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual([(r['道具名称'], r['净变化']) for r in csv.DictReader(stream)], [('甲', '2'), ('乙', '-4')])

    def test_real_process_exit_during_first_baseline_preserves_original_observation(self):
        script = '''
import os, sys
from pathlib import Path
import app.inventory_csv_sample as module
original = os.replace
def crash(source, target):
    if Path(target).name == 'baseline.csv': os._exit(39)
    return original(source, target)
module.os.replace = crash
module.CsvSampleStore(sys.argv[1]).commit([{'name':'甲','quantity':'10'}, {'name':'乙','quantity':'4'}],
    'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
    started_at='2026-11-14T07:55:00+08:00', observed_at='2026-11-14T08:00:00+08:00')
'''
        process = subprocess.run([sys.executable, '-c', script, str(self.path)], cwd=ROOT,
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 39)
        state = CsvSampleStore(self.path).read()
        self.assertEqual(state['baseline'], rows(('甲', '10'), ('乙', '4')))
        self.assertEqual(state['changes'], [])
        self.assertFalse((self.path / 'transaction.json').exists())

    def test_unknown_or_corrupt_files_are_preserved(self):
        path = self.path / 'unknown.csv'
        path.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.commit(self.first, 'first')
        self.assertEqual(path.read_bytes(), b'keep')

    def test_commit_interruption_at_each_replacement_boundary(self):
        for target_name in ('transaction.json', 'current.csv', 'state.json'):
            with self.subTest(target=target_name), tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as directory:
                store = CsvSampleStore(directory)
                store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                             observed_at='2026-11-14T08:00:00+08:00', started_at='2026-11-14T08:00:00+08:00')
                actual = os.replace
                def interrupted(source, target):
                    if Path(target).name == target_name:
                        raise PermissionError('模拟中断')
                    return actual(source, target)
                with patch('app.inventory_csv_sample.os.replace', side_effect=interrupted):
                    with self.assertRaises(PermissionError):
                        store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                                     observed_at='2026-11-15T09:30:00+08:00', started_at='2026-11-15T09:30:00+08:00')
                resumed = CsvSampleStore(directory).read()
                if target_name == 'transaction.json':
                    self.assertEqual(resumed['observations'], ['first'])
                else:
                    self.assertEqual(resumed['observations'], ['first', 'second'])
                store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                             observed_at='2026-11-15T09:30:00+08:00', started_at='2026-11-15T09:30:00+08:00')
                self.assertEqual(len(store.read()['changes']), 2)

    def test_first_commit_interrupted_after_journal_can_resume_baseline(self):
        actual = os.replace
        def interrupted(source, target):
            if Path(target).name == 'baseline.csv':
                raise PermissionError('首次写入中断')
            return actual(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=interrupted):
            with self.assertRaises(PermissionError):
                self.commit(self.first, 'first')
        restored = CsvSampleStore(self.path).read()
        self.assertEqual(restored['baseline'], self.first)
        self.assertEqual(restored['changes'], [])
        self.commit(self.first, 'first')
        self.assertEqual(self.store.read()['observations'], ['first'])

    def test_damaged_recovery_record_does_not_touch_existing_files(self):
        self.commit(self.first, 'first')
        original = {name: (self.path / name).read_bytes()
                    for name in ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json')}
        (self.path / 'transaction.json').write_bytes(b'{broken')
        with self.assertRaises(ValueError):
            self.store.read()
        self.assertEqual({name: (self.path / name).read_bytes() for name in original}, original)
        self.assertEqual((self.path / 'transaction.json').read_bytes(), b'{broken')

    def test_valid_json_but_bad_recovery_checksum_is_preserved_and_rejected(self):
        import json
        self.commit(self.first, 'first')
        real_replace = os.replace
        def interrupt(source, target):
            if Path(target).name == 'current.csv':
                raise PermissionError('模拟中断')
            return real_replace(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=interrupt):
            with self.assertRaises(PermissionError):
                self.commit(self.second, 'second')
        journal = self.path / 'transaction.json'
        envelope = json.loads(journal.read_text(encoding='utf-8'))
        envelope['sha256'] = '0' * 64
        journal.write_text(json.dumps(envelope), encoding='utf-8')
        before = {name: (self.path / name).read_bytes()
                  for name in ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json', 'transaction.json')}
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.store.read()
        self.assertEqual({name: (self.path / name).read_bytes() for name in before}, before)

    def test_unknown_recovery_version_is_preserved_without_touching_csv(self):
        import json
        self.commit(self.first, 'first')
        real_replace = os.replace
        def interrupt(source, target):
            if Path(target).name == 'current.csv':
                raise PermissionError('模拟中断')
            return real_replace(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=interrupt):
            with self.assertRaises(PermissionError):
                self.commit(self.second, 'second')
        journal = self.path / 'transaction.json'
        envelope = json.loads(journal.read_text(encoding='utf-8'))
        envelope['format_version'] = 999
        journal.write_text(json.dumps(envelope), encoding='utf-8')
        names = ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json', 'transaction.json')
        before = {name: (self.path / name).read_bytes() for name in names}
        with self.assertRaisesRegex(ValueError, '版本不支持'):
            self.store.read()
        self.assertEqual({name: (self.path / name).read_bytes() for name in names}, before)

    def test_unknown_state_version_stops_without_changing_existing_files(self):
        import json
        self.commit(self.first, 'first')
        path = self.path / 'state.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        state['format_version'] = 999
        path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        names = ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json')
        before = {name: (self.path / name).read_bytes() for name in names}
        with self.assertRaisesRegex(ValueError, '版本不支持'):
            self.store.read()
        self.assertEqual({name: (self.path / name).read_bytes() for name in names}, before)

    def test_missing_or_boolean_version_is_not_silently_migrated(self):
        import json
        self.commit(self.first, 'first')
        path = self.path / 'state.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        for value in (None, True):
            with self.subTest(version=value):
                changed = dict(state)
                if value is None:
                    changed.pop('format_version')
                else:
                    changed['format_version'] = value
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding='utf-8')
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, '版本不支持'):
                    self.store.read()
                self.assertEqual(path.read_bytes(), before)

    def test_edited_existing_change_history_blocks_recovery(self):
        self.commit(self.first, 'first')
        self.commit(self.second, 'second')
        third = rows(('甲', '13'), ('丙', '3'))
        real_replace = os.replace
        def interrupt(source, target):
            if Path(target).name == 'current.csv':
                raise PermissionError('模拟中断')
            return real_replace(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=interrupt):
            with self.assertRaises(PermissionError):
                self.store.commit(third, 'third', scope='ordinary-items', reviewed=True, complete=True,
                                  order_verified=True, started_at='2026-11-16T09:00:00+08:00',
                                  observed_at='2026-11-16T09:30:00+08:00')
        history = self.path / 'changes.csv'
        content = bytearray(history.read_bytes())
        content[-4] ^= 1
        history.write_bytes(content)
        modified = history.read_bytes()
        with self.assertRaisesRegex(ValueError, '修改'):
            self.store.read()
        self.assertEqual(history.read_bytes(), modified)

    def test_manual_edit_before_next_commit_is_never_replaced(self):
        self.commit(self.first, 'first')
        current = self.path / 'current.csv'
        current.write_bytes(b'edited')
        with self.assertRaisesRegex(ValueError, '不一致'):
            self.commit(self.second, 'second')
        self.assertEqual(current.read_bytes(), b'edited')

    def test_excluded_record_cannot_enter_the_baseline(self):
        snapshot = [{'name': '甲', 'quantity': '1'}, {'name': '乙', 'quantity': '3', 'invalid': True}]
        with self.assertRaisesRegex(ValueError, '排除'):
            self.commit(snapshot, 'first')
        self.assertFalse((self.path / 'baseline.csv').exists())

    def test_change_csv_records_both_capture_times_and_retries_are_stable(self):
        first_time, second_time = '2026-11-14T08:00:00+08:00', '2026-11-15T09:30:00+08:00'
        first_start, second_start = '2026-11-14T07:55:00+08:00', '2026-11-15T09:25:00+08:00'
        self.store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True, observed_at=first_time, started_at=first_start)
        self.store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True, observed_at=second_time, started_at=second_start)
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            record = list(csv.DictReader(stream))[0]
        self.assertEqual((record['起始时间'], record['结束时间']), (first_time, second_time))
        state = self.store.read()
        self.assertEqual((state['observation_starts']['first'], state['observation_starts']['second']), (first_start, second_start))
        self.store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True)
        with self.assertRaisesRegex(ValueError, '不同数据'):
            self.store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                              observed_at='2026-11-15T10:00:00+08:00', started_at='2026-11-15T10:00:00+08:00')

    def test_invalid_or_earlier_capture_time_does_not_change_files(self):
        self.store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                          observed_at='2026-11-15T09:00:00+08:00', started_at='2026-11-15T09:00:00+08:00')
        before = (self.path / 'changes.csv').read_bytes()
        for value in (None, '2026-11-15T08:59:00+08:00', '2026-11-15T10:00:00', 'bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                                  observed_at=value, started_at=value)
        self.assertEqual((self.path / 'changes.csv').read_bytes(), before)

    def test_other_capture_scope_cannot_overwrite_or_change_existing_baseline(self):
        self.commit(self.first, 'first')
        before = {name: (self.path / name).read_bytes()
                  for name in ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json')}
        with self.assertRaisesRegex(ValueError, '范围'):
            self.store.commit(self.second, 'second', scope='another-category', reviewed=True, complete=True,
                              order_verified=True, started_at='2026-11-15T09:25:00+08:00',
                              observed_at='2026-11-15T09:30:00+08:00')
        self.assertEqual({name: (self.path / name).read_bytes() for name in before}, before)
        self.assertEqual(self.store.read()['scope'], 'ordinary-items')

    def test_reviewed_synthetic_automatic_capture_uses_real_recorded_interval(self):
        source = self.path / 'synthetic-capture'
        source.mkdir()
        collector = BagCollector(Mock(), root=source, pause=lambda *_: None)
        collector._assert_bag = Mock()
        collector._capture = Mock(return_value=(Path('fixture.png'), {}))
        collector._move = Mock(side_effect=[(Path('top.png'), 0, True), (Path('bottom.png'), 0, True)])
        collector._record = Mock(return_value=Path('recorded.png'))
        collector.run(Mock())
        collector.inventory.add('样例道具', '3')
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as target:
            store = CsvSampleStore(target)
            result = store.commit_reviewed_capture(collector.inventory, 'synthetic-round', confirmed=True)
            self.assertEqual(result['scope'], 'ordinary-items')
            self.assertEqual(result['observation_starts']['synthetic-round'], collector.status['capture_started_at'])
            self.assertEqual(result['observation_times']['synthetic-round'], collector.status['capture_ended_at'])
            self.assertEqual(result['baseline'], [{'name': '样例道具', 'quantity': '3'}])

    def test_unreviewed_incomplete_or_untimed_capture_cannot_enter_sample_store(self):
        source = self.path / 'source'
        inv = ManualInventory(source)
        inv.capture_mode = 'automatic'
        inv.add('样例', '1')
        progress = inv.directory / 'progress.json'
        progress.write_text('{"phase":"review","capture_complete":true}', encoding='utf-8')
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as target:
            store = CsvSampleStore(target)
            with self.assertRaisesRegex(ValueError, '核对'):
                store.commit_reviewed_capture(inv, 'first', confirmed=False)
            inv.ocr_reports['sample'] = {'status': 'pending'}
            with self.assertRaisesRegex(ValueError, '核对'):
                store.commit_reviewed_capture(inv, 'first', confirmed=True)
            inv.ocr_reports.clear()
            with self.assertRaisesRegex(ValueError, '时间'):
                store.commit_reviewed_capture(inv, 'first', confirmed=True)
            progress.write_text('{"phase":"stopped","capture_complete":false}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '尚未完整'):
                store.commit_reviewed_capture(inv, 'first', confirmed=True)
            self.assertFalse((Path(target) / 'baseline.csv').exists())

    def test_adapter_refuses_a_non_sample_inventory_before_reading_it(self):
        inventory = object.__new__(ManualInventory)
        inventory.root = ROOT
        inventory.directory = ROOT / 'runtime/manual-inventory/step56'
        with self.assertRaisesRegex(ValueError, '临时目录'):
            self.store.commit_reviewed_capture(inventory, 'first', confirmed=True)
        self.assertFalse((self.path / 'baseline.csv').exists())

    def test_capture_interval_requires_real_start_and_consistent_order(self):
        with self.assertRaisesRegex(ValueError, '开始时间'):
            self.store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                              observed_at='2026-11-14T08:00:00+08:00')
        with self.assertRaisesRegex(ValueError, '晚于'):
            self.store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                              started_at='2026-11-14T08:01:00+08:00', observed_at='2026-11-14T08:00:00+08:00')
        self.assertFalse((self.path / 'baseline.csv').exists())

    def test_existing_manual_csv_exports_roundtrip_through_sample_store(self):
        sources = []
        for name, snapshot in [('one', self.first), ('two', self.second)]:
            inventory = ManualInventory(self.path / name)
            for row in snapshot:
                inventory.add(row['name'], row['quantity'])
            inventory.finish(True)
            sources.append((inventory.output, inventory.output.read_bytes()))
        with tempfile.TemporaryDirectory(prefix='isolated-csv-store-', dir=ROOT / '.cache/tmp') as directory:
            store = CsvSampleStore(directory)
            for (source, _), identifier in zip(sources, ['one', 'two']):
                with source.open(encoding='utf-8-sig', newline='') as stream:
                    timestamp = '2026-11-14T08:00:00+08:00' if identifier == 'one' else '2026-11-15T09:30:00+08:00'
                    store.commit(read_inventory_csv(stream), identifier, scope='ordinary-items', reviewed=True, complete=True,
                                 order_verified=True, observed_at=timestamp, started_at=timestamp)
            state = CsvSampleStore(directory).read()
            self.assertEqual([(c['name'], c['delta']) for c in state['changes']], [('甲', 2), ('乙', -4)])
        self.assertTrue(all(path.read_bytes() == original for path, original in sources))

    def test_legacy_csv_in_sample_directory_is_never_overwritten(self):
        for name in ('背包道具统计.csv', 'inventory.csv'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as directory:
                legacy = Path(directory) / name
                original = b'legacy inventory'
                legacy.write_bytes(original)
                store = CsvSampleStore(directory)
                with self.assertRaisesRegex(ValueError, '请先核对并决定是否作为基线'):
                    store.commit(self.first, 'first', scope='ordinary-items', reviewed=True, complete=True,
                                 order_verified=True, started_at='2026-11-14T07:55:00+08:00',
                                 observed_at='2026-11-14T08:00:00+08:00')
                self.assertEqual(legacy.read_bytes(), original)
                self.assertFalse((Path(directory) / 'baseline.csv').exists())

    def test_two_legacy_names_are_both_preserved_without_choosing_one(self):
        files = {name: self.path / name for name in ('背包道具统计.csv', 'inventory.csv')}
        originals = {'背包道具统计.csv': b'old chinese', 'inventory.csv': b'old english'}
        for name, path in files.items():
            path.write_bytes(originals[name])
        with self.assertRaisesRegex(ValueError, '请先核对并决定是否作为基线'):
            self.commit(self.first, 'first')
        self.assertEqual({name: path.read_bytes() for name, path in files.items()}, originals)
        self.assertFalse((self.path / 'state.json').exists())

    def test_legacy_file_appearing_during_first_recovery_stops_before_baseline(self):
        actual = os.replace
        def interrupt(source, target):
            if Path(target).name == 'baseline.csv':
                raise PermissionError('模拟中断')
            return actual(source, target)
        with patch('app.inventory_csv_sample.os.replace', side_effect=interrupt):
            with self.assertRaises(PermissionError):
                self.commit(self.first, 'first')
        legacy = self.path / 'inventory.csv'
        legacy.write_bytes(b'legacy data')
        with self.assertRaisesRegex(ValueError, '请先核对并决定是否作为基线'):
            self.store.read()
        self.assertEqual(legacy.read_bytes(), b'legacy data')
        self.assertFalse((self.path / 'baseline.csv').exists())
        self.assertTrue((self.path / 'transaction.json').exists())

    def test_unseen_boundary_keeps_last_quantity_with_explicit_old_time(self):
        self.commit(self.first, 'first')
        self.commit(rows(('乙', '5'), ('丙', '3')), 'second')
        with (self.path / 'current.csv').open(encoding='utf-8-sig', newline='') as stream:
            current = {row['道具名称']: row for row in csv.DictReader(stream)}
        with (self.path / 'inventory-status.csv').open(encoding='utf-8-sig', newline='') as stream:
            status = {row['道具名称']: row for row in csv.DictReader(stream)}
        self.assertEqual(current['甲']['数量'], '10')
        self.assertEqual(status['甲']['本次观察'], '否')
        self.assertEqual(status['甲']['上次观察时间'], '2026-11-14T08:00:00+08:00')

    def test_item_reappearing_after_unseen_round_records_only_interval_net(self):
        self.commit(self.first, 'first')
        self.store.commit(rows(('甲', '10'), ('丙', '3')), 'second', scope='ordinary-items', reviewed=True, complete=True,
                          order_verified=False, started_at='2026-11-15T09:00:00+08:00',
                          observed_at='2026-11-15T09:30:00+08:00')
        self.store.commit(rows(('甲', '10'), ('乙', '7'), ('丙', '3')), 'third', scope='ordinary-items', reviewed=True, complete=True,
                          order_verified=True, started_at='2026-11-16T09:00:00+08:00',
                          observed_at='2026-11-16T09:30:00+08:00')
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            changes = list(csv.DictReader(stream))
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]['道具名称'], changes[0]['净变化']), ('乙', '3'))
        self.assertEqual((changes[0]['起始时间'], changes[0]['结束时间']),
                         ('2026-11-14T08:00:00+08:00', '2026-11-16T09:30:00+08:00'))

    def test_incomplete_capture_cannot_update_existing_files(self):
        self.commit(self.first, 'first')
        names = ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json')
        before = {name: (self.path / name).read_bytes() for name in names}
        with self.assertRaisesRegex(ValueError, '尚未完整'):
            self.store.commit(self.second, 'second', scope='ordinary-items', reviewed=True, complete=False,
                              order_verified=True, started_at='2026-11-15T09:00:00+08:00',
                              observed_at='2026-11-15T09:30:00+08:00')
        self.assertEqual({name: (self.path / name).read_bytes() for name in names}, before)

    def test_item_reappearing_after_inferred_zero_preserves_that_provenance(self):
        self.commit(self.first, 'first')
        self.commit(self.second, 'second')
        self.store.commit(rows(('甲', '12'), ('乙', '7'), ('丙', '3')), 'third', scope='ordinary-items', reviewed=True, complete=True,
                          order_verified=True, started_at='2026-11-16T09:00:00+08:00',
                          observed_at='2026-11-16T09:30:00+08:00')
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            changes = list(csv.DictReader(stream))
        last = changes[-1]
        self.assertEqual((last['道具名称'], last['净变化'], last['方式']), ('乙', '7', '从推断值计算的净变化'))
        self.assertEqual((last['起始时间'], last['结束时间'], last['左侧参照'], last['右侧参照']),
                         ('2026-11-15T09:30:00+08:00', '2026-11-16T09:30:00+08:00', '甲', '丙'))

    def test_approximate_displays_are_recorded_without_numeric_delta(self):
        self.commit(rows(('甲', '1'), ('乙', '1.2万'), ('丙', '2')), 'first')
        self.commit(rows(('甲', '1'), ('丙', '2')), 'second')
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            change = list(csv.DictReader(stream))[0]
        self.assertEqual((change['道具名称'], change['原显示数量'], change['新显示数量'], change['净变化']),
                         ('乙', '1.2万', '0', ''))
        self.assertEqual(change['方式'], '推断耗尽，数量差不确定')

    def test_later_exact_detail_does_not_invent_change_from_rounded_display(self):
        self.commit(rows(('甲', '1.2万')), 'first')
        self.commit(rows(('甲', '12345')), 'second')
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            change = list(csv.DictReader(stream))[0]
        self.assertEqual((change['原显示数量'], change['新显示数量'], change['净变化']), ('1.2万', '12345', ''))
        self.assertEqual(change['方式'], '显示变化，数量差不确定')

    def test_order_uncertainty_persists_in_status_csv_until_reobserved(self):
        rounds = [rows(('甲', '1'), ('乙', '4'), ('丁', '3')),
                  rows(('甲', '1'), ('丙', '2'), ('丁', '3')),
                  rows(('甲', '1'), ('丁', '3')),
                  rows(('甲', '1'), ('丙', '2'), ('乙', '4'), ('丁', '3'))]
        for i, snapshot in enumerate(rounds):
            stamp = f'2026-11-{i+11:02}T09:00:00+08:00'
            self.store.commit(snapshot, f'day-{i}', scope='ordinary-items', reviewed=True, complete=True,
                              order_verified=True, started_at=stamp, observed_at=stamp)
            with (self.path / 'inventory-status.csv').open(encoding='utf-8-sig', newline='') as stream:
                status = {row['道具名称']: row['顺序待核对'] for row in csv.DictReader(stream)}
            if i in (1, 2):
                self.assertEqual((status['乙'], status['丙']), ('是', '是'))
            if i == 3:
                self.assertEqual((status['乙'], status['丙']), ('否', '否'))

    def test_many_rounds_match_independent_count_model(self):
        rng = random.Random(7281)
        quantities = {f'道具{i:02}': 100 for i in range(20)}
        baseline = dict(quantities)
        expected = []
        start = datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=8)))
        for day in range(61):
            if day:
                previous = dict(quantities)
                for name in rng.sample(list(quantities), 5):
                    quantities[name] += rng.choice([-3, -1, 1, 4])
                expected.extend((name, quantities[name] - previous[name]) for name in quantities
                                if quantities[name] != previous[name])
            snapshot = rows(*((name, str(value)) for name, value in quantities.items()))
            observed = (start + timedelta(days=day)).isoformat()
            self.store.commit(snapshot, f'day-{day}', scope='ordinary-items', reviewed=True, complete=True, order_verified=True,
                              started_at=observed, observed_at=observed)
        result = CsvSampleStore(self.path).read()
        self.assertEqual({r['name']: int(r['quantity']) for r in result['baseline']}, baseline)
        self.assertEqual({r['name']: int(r['quantity']) for r in result['current']}, quantities)
        self.assertEqual([(r['name'], r['delta']) for r in result['changes']], expected)
        with (self.path / 'changes.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), len(expected))

    def test_many_rounds_with_repeated_interruptions_do_not_duplicate_changes(self):
        import app.inventory_csv_sample as module
        rng = random.Random(1411)
        quantities = {f'道具{i:02}': 100 for i in range(12)}
        start = datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=8)))
        expected = []
        for day in range(31):
            if day:
                previous = dict(quantities)
                for name in rng.sample(list(quantities), 3):
                    quantities[name] += rng.choice([-1, 1, 2])
                expected.extend((name, quantities[name] - previous[name]) for name in quantities
                                if quantities[name] != previous[name])
            snapshot = rows(*((name, str(value)) for name, value in quantities.items()))
            observed = (start + timedelta(days=day)).isoformat()
            flags = dict(scope='ordinary-items', reviewed=True, complete=True, order_verified=True, started_at=observed, observed_at=observed)
            if day and day % 3 == 0:
                original = module._atomic_replace
                target = ('current.csv', 'inventory-status.csv', 'state.json')[(day // 3 - 1) % 3]
                def fail_once(directory, path, data):
                    if path.name == target:
                        raise PermissionError('模拟中断')
                    return original(directory, path, data)
                with patch('app.inventory_csv_sample._atomic_replace', side_effect=fail_once):
                    with self.assertRaises(PermissionError):
                        self.store.commit(snapshot, f'day-{day}', **flags)
                recovered = CsvSampleStore(self.path).read()
                self.assertEqual(recovered['observations'][-1], f'day-{day}')
            self.store.commit(snapshot, f'day-{day}', **flags)
        result = self.store.read()
        self.assertEqual([(r['name'], r['delta']) for r in result['changes']], expected)

    def test_real_second_process_cannot_write_during_active_transaction(self):
        self.commit(self.first, 'first')
        signal = self.path / 'worker-ready'
        script = '''
import sys, time
from pathlib import Path
from app.inventory_csv_sample import CsvSampleStore
root = Path(sys.argv[1])
with CsvSampleStore(root)._locked():
    (root / 'worker-ready').write_text('ready')
    time.sleep(3)
'''
        process = subprocess.Popen([sys.executable, '-c', script, str(self.path)], cwd=ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while not signal.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(signal.exists())
            with self.assertRaisesRegex(ValueError, '写入任务'):
                self.commit(self.second, 'second')
        finally:
            process.terminate()
            process.communicate(timeout=10)
        self.assertEqual(self.store.read()['observations'], ['first'])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing behavior')
    def test_windows_exclusive_file_handle_keeps_transaction_recoverable(self):
        import ctypes
        from ctypes import wintypes
        import app.inventory_csv_sample as module
        self.commit(self.first, 'first')
        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = ctypes.windll.kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = []
        original = module._atomic_replace
        def lock_during_update(directory, target, data):
            if target.name == 'current.csv':
                value = create(str(target), 0x80000000, 0, None, 3, 0x80, None)
                self.assertNotEqual(value, ctypes.c_void_p(-1).value)
                handle.append(value)
            return original(directory, target, data)
        try:
            with patch('app.inventory_csv_sample._atomic_replace', side_effect=lock_during_update):
                with self.assertRaises(PermissionError):
                    self.commit(self.second, 'second')
            self.assertTrue((self.path / 'transaction.json').exists())
        finally:
            for value in handle:
                close(value)
        self.assertEqual(self.store.read()['observations'], ['first', 'second'])


if __name__ == '__main__':
    unittest.main()
