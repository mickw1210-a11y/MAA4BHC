import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from app.device import MaaDevice


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
