import unittest

from PIL import Image

from app.bag_geometry import bag_point_to_device, normalize_bag_image


class BagGeometryTests(unittest.TestCase):
    def test_450_image_uses_reference_coordinates_and_preserves_source(self):
        source = Image.new('RGB', (450, 800), (100, 80, 60))
        result = normalize_bag_image(source)
        self.assertEqual(result.size, (630, 1120))
        self.assertEqual(result.getpixel((590, 920)), (100, 80, 60))
        self.assertEqual(source.size, (450, 800))

    def test_reference_image_pixels_stay_identical(self):
        source = Image.new('RGBA', (630, 1120), (100, 80, 60, 255))
        self.assertEqual(normalize_bag_image(source).tobytes(), source.convert('RGB').tobytes())

    def test_swipe_points_map_to_actual_screen(self):
        self.assertEqual(bag_point_to_device(590, 920, (630, 1120)), (590, 920))
        self.assertEqual(bag_point_to_device(590, 920, (450, 800)), (421, 657))
        self.assertEqual(bag_point_to_device(590, 820, (450, 800)), (421, 586))

    def test_unknown_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_bag_image(Image.new('RGB', (750, 1334)))
        with self.assertRaises(ValueError):
            bag_point_to_device(590, 920, (800, 450))
