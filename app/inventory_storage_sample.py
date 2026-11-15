"""Isolated CSV storage experiment; not connected to user inventory.

Only project-local temporary directories are accepted. Each generation is
immutable and a single pointer selects the committed set of files. This is an
experiment for review, not a finalized production data format.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import uuid

from .config import ROOT
from .inventory import ManualInventory
from .inventory_rehearsal import advance_rehearsal


def _csv(header, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\r\n')
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8-sig')


def _files(state):
    baseline = _csv(['道具名称', '数量'], ((r['name'], r['quantity']) for r in state['baseline']))
    current = _csv(['道具名称', '数量', '本次观察', '上次观察轮次', '推断耗尽', '顺序待核对'],
                   ((r['name'], r['quantity'], int(r['observed']), r['last_seen'],
                     int(r['inferred']), int(r['order_uncertain'])) for r in state['current']))
    changes = _csv(['道具名称', '净变化', '起始轮次', '结束轮次', '方式', '左侧参照', '右侧参照'],
                   ((r['name'], r['delta'], r['from_observation'], r['to_observation'], r['status'],
                     (r['inference_neighbors'] or {}).get('left', ''),
                     (r['inference_neighbors'] or {}).get('right', '')) for r in state['changes']))
    return {'baseline.csv': baseline, 'current.csv': current, 'changes.csv': changes,
            'state.json': json.dumps(state, ensure_ascii=False, sort_keys=True).encode('utf-8')}


def _write_exclusive(path, content):
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


class SampleStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        if not self.directory.is_relative_to((ROOT / '.cache/tmp').resolve()):
            raise ValueError('样例存储只能放在项目临时目录')
        if not self.directory.is_dir():
            raise ValueError('样例存储目录不存在')

    def _read(self):
        pointer = self.directory / 'HEAD'
        if pointer.is_symlink():
            raise ValueError('样例存储指针不能是链接')
        if not pointer.exists():
            if any(p.name not in {'.writer-lock', '.sample-store'} for p in self.directory.iterdir()):
                raise ValueError('存在未完成或未知文件，不能建立新基线')
            return None
        if not (self.directory / '.sample-store').is_file():
            raise ValueError('样例存储标识缺失')
        name = pointer.read_text(encoding='ascii').strip()
        if len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
            raise ValueError('样例存储指针无效')
        generation = self.directory / name
        if generation.is_symlink() or any((generation / key).is_symlink() for key in
                                           ('manifest.json', 'baseline.csv', 'current.csv', 'changes.csv', 'state.json')):
            raise ValueError('样例记录不能是链接')
        manifest = json.loads((generation / 'manifest.json').read_text(encoding='utf-8'))
        names = {'baseline.csv', 'current.csv', 'changes.csv', 'state.json'}
        if set(manifest) != names:
            raise ValueError('样例清单无效')
        content = {key: (generation / key).read_bytes() for key in names}
        if any(hashlib.sha256(content[key]).hexdigest() != manifest[key] for key in names):
            raise ValueError('样例记录校验失败')
        state = json.loads(content['state.json'].decode('utf-8'))
        if _files(state) != content:
            raise ValueError('样例记录与导出内容不一致')
        return state

    def read(self):
        return self._read()

    def commit(self, rows, observation_id, *, reviewed, complete, order_verified):
        # A stale lock intentionally blocks further writes; it is never guessed
        # away after a crash. This prototype has no automatic lock recovery.
        lock = self.directory / '.writer-lock'
        try:
            lock.mkdir()
        except FileExistsError as error:
            raise ValueError('已有写入任务或遗留锁，已停止') from error
        try:
            state = self._read()
            snapshot = list(rows)
            if (not isinstance(observation_id, str) or not observation_id.strip()
                    or observation_id != observation_id.strip()
                    or len(observation_id) > 100 or observation_id[0] in '=+-@'
                    or any(c in observation_id for c in '\r\n\x00')):
                raise ValueError('轮次标识无效')
            for row in snapshot:
                if not isinstance(row, dict):
                    raise ValueError('道具记录格式无效')
                ManualInventory._validate_fields(row.get('name', ''), row.get('quantity', ''))
            request = {'rows': snapshot, 'reviewed': reviewed, 'complete': complete,
                       'order_verified': order_verified}
            digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
            if state and observation_id in state['requests']:
                if state['requests'][observation_id] != digest:
                    raise ValueError('同一轮标识对应不同数据，已停止')
                return state
            new = advance_rehearsal(state, snapshot, observation_id, reviewed=reviewed,
                                    complete=complete, order_verified=order_verified)
            new['requests'] = dict(state['requests']) if state else {}
            new['requests'][observation_id] = digest
            marker = self.directory / '.sample-store'
            if not marker.exists():
                _write_exclusive(marker, b'sample-only\n')
            name = uuid.uuid4().hex
            generation = self.directory / name
            generation.mkdir()
            content = _files(new)
            for key, data in content.items():
                _write_exclusive(generation / key, data)
            manifest = {key: hashlib.sha256(data).hexdigest() for key, data in content.items()}
            _write_exclusive(generation / 'manifest.json', json.dumps(manifest, sort_keys=True).encode('utf-8'))
            staged = self.directory / ('.head-' + name)
            _write_exclusive(staged, name.encode('ascii'))
            os.replace(staged, self.directory / 'HEAD')
            return new
        finally:
            lock.rmdir()
