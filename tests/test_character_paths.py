import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import prepare_character_paths


class CharacterPathsTests(unittest.TestCase):
    def test_creates_only_empty_character_directories(self):
        with tempfile.TemporaryDirectory(dir='.cache') as tmp:
            root = Path(tmp)
            with patch('app.config.ROOT', root):
                config, assets = prepare_character_paths('0123456789', '昵称')
                self.assertEqual(config.parent.name, '0123456789_昵称')
                self.assertEqual({p.name for p in config.parent.iterdir()}, {'Priv_Config', 'Priv_Assets'})
                self.assertFalse(list(config.iterdir()))
                self.assertFalse(list(assets.iterdir()))
                self.assertEqual(prepare_character_paths('0123456789', '昵称'), (config, assets))

    def test_rejects_invalid_ids_and_unsafe_names(self):
        for character_id, nickname in [('123', '昵称'), ('１２３４５６７８９０', '昵称'), ('0123456789', '../bad'), ('0123456789', 'bad.'), ('0123456789', '')]:
            with self.subTest(character_id=character_id, nickname=nickname):
                with self.assertRaises(ValueError):
                    prepare_character_paths(character_id, nickname)
