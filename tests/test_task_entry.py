import unittest
from threading import Event
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from app.bridge import Bridge
from app.config import ROOT
from app.inventory import ManualInventory
from tests.test_worker import wait_idle


class InspectionDevice:
    def __init__(self):
        self.actions = []

    def connect(self, adb_path, address, token):
        token.check()
        self.actions.append('connect')

    def screenshot(self, token, *, save):
        token.check()
        self.actions.append(('screenshot', save))
        return {'frame_id': 'inspection', 'width': 450, 'height': 800,
                'time': 'fixture', 'data': 'fixture'}


class TaskEntryTests(unittest.TestCase):
    def bridge(self, device=None, **options):
        bridge = Bridge(device=device or InspectionDevice(), **options)
        self.addCleanup(bridge.shutdown)
        return bridge

    def test_inspection_connects_and_captures_in_one_submission(self):
        device = InspectionDevice()
        bridge = self.bridge(device, task_home=True)
        with patch('app.bridge.MaaDevice.validate_connection'):
            self.assertTrue(bridge.inspect_device('fixture-adb', 'fixture-address')['ok'])
        wait_idle(bridge._worker)
        state = bridge.get_state()
        self.assertEqual(device.actions, ['connect', ('screenshot', False)])
        self.assertTrue(state['task_home'])
        self.assertEqual(state['frame']['width'], 450)
        self.assertEqual(state['status'], 'connected')

    def test_connected_inspection_reuses_connection(self):
        device = InspectionDevice()
        bridge = self.bridge(device)
        bridge._status = 'connected'
        self.assertTrue(bridge.inspect_device()['ok'])
        wait_idle(bridge._worker)
        self.assertEqual(device.actions, [('screenshot', False)])

    def test_explicit_read_only_blocks_inventory_task_at_all_entry_points(self):
        with TemporaryDirectory(dir=ROOT / '.cache/tmp') as folder:
            inventory = ManualInventory(Path(folder))
            with patch('app.bridge.ManualInventory', return_value=inventory):
                bridge = self.bridge(read_only=True, inventory_capture=True, task_home=True)
            bridge._status = 'connected'
            bridge._frame = {'width': 450, 'height': 800, 'frame_id': 'fixture'}
            with patch.object(bridge._worker, 'submit', side_effect=AssertionError('must not dispatch')):
                self.assertFalse(bridge.auto_inventory()['ok'])
                self.assertFalse(bridge.click(1, 1)['ok'])
                self.assertFalse(bridge.swipe(1, 1, 2, 2, 300)['ok'])
            self.assertFalse(bridge.get_state()['inventory_automation'])

    def test_explicit_read_only_disables_device_swipe_backend(self):
        with TemporaryDirectory(dir=ROOT / '.cache/tmp') as folder:
            with patch('app.bridge.ManualInventory', return_value=ManualInventory(Path(folder))), patch('app.bridge.MaaDevice') as factory:
                bridge = Bridge(read_only=True, inventory_capture=True)
                self.addCleanup(bridge.shutdown)
            self.assertTrue(factory.call_args.kwargs['read_only'])
            self.assertFalse(factory.call_args.kwargs['allow_inventory_swipe'])

    def test_changed_target_reconnects_and_records_only_successful_settings(self):
        device = InspectionDevice()
        bridge = self.bridge(device)
        bridge._status = 'connected'
        bridge._settings = {'adb_path': 'old-adb', 'address': 'old-address'}
        with patch('app.bridge.MaaDevice.validate_connection'):
            self.assertTrue(bridge.inspect_device('new-adb', 'new-address')['ok'])
        wait_idle(bridge._worker)
        self.assertEqual(device.actions, ['connect', ('screenshot', False)])
        self.assertEqual(bridge.get_state()['settings'], {'adb_path': 'new-adb', 'address': 'new-address'})
        device.actions.clear()
        self.assertTrue(bridge.inspect_device('new-adb', 'new-address')['ok'])
        wait_idle(bridge._worker)
        self.assertEqual(device.actions, [('screenshot', False)])

    def test_offline_and_invalid_configuration_do_not_dispatch(self):
        for offline in (True, False):
            with self.subTest(offline=offline):
                device = InspectionDevice()
                bridge = self.bridge(device, offline=offline)
                self.assertFalse(bridge.inspect_device('', '')['ok'])
                self.assertEqual(device.actions, [])

    def test_stop_during_connection_prevents_screenshot(self):
        started, release = Event(), Event()

        class DelayedDevice(InspectionDevice):
            def connect(self, *args):
                self.actions.append('connect')
                started.set()
                if not release.wait(3):
                    raise RuntimeError('fixture timeout')

        device = DelayedDevice()
        bridge = self.bridge(device)
        with patch('app.bridge.MaaDevice.validate_connection'):
            self.assertTrue(bridge.inspect_device('fixture-adb', 'fixture-address')['ok'])
        try:
            self.assertTrue(started.wait(3))
            bridge.stop()
        finally:
            release.set()
        wait_idle(bridge._worker)
        self.assertEqual(device.actions, ['connect'])
        self.assertEqual(bridge.get_state()['status'], 'stopped')
        self.assertIsNone(bridge.get_state()['frame'])

    def test_failed_connection_does_not_capture_or_claim_completion(self):
        device = InspectionDevice()
        bridge = self.bridge(device)
        with patch('app.bridge.MaaDevice.validate_connection'), patch.object(device, 'connect', side_effect=RuntimeError('fixture failed')):
            with self.assertLogs('m4b', level='ERROR'):
                self.assertTrue(bridge.inspect_device('fixture-adb', 'fixture-address')['ok'])
                wait_idle(bridge._worker)
        self.assertEqual(device.actions, [])
        self.assertEqual(bridge.get_state()['status'], 'error')
        self.assertIsNone(bridge.get_state()['frame'])
