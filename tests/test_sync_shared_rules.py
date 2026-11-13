"""Only the explicitly delimited shared rules can be copied between documents."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT
from scripts.sync_shared_rules import END, START, check, section, sync


class ProjectSharedRulesTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / 'AGENTS.md').exists(), '本机未提供 AGENTS.md')
    def test_project_shared_rules_are_consistent(self):
        self.assertTrue(check(ROOT), '共同要求不一致，请核对后明确同步方向')


class SharedRulesTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.cache/tmp').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.agents = self.root / 'AGENTS.md'
        self.handoff = self.root / 'Workspace_Handoff.md'
        self.agents.write_text('本机规则\n' + START + '\n共同规则甲\n' + END + '\n本机进度\n', encoding='utf-8')
        self.handoff.write_text('公开进度\n' + START + '\n共同规则乙\n' + END + '\n其他记录\n', encoding='utf-8')

    def test_agents_to_handoff_preserves_unrelated_text(self):
        self.assertFalse(check(self.root))
        self.assertTrue(sync(self.root, 'agents'))
        self.assertTrue(check(self.root))
        text = self.handoff.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('公开进度\n'))
        self.assertTrue(text.endswith('\n其他记录\n'))
        self.assertNotIn('本机进度', text)
        self.assertFalse(sync(self.root, 'agents'))

    def test_handoff_to_agents_preserves_unrelated_text(self):
        self.assertTrue(sync(self.root, 'handoff'))
        self.assertTrue(check(self.root))
        text = self.agents.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('本机规则\n'))
        self.assertTrue(text.endswith('\n本机进度\n'))
        self.assertNotIn('公开进度', text)

    def test_duplicate_or_reversed_markers_are_rejected(self):
        for text in ['', END + START, START + END + START]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                section(text)
        self.handoff.write_text('没有标记', encoding='utf-8')
        before = self.handoff.read_bytes()
        with self.assertRaises(ValueError):
            sync(self.root, 'agents')
        self.assertEqual(self.handoff.read_bytes(), before)

    def test_target_changed_during_sync_is_not_overwritten(self):
        actual = Path.read_bytes
        calls = 0
        def read_bytes(path):
            nonlocal calls
            if path == self.handoff:
                calls += 1
                if calls == 2:
                    self.handoff.write_text('另一项修改', encoding='utf-8')
            return actual(path)
        with patch.object(Path, 'read_bytes', read_bytes):
            with self.assertRaisesRegex(ValueError, '目标文件已变化'):
                sync(self.root, 'agents')
        self.assertEqual(self.handoff.read_text(encoding='utf-8'), '另一项修改')
        self.assertFalse(self.handoff.with_name(self.handoff.name + '.sync.tmp').exists())

    def test_existing_temporary_file_is_not_overwritten(self):
        temp = self.handoff.with_name(self.handoff.name + '.sync.tmp')
        temp.write_text('已有恢复文件', encoding='utf-8')
        before = self.handoff.read_bytes()
        with self.assertRaises(ValueError):
            sync(self.root, 'agents')
        self.assertEqual(self.handoff.read_bytes(), before)
        self.assertEqual(temp.read_text(encoding='utf-8'), '已有恢复文件')


if __name__ == '__main__':
    unittest.main()
