"""Map supported portrait bag images to the existing recognition coordinates."""
from PIL import Image


REFERENCE_SIZE = (630, 1120)
SUPPORTED_SIZES = (REFERENCE_SIZE, (450, 800))


def normalize_bag_image(image):
    if image.size not in SUPPORTED_SIZES:
        raise ValueError('背包识别目前支持630×1120和450×800')
    rgb = image.convert('RGB')
    if rgb.size == REFERENCE_SIZE:
        return rgb
    return rgb.resize(REFERENCE_SIZE, Image.Resampling.LANCZOS)


def bag_point_to_device(x, y, size):
    if size not in SUPPORTED_SIZES:
        raise ValueError('尚未支持当前背包画面尺寸')
    return (round(x * size[0] / REFERENCE_SIZE[0]),
            round(y * size[1] / REFERENCE_SIZE[1]))
