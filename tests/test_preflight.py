import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT
from app.preflight import check_local_readiness
from app.bridge import Bridge


class LocalReadinessTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.adb = self.root / 'adb.exe'
        self.adb.write_bytes(b'not executable: local check must never launch this')
        self.model = self.root / 'assets/ocr/zh_cn'
        self.model.mkdir(parents=True)

    def test_file_presence_does_not_claim_device_or_ocr_success(self):
        for name in ('det.onnx', 'rec.onnx', 'keys.txt'):
            (self.model / name).write_bytes(b'not a valid model')
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            result = check_local_readiness(str(self.adb), '127.0.0.1:12345', root=self.root)
        self.assertTrue(result['ok'])
        self.assertTrue(all(row['status'] == 'checked' for row in result['checks']))
        self.assertIn('尚未验证连接', result['checks'][0]['message'])
        self.assertIn('待验证', result['checks'][1]['message'])

    def test_missing_empty_and_directory_models_are_reported(self):
        (self.model / 'det.onnx').write_bytes(b'')
        (self.model / 'rec.onnx').mkdir()
        result = check_local_readiness(str(self.adb), '127.0.0.1:12345', root=self.root)
        self.assertEqual(result['checks'][1]['status'], 'missing')
        for name in ('det.onnx', 'rec.onnx', 'keys.txt'):
            self.assertIn(name, result['checks'][1]['message'])

    def test_invalid_configuration_is_reported_without_launching(self):
        for adb, address in (('', ''), (str(self.adb), '127.0.0.1:70000'),
                             (str(self.adb), 'remote-host:12345')):
            with self.subTest(address=address), patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
                result = check_local_readiness(adb, address, root=self.root)
                self.assertEqual(result['checks'][0]['status'], 'missing')

    def test_bridge_check_preserves_stopped_state_and_never_dispatches(self):
        bridge = Bridge(offline=True)
        self.addCleanup(bridge.shutdown)
        bridge.stop()
        before = bridge.get_state()
        with patch.object(bridge._worker, 'submit', side_effect=AssertionError('must not dispatch')):
            result = bridge.check_readiness('', '')
        self.assertTrue(result['ok'])
        after = bridge.get_state()
        for key in ('status', 'stopped', 'busy', 'frame', 'settings'):
            self.assertEqual(before[key], after[key])
