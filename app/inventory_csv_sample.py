"""Temporary-only CSV transaction experiment, not a production store."""
import base64
from contextlib import contextmanager
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid

from .config import ROOT
from .inventory import ManualInventory
from .inventory_rehearsal import advance_rehearsal

NAMES = ('baseline.csv', 'current.csv', 'inventory-status.csv', 'changes.csv', 'state.json')
FORMAT_VERSION = 1
CHANGE_LABELS = {'changed': '净变化', 'inferred_depleted': '按顺序推断耗尽',
                 'changed_after_gap': '间隔净变化', 'changed_after_inference': '从推断值计算的净变化',
                 'changed_unknown_amount': '显示变化，数量差不确定',
                 'inferred_depleted_unknown_amount': '推断耗尽，数量差不确定',
                 'changed_after_gap_unknown_amount': '间隔显示变化，数量差不确定',
                 'changed_after_inference_unknown_amount': '从推断值变化，数量差不确定'}


def _csv(header, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\r\n')
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


def _sample_files(state):
    content = {'baseline.csv': _csv(['道具名称', '数量'],
                                    ((row['name'], row['quantity']) for row in state['baseline'])),
               'state.json': json.dumps(state, ensure_ascii=False, sort_keys=True).encode('utf-8')}
    content['current.csv'] = _csv(['道具名称', '数量'],
                                  ((row['name'], row['quantity']) for row in state['current']))
    times = state['observation_times']
    content['inventory-status.csv'] = _csv(['道具名称', '本次观察', '上次观察轮次', '上次观察时间', '推断耗尽',
                                           '推断轮次', '推断时间', '左侧参照', '右侧参照', '顺序待核对'],
                                         ((row['name'], '是' if row['observed'] else '否', row['last_seen'], times[row['last_seen']],
                                           '是' if row['inferred'] else '否', row.get('inferred_at', ''),
                                           times.get(row.get('inferred_at', ''), ''),
                                           row.get('inference_neighbors', {}).get('left', ''),
                                           row.get('inference_neighbors', {}).get('right', ''),
                                           '是' if row['order_uncertain'] else '否')
                                          for row in state['current']))
    content['changes.csv'] = _csv(['道具名称', '净变化', '原显示数量', '新显示数量', '起始轮次', '起始时间', '结束轮次', '结束时间',
                                  '方式', '左侧参照', '右侧参照'],
                                 ((row['name'], row['delta'], row['previous_display'], row['current_display'],
                                   row['from_observation'], times[row['from_observation']],
                                   row['to_observation'], times[row['to_observation']], CHANGE_LABELS[row['status']],
                                   (row['inference_neighbors'] or {}).get('left', ''),
                                   (row['inference_neighbors'] or {}).get('right', ''))
                                  for row in state['changes']))
    return content


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _legacy_exists(directory):
    return any((directory / name).exists() or (directory / name).is_symlink()
               for name in ('inventory.csv', '背包道具统计.csv'))


def _write_new(path, data):
    with path.open('xb') as stream:
        if stream.write(data) != len(data):
            raise OSError('样例文件未完整写入')
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_replace(directory, destination, data):
    temporary = directory / ('.stage-' + uuid.uuid4().hex)
    _write_new(temporary, data)
    os.replace(temporary, destination)


def _validate_existing(name, old_hash, old_length, new, existing):
    if name == 'changes.csv':
        if old_hash is not None and existing is None:
            raise ValueError('原变化记录缺失，停止恢复')
        base = old_length or 0
        if existing is not None and (len(existing) < base or
                (old_hash is not None and _hash(existing[:base]) != old_hash) or
                not new.startswith(existing[base:])):
            raise ValueError('变化记录已被修改，停止恢复')
    elif existing is None:
        if old_hash is not None:
            raise ValueError('样例文件已被修改，停止恢复')
    elif _hash(existing) not in (old_hash, _hash(new)):
        raise ValueError('样例文件已被修改，停止恢复')


class CsvSampleStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir() or not self.directory.is_relative_to((ROOT / '.cache/tmp').resolve()):
            raise ValueError('样例目录必须位于项目临时目录')

    @contextmanager
    def _locked(self):
        lock_path = self.directory / '.csv-lock'
        if lock_path.is_symlink():
            raise ValueError('锁文件不能是链接')
        with lock_path.open('a+b') as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b'0'); lock.flush()
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError('已有写入任务，已停止') from error
            try:
                yield
            finally:
                if os.name == 'nt':
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _path(self, name):
        path = self.directory / name
        if path.is_symlink():
            raise ValueError('样例数据文件不能是链接')
        return path

    def _load(self):
        marker = self._path('.csv-sample')
        state_path = self._path('state.json')
        if not state_path.exists():
            if _legacy_exists(self.directory):
                raise ValueError('发现旧库存 CSV；请先核对并决定是否作为基线，原文件已保留')
            permitted = {'.csv-lock', '.csv-sample'}
            if any(path.name not in permitted for path in self.directory.iterdir()):
                raise ValueError('发现未知或未完成文件，不能建立新基线')
            return None
        if not marker.is_file():
            raise ValueError('样例标识缺失')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if not isinstance(state, dict) or type(state.get('format_version')) is not int or state['format_version'] != FORMAT_VERSION:
            raise ValueError('样例数据版本不支持，已保留原文件')
        expected = _sample_files(state)
        if any(not self._path(name).is_file() or self._path(name).read_bytes() != expected[name] for name in NAMES):
            raise ValueError('样例文件损坏或不一致，已停止')
        return state

    def _recover(self):
        journal_path = self._path('transaction.json')
        if not journal_path.exists():
            return
        if not self._path('state.json').exists() and _legacy_exists(self.directory):
            raise ValueError('发现旧库存 CSV；请先核对并决定是否作为基线，原文件已保留')
        envelope = json.loads(journal_path.read_text(encoding='utf-8'))
        if not isinstance(envelope, dict) or type(envelope.get('format_version')) is not int or envelope['format_version'] != FORMAT_VERSION:
            raise ValueError('恢复记录版本不支持，已保留原文件')
        payload = envelope['payload'].encode('utf-8')
        if _hash(payload) != envelope['sha256']:
            raise ValueError('恢复记录校验失败')
        transaction = json.loads(payload)
        if set(transaction) != set(NAMES):
            raise ValueError('恢复记录格式无效')
        # Preflight every file before changing any: no foreign modification is
        # overwritten and a partially appended CSV must match the intended bytes.
        decoded = {}
        for name in NAMES:
            part = transaction[name]
            new = base64.b64decode(part['new'], validate=True)
            old_hash, old_length = part['old_hash'], part['old_length']
            if ((old_hash is None) != (old_length is None) or
                    (old_length is not None and (type(old_length) is not int or old_length < 0))):
                raise ValueError('恢复记录格式无效')
            existing = self._path(name).read_bytes() if self._path(name).exists() else None
            _validate_existing(name, old_hash, old_length, new, existing)
            decoded[name] = (old_hash, old_length, new)
        for name in NAMES:
            old_hash, old_length, new = decoded[name]
            target = self._path(name)
            existing = target.read_bytes() if target.exists() else None
            _validate_existing(name, old_hash, old_length, new, existing)
            if name == 'changes.csv':
                offset = len(existing or b'') - (old_length or 0)
                if existing is not None and offset == len(new):
                    continue
                with target.open('ab' if existing is not None else 'xb') as stream:
                    remaining = new[offset:]
                    if stream.write(remaining) != len(remaining):
                        raise OSError('样例变化记录未完整写入')
                    stream.flush(); os.fsync(stream.fileno())
            else:
                if existing == new:
                    continue
                _atomic_replace(self.directory, target, new)
        self._load()
        journal_path.unlink()

    def read(self):
        with self._locked():
            self._recover()
            return self._load()

    def commit_reviewed_capture(self, inventory, observation_id, *, confirmed):
        """Connect a reviewed *synthetic* ordinary-tab capture to this sample."""
        if confirmed is not True:
            raise ValueError('请先确认已核对本轮记录')
        sample_root = (ROOT / '.cache/tmp').resolve()
        if (not isinstance(inventory, ManualInventory) or
                not inventory.root.resolve().is_relative_to(sample_root) or
                not inventory.directory.resolve().is_relative_to(inventory.root.resolve())):
            raise ValueError('演练只接受临时目录中的样例采集')
        if inventory.capture_mode != 'automatic':
            raise ValueError('该演练只接受普通道具自动采集样例')
        progress_path = inventory.directory / 'progress.json'
        if progress_path.is_symlink():
            raise ValueError('采集进度文件不能是链接')
        try:
            progress = json.loads(progress_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ValueError('无法读取采集进度，已停止') from error
        if progress.get('phase') != 'review' or progress.get('capture_complete') is not True:
            raise ValueError('本轮采集尚未完整，不能更新库存')
        if any(report.get('status') == 'pending' for report in inventory.ocr_reports.values()):
            raise ValueError('还有截图需要核对')
        rows = [{'name': row['name'], 'quantity': row['quantity']}
                for row in inventory.rows if not row.get('invalid')]
        # Recorded order is reviewed by the caller. No inference from real data
        # is enabled until a production integration establishes those checks.
        return self.commit(rows, observation_id, scope='ordinary-items', reviewed=True,
                           complete=True, order_verified=True,
                           started_at=progress.get('capture_started_at'),
                           observed_at=progress.get('capture_ended_at'))

    def commit(self, rows, observation_id, *, scope, reviewed, complete, order_verified, observed_at=None, started_at=None):
        with self._locked():
            self._recover()
            state = self._load()
            snapshot = list(rows)
            if not isinstance(scope, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', scope):
                raise ValueError('必须明确指定有效的采集范围')
            if state and state.get('scope') != scope:
                raise ValueError('采集范围与已有样例不同，已停止')
            if complete is not True:
                raise ValueError('本轮采集尚未完整，不能更新库存')
            if (not isinstance(observation_id, str) or not observation_id.strip()
                    or observation_id != observation_id.strip() or len(observation_id) > 100
                    or observation_id[0] in '=+-@' or any(c in observation_id for c in '\r\n\x00')):
                raise ValueError('轮次标识无效')
            for row in snapshot:
                if not isinstance(row, dict):
                    raise ValueError('道具记录格式无效')
                if row.get('invalid'):
                    raise ValueError('样例包含已排除的记录，请先筛选有效记录')
                ManualInventory._validate_fields(row.get('name', ''), row.get('quantity', ''))
            if observed_at is None:
                observed_at = (state['observation_times'].get(observation_id) if state else None)
                if observed_at is None:
                    raise ValueError('必须提供本轮实际采集结束时间')
            if started_at is None:
                started_at = (state['observation_starts'].get(observation_id) if state else None)
                if started_at is None:
                    raise ValueError('必须提供本轮实际采集开始时间')
            def parse_time(value):
                if not isinstance(value, str):
                    raise ValueError('采集时间无效')
                try:
                    parsed = datetime.fromisoformat(value)
                except ValueError as error:
                    raise ValueError('采集时间无效') from error
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError('采集时间必须包含时区')
                return parsed
            parsed_time, parsed_start = parse_time(observed_at), parse_time(started_at)
            if parsed_start > parsed_time:
                raise ValueError('采集开始时间晚于结束时间')
            request = {'rows': snapshot, 'scope': scope, 'reviewed': reviewed, 'complete': complete,
                       'order_verified': order_verified, 'observed_at': observed_at, 'started_at': started_at}
            digest = _hash(json.dumps(request, ensure_ascii=False, sort_keys=True).encode('utf-8'))
            if state and observation_id in state['requests']:
                if state['requests'][observation_id] != digest:
                    raise ValueError('同一轮标识对应不同数据，已停止')
                return state
            if state:
                previous_time = datetime.fromisoformat(state['observation_times'][state['observations'][-1]])
                if parsed_start < previous_time:
                    raise ValueError('采集开始时间早于上一轮结束，请先核对')
            new = advance_rehearsal(state, snapshot, observation_id, reviewed=reviewed,
                                    complete=complete, order_verified=order_verified)
            new['format_version'] = FORMAT_VERSION
            new['scope'] = scope
            new['requests'] = dict(state['requests']) if state else {}
            new['requests'][observation_id] = digest
            new['observation_times'] = dict(state['observation_times']) if state else {}
            new['observation_times'][observation_id] = observed_at
            new['observation_starts'] = dict(state['observation_starts']) if state else {}
            new['observation_starts'][observation_id] = started_at
            before = _sample_files(state) if state else {name: None for name in NAMES}
            after = _sample_files(new)
            if before['changes.csv'] is not None and not after['changes.csv'].startswith(before['changes.csv']):
                raise ValueError('变化记录不是追加，已停止')
            transaction = {}
            for name in NAMES:
                old = before[name]
                data = after[name][len(old):] if name == 'changes.csv' and old is not None else after[name]
                transaction[name] = {'old_hash': None if old is None else _hash(old),
                                     'old_length': None if old is None else len(old),
                                     'new': base64.b64encode(data).decode('ascii')}
            payload = json.dumps(transaction, sort_keys=True).encode('utf-8')
            envelope = json.dumps({'format_version': FORMAT_VERSION, 'payload': payload.decode('utf-8'),
                                   'sha256': _hash(payload)}).encode('utf-8')
            marker = self._path('.csv-sample')
            if not marker.exists():
                _write_new(marker, b'sample-only\n')
            _atomic_replace(self.directory, self._path('transaction.json'), envelope)
            self._recover()
            return new
