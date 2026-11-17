import unittest
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from app.device import MaaDevice


class AdbConnectionTests(unittest.TestCase):
    class Token:
        def check(self): pass
        def dispatch(self, action): return action()

    def test_success_requires_adb_to_report_target_connected(self):
        address = '127.0.0.1:12345'
        for message in (f'connected to {address}', f'already connected to {address}'):
            process = Mock(returncode=0)
            process.communicate.return_value = (message.encode(), b'')
            with patch('app.device.subprocess.Popen', return_value=process) as launch:
                MaaDevice._connect_adb(Path('adb.exe'), address, self.Token())
            self.assertEqual(launch.call_args.args[0], ['adb.exe', 'connect', address])

    def test_failed_or_ambiguous_output_does_not_proceed(self):
        for code, output in ((0, b'failed to connect'), (1, b'connected to 127.0.0.1:12345'),
                             (0, b'connected to 127.0.0.1:9999')):
            process = Mock(returncode=code)
            process.communicate.return_value = (output, b'')
            with patch('app.device.subprocess.Popen', return_value=process):
                with self.assertRaises(RuntimeError):
                    MaaDevice._connect_adb(Path('adb.exe'), '127.0.0.1:12345', self.Token())

    def test_timeout_kills_and_drains_process(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('adb', 8), (b'', b'')]
        with patch('app.device.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, '超时'):
                MaaDevice._connect_adb(Path('adb.exe'), '127.0.0.1:12345', self.Token())
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    def test_stop_after_connection_prevents_followup(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (b'connected to 127.0.0.1:12345', b'')
        token = self.Token()
        token.check = Mock(side_effect=RuntimeError('stopped'))
        with patch('app.device.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'stopped'):
                MaaDevice._connect_adb(Path('adb.exe'), '127.0.0.1:12345', token)


class DisplaySelectionTests(unittest.TestCase):
    windows = """Display: mDisplayId=0 (organized)
 mCurrentFocus=null
 mFocusedApp=app.lawnchair/.Launcher
Display: mDisplayId=2 (organized)
 mCurrentFocus=Window{u0 com.tomato.android.ssbhc/org.cocos2dx.javascript.AppActivity}
Display: mDisplayId=3 (organized)
 mCurrentFocus=null
"""
    displays = """DisplayViewport{type=INTERNAL, displayId=0, uniqueId='local:100', physicalPort=0}
DisplayViewport{type=INTERNAL, displayId=2, uniqueId='local:200', physicalPort=1}
DisplayViewport{type=INTERNAL, displayId=3, uniqueId='local:300', physicalPort=2}"""

    def test_logical_game_screen_maps_to_physical_id(self):
        self.assertEqual(MaaDevice._select_game_display(self.windows, self.displays), ('2', '200'))

    def test_missing_or_ambiguous_game_stops(self):
        for windows in [self.windows.replace('com.tomato.android.ssbhc/', 'other/'),
                        self.windows + self.windows]:
            with self.assertRaises(RuntimeError):
                MaaDevice._select_game_display(windows, self.displays)

    def test_missing_or_ambiguous_mapping_stops(self):
        for displays in ['', self.displays + "DisplayViewport{displayId=2, uniqueId='local:999'}"]:
            with self.assertRaises(RuntimeError):
                MaaDevice._select_game_display(self.windows, displays)


class InventorySwipeTests(unittest.TestCase):
    class Token:
        def check(self): pass
        def dispatch(self, action): return action()

    def device(self, enabled=True):
        device = MaaDevice(read_only=True, allow_inventory_swipe=enabled)
        device._controller = Mock(connected=True)
        device._capture_target = (Path('fixture-adb.exe'), '127.0.0.1:16544', {'fixture': True})
        device._last_size = (630, 1120)
        return device

    def test_bag_swipe_targets_logical_game_display_and_never_enables_click(self):
        device = self.device()
        process = Mock(returncode=0)
        process.communicate.return_value = (b'', b'')
        with patch.object(MaaDevice, '_screen_info', return_value=('2', {'fixture': True})), patch('app.device.subprocess.Popen', return_value=process) as launch:
            device.swipe_inventory('up', 100, self.Token())
        args = launch.call_args.args[0]
        self.assertEqual(args[-9:], ['touchscreen', '-d', '2', 'swipe', '590', '920', '590', '820', '1200'])
        with self.assertRaises(RuntimeError): device.click(1, 1, self.Token())

    def test_wrong_size_disabled_mode_and_display_change_send_no_input(self):
        for kind in ('disabled', 'size', 'display'):
            device = self.device(enabled=kind != 'disabled')
            if kind == 'size': device._last_size = (750, 1334)
            with patch.object(MaaDevice, '_screen_info', return_value=('2', {'changed': True})), patch('app.device.subprocess.Popen') as launch:
                with self.assertRaises(RuntimeError): device.swipe_inventory('up', 100, self.Token())
                launch.assert_not_called()

    def test_450_swipe_maps_reference_points_to_device_pixels(self):
        device = self.device()
        device._last_size = (450, 800)
        process = Mock(returncode=0)
        process.communicate.return_value = (b'', b'')
        with patch.object(MaaDevice, '_screen_info', return_value=('2', {'fixture': True})), patch('app.device.subprocess.Popen', return_value=process) as launch:
            device.swipe_inventory('up', 100, self.Token())
        self.assertEqual(launch.call_args.args[0][-9:],
                         ['touchscreen', '-d', '2', 'swipe', '421', '657', '421', '586', '1200'])
