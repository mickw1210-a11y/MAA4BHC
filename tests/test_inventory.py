import base64
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app.inventory import ManualInventory
from app.bridge import Bridge
from app.config import ROOT


class ManualInventoryTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / '.cache/tmp'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inventory = ManualInventory(self.root)

    def image(self):
        stream = io.BytesIO()
        Image.new('RGB', (4, 8), 'white').save(stream, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()

    def test_order_exact_quantity_resume_and_completion_cleanup(self):
        self.inventory.import_image(self.image())
        self.inventory.add('道具乙', '1.2万')
        self.inventory.add('道具甲', '001')
        original = self.root / 'reference.png'
        original.write_bytes(b'keep')
        outside = self.inventory.images / 'untracked.png'
        outside.write_bytes(b'keep')
        resumed = ManualInventory(self.root)
        resumed.update(0, '道具乙', '2万')
        result = resumed.finish(True)
        self.assertEqual(result['phase'], 'completed')
        with resumed.output.open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(list(csv.reader(stream)), [['道具名称', '数量'], ['道具乙', '2万'], ['道具甲', '001']])
        self.assertEqual(original.read_bytes(), b'keep')
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertEqual(list(resumed.images.glob('[0-9a-f]' * 32 + '.png')), [])
        self.assertEqual(resumed.finish(True)['phase'], 'completed')

    def test_incomplete_or_existing_csv_preserves_images(self):
        self.inventory.import_image(self.image())
        self.inventory.add('道具', '10')
        with self.assertRaises(ValueError):
            self.inventory.finish(False)
        self.inventory.output.parent.mkdir(parents=True)
        self.inventory.output.write_text('existing', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.inventory.finish(True)
        self.assertEqual(len(list(self.inventory.images.glob('*.png'))), 1)
        self.assertEqual(self.inventory.output.read_text(), 'existing')

    def test_duplicate_and_bad_image_or_path_rejected(self):
        self.inventory.add('道具', '10')
        with self.assertRaises(ValueError):
            self.inventory.add('道具', '20')
        for name in ['../x.png', '/x.png', 'invalid.png']:
            with self.assertRaises(ValueError):
                self.inventory._image_path(name)
        with self.assertRaises(ValueError):
            self.inventory.import_image('bad image')
        self.assertEqual(len(self.inventory.rows), 1)

    def test_cleanup_failure_can_resume_without_overwriting_csv(self):
        self.inventory.import_image(self.image())
        self.inventory.add('道具', '10')
        actual = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.suffix == '.png':
                raise PermissionError('fixture locked')
            return actual(path, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            with self.assertRaises(PermissionError):
                self.inventory.finish(True)
        self.assertEqual(self.inventory.phase, 'exported')
        saved = self.inventory.output.read_bytes()
        resumed = ManualInventory(self.root)
        self.assertEqual(resumed.finish(True)['phase'], 'completed')
        self.assertEqual(saved, resumed.output.read_bytes())

    def test_manual_bridge_never_accesses_device(self):
        class ForbiddenDevice:
            def __getattr__(self, name):
                raise AssertionError('Device forbidden: ' + name)
        with patch('app.bridge.ManualInventory', return_value=self.inventory):
            bridge = Bridge(manual_inventory=True, device=ForbiddenDevice())
        self.addCleanup(bridge.shutdown)
        self.assertFalse(bridge.connect('', '')['ok'])
        self.assertFalse(bridge.screenshot()['ok'])
        self.assertFalse(bridge.click(1, 1)['ok'])
        self.assertFalse(bridge.swipe(1, 1, 2, 2, 300)['ok'])
        self.assertTrue(bridge.inventory_action('add', '道具', '10')['ok'])
        self.assertEqual(bridge.get_state()['inventory']['rows'][0]['name'], '道具')
