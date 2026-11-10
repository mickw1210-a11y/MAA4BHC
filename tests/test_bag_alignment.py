"""Synthetic row identities test alignment without touching a device."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.bag_alignment import SCROLL_ROI, estimate_vertical_shift
from app.config import ROOT


class BagAlignmentTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / '.cache/tmp'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Each icon has a unique texture, though its frame repeats every155px.
        self.content = Image.new('RGB', (584, 3600), (230, 222, 199))
        draw = ImageDraw.Draw(self.content)
        rng = np.random.default_rng(60)
        for row in range(23):
            for col in range(5):
                x, y = col * 116 + 12, row * 155 + 8
                draw.rounded_rectangle((x, y, x + 90, y + 118), radius=7, fill=(186, 160, 112))
                texture = rng.integers(25, 235, (14, 14, 3), dtype=np.uint8)
                icon = Image.fromarray(texture).resize((76, 76), Image.Resampling.NEAREST)
                self.content.paste(icon, (x + 7, y + 7))
                draw.text((x + 12, y + 92), f'{row}/{col}/{row * 5 + col}', fill=(28, 28, 28))

    def screen(self, offset, name, chrome=(255, 255, 255)):
        image = Image.new('RGB', (630, 1120), chrome)
        x, y, width, height = SCROLL_ROI
        image.paste(self.content.crop((0, offset, width, offset + height)), (x, y))
        path = self.root / name
        image.save(path)
        return path

    def test_620_upward_scroll_uses_icons_not_repeating_row_frames(self):
        result = estimate_vertical_shift(self.screen(0, 'before.png'), self.screen(620, 'after.png'))
        self.assertTrue(result['reliable'], result)
        self.assertAlmostEqual(result['shift'], 620, delta=1)
        self.assertFalse(result['unchanged'])
        self.assertGreater(result['confidence'], .7)

    def test_return_toward_top_is_negative(self):
        result = estimate_vertical_shift(self.screen(620, 'before.png'), self.screen(0, 'after.png'))
        self.assertTrue(result['reliable'], result)
        self.assertAlmostEqual(result['shift'], -620, delta=1)

    def test_unchanged_content_ignores_top_bottom_chrome(self):
        result = estimate_vertical_shift(self.screen(320, 'before.png'),
                                         self.screen(320, 'after.png', chrome=(11, 75, 99)))
        self.assertTrue(result['reliable'], result)
        self.assertEqual(result['shift'], 0)
        self.assertTrue(result['unchanged'])

    def test_odd_pixel_shift_has_original_pixel_precision(self):
        result = estimate_vertical_shift(self.screen(0, 'before.png'), self.screen(157, 'after.png'))
        self.assertTrue(result['reliable'], result)
        self.assertAlmostEqual(result['shift'], 157, delta=1)

    def test_scene_change_does_not_claim_scroll_or_bottom(self):
        before = self.screen(0, 'before.png')
        rng = np.random.default_rng(61)
        after = self.root / 'different.png'
        Image.fromarray(rng.integers(0, 256, (1120, 630, 3), dtype=np.uint8)).save(after)
        result = estimate_vertical_shift(before, after)
        self.assertFalse(result['reliable'], result)
        self.assertIsNone(result['shift'])
        self.assertFalse(result['unchanged'])

    def test_truly_repeating_rows_are_ambiguous_not_a_false_155_shift(self):
        tile = self.content.crop((0, 0, 584, 155))
        for top in range(0, 3500, 155):
            self.content.paste(tile, (0, top))
        result = estimate_vertical_shift(self.screen(0, 'before.png'), self.screen(155, 'after.png'))
        self.assertFalse(result['reliable'], result)
        self.assertIsNone(result['shift'])
        self.assertEqual(result['reason'], 'ambiguous_repeating_rows')

    def test_blank_loading_frame_is_not_a_confirmed_boundary(self):
        self.content = Image.new('RGB', (584, 3600), 'white')
        result = estimate_vertical_shift(self.screen(0, 'before.png'), self.screen(0, 'after.png'))
        self.assertFalse(result['reliable'], result)
        self.assertEqual(result['reason'], 'insufficient_texture')
        self.assertFalse(result['unchanged'])

    def test_unlocked_resolution_is_rejected(self):
        path = self.root / 'wrong-size.png'
        Image.new('RGB', (750, 1334)).save(path)
        with self.assertRaises(ValueError):
            estimate_vertical_shift(path, path)


if __name__ == '__main__':
    unittest.main()
