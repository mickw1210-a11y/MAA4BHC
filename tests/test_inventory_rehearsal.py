import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT
from app.inventory import ManualInventory
from app.inventory_comparison import read_inventory_csv
from app.inventory_rehearsal import advance_rehearsal, load_rehearsal, save_rehearsal


def rows(*pairs):
    return [{'name': name, 'quantity': quantity} for name, quantity in pairs]


def advance(state, snapshot, name, *, complete=True, order_verified=True, reviewed=True):
    return advance_rehearsal(state, snapshot, name, reviewed=reviewed,
                             complete=complete, order_verified=order_verified)


class InventoryRehearsalTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / '.cache/tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='inventory-rehearsal-', dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'inventory-rehearsal.json'

    def test_baseline_and_three_rounds_survive_restarts(self):
        first = rows(('甲', '10'), ('乙', '4'), ('丙', '3'))
        state = advance(None, first, 'first')
        self.assertEqual(state['baseline'], first)
        self.assertEqual(state['changes'], [])
        save_rehearsal(self.path, state)
        state = advance(load_rehearsal(self.path), rows(('甲', '12'), ('丙', '3')), 'second')
        by_name = {row['name']: row for row in state['current']}
        self.assertEqual((by_name['乙']['quantity'], by_name['乙']['observed'], by_name['乙']['inferred']), ('0', False, True))
        self.assertEqual([(c['name'], c['delta']) for c in state['changes']], [('甲', 2), ('乙', -4)])
        save_rehearsal(self.path, state)
        state = advance(load_rehearsal(self.path), rows(('甲', '13'), ('丙', '3'), ('丁', '5')), 'third')
        self.assertEqual(state['baseline'], first)
        self.assertEqual([(c['name'], c['delta']) for c in state['changes']], [('甲', 2), ('乙', -4), ('甲', 1)])
        self.assertEqual(state['current'][-1]['name'], '丁')
        self.assertFalse(next(row for row in state['current'] if row['name'] == '乙')['observed'])

    def test_missing_then_reappearing_does_not_claim_intermediate_changes(self):
        state = advance(None, rows(('甲', '1'), ('乙', '4'), ('丙', '2')), 'first')
        state = advance(state, rows(('甲', '1'), ('丙', '2')), 'second', complete=False)
        missing = next(row for row in state['current'] if row['name'] == '乙')
        self.assertEqual((missing['quantity'], missing['observed'], missing['last_seen']), ('4', False, 'first'))
        state = advance(state, rows(('甲', '1'), ('乙', '7'), ('丙', '2')), 'third')
        self.assertEqual([(change['name'], change['delta'], change['from_observation'], change['to_observation'])
                          for change in state['changes']], [('乙', 3, 'first', 'third')])
        self.assertEqual(next(row for row in state['current'] if row['name'] == '乙')['quantity'], '7')

    def test_reappearance_after_inferred_zero_keeps_inference_provenance(self):
        state = advance(None, rows(('甲', '1'), ('乙', '4'), ('丙', '2')), 'first')
        state = advance(state, rows(('甲', '1'), ('丙', '2')), 'second')
        self.assertEqual(state['changes'][0]['delta'], -4)
        state = advance(state, rows(('甲', '1'), ('乙', '7'), ('丙', '2')), 'third')
        self.assertEqual(len(state['changes']), 2)
        change = state['changes'][1]
        self.assertEqual((change['delta'], change['from_observation'], change['to_observation'], change['status']),
                         (7, 'second', 'third', 'changed_after_inference'))
        self.assertEqual(change['inference_neighbors'], {'left': '甲', 'right': '丙'})

    def test_approximate_count_change_retains_displays_without_guessing_delta(self):
        state = advance(None, rows(('甲', '1.2万')), 'first')
        state = advance(state, rows(('甲', '1.3万')), 'second')
        change = state['changes'][0]
        self.assertEqual((change['previous_display'], change['current_display'], change['delta']),
                         ('1.2万', '1.3万', None))
        self.assertEqual(change['status'], 'changed_unknown_amount')
        state = advance(state, rows(('甲', '1.3万')), 'third')
        self.assertEqual(len(state['changes']), 1)

    def test_approximate_inferred_depletion_keeps_original_display_and_neighbors(self):
        state = advance(None, rows(('甲', '1'), ('乙', '1.2万'), ('丙', '2')), 'first')
        state = advance(state, rows(('甲', '1'), ('丙', '2')), 'second')
        change = state['changes'][0]
        self.assertEqual((change['previous_display'], change['current_display'], change['delta']), ('1.2万', '0', None))
        self.assertEqual(change['status'], 'inferred_depleted_unknown_amount')
        self.assertEqual(change['inference_neighbors'], {'left': '甲', 'right': '丙'})

    def test_approximate_count_reappearing_after_gap_preserves_interval_without_guess(self):
        state = advance(None, rows(('甲', '1'), ('乙', '1.2万'), ('丙', '2')), 'first')
        state = advance(state, rows(('甲', '1'), ('丙', '2')), 'second', order_verified=False)
        state = advance(state, rows(('甲', '1'), ('乙', '12345'), ('丙', '2')), 'third')
        change = state['changes'][0]
        self.assertEqual((change['previous_display'], change['current_display'], change['delta']),
                         ('1.2万', '12345', None))
        self.assertEqual((change['from_observation'], change['to_observation'], change['status']),
                         ('first', 'third', 'changed_after_gap_unknown_amount'))

    def test_uncertain_relative_order_survives_missing_rounds_until_verified(self):
        state = advance(None, rows(('甲', '1'), ('乙', '4'), ('丁', '3')), 'first')
        state = advance(state, rows(('甲', '1'), ('丙', '2'), ('丁', '3')), 'second')
        self.assertEqual({r['name'] for r in state['current'] if r['order_uncertain']}, {'乙', '丙'})
        state = advance(state, rows(('甲', '1'), ('丁', '3')), 'third')
        self.assertEqual({r['name'] for r in state['current'] if r['order_uncertain']}, {'乙', '丙'})
        state = advance(state, rows(('甲', '1'), ('丙', '2'), ('乙', '4'), ('丁', '3')), 'fourth')
        self.assertEqual([r['name'] for r in state['current']], ['甲', '丙', '乙', '丁'])
        self.assertFalse(any(r['order_uncertain'] for r in state['current']))

    def test_invalid_round_never_changes_existing_state(self):
        state = advance(None, rows(('甲', '1')), 'first')
        original = json.dumps(state, ensure_ascii=False, sort_keys=True)
        for snapshot, name, flags in [(rows(('甲', '2')), 'first', {}),
                                       (rows(('甲', '2')), 'second', {'reviewed': False}),
                                       (rows(('甲', '2'), ('甲', '3')), 'second', {})]:
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                advance(state, snapshot, name, **flags)
            self.assertEqual(json.dumps(state, ensure_ascii=False, sort_keys=True), original)

    def test_interrupted_commit_keeps_previous_generation(self):
        old = advance(None, rows(('甲', '1')), 'first')
        save_rehearsal(self.path, old)
        new = advance(old, rows(('甲', '2')), 'second')
        with patch('app.inventory_rehearsal.os.replace', side_effect=OSError('模拟中断')):
            with self.assertRaises(OSError):
                save_rehearsal(self.path, new)
        self.assertEqual(load_rehearsal(self.path), old)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        save_rehearsal(self.path, new)
        self.assertEqual(load_rehearsal(self.path), new)

    def test_write_failure_before_replace_preserves_existing_state(self):
        old = advance(None, rows(('甲', '1')), 'first')
        save_rehearsal(self.path, old)
        new = advance(old, rows(('甲', '2')), 'second')
        with patch('app.inventory_rehearsal.os.fsync', side_effect=OSError('模拟写入失败')):
            with self.assertRaises(OSError):
                save_rehearsal(self.path, new)
        self.assertEqual(load_rehearsal(self.path), old)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_corrupt_saved_state_is_not_silently_replaced_by_empty_state(self):
        self.path.write_text('{bad json', encoding='utf-8')
        before = self.path.read_bytes()
        with self.assertRaises(json.JSONDecodeError):
            load_rehearsal(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_first_snapshot_must_be_complete_and_reviewed(self):
        for flags in ({'complete': False}, {'reviewed': False}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                advance(None, rows(('甲', '1')), 'first', **flags)
        self.assertFalse(self.path.exists())

    def test_reviewed_csv_exports_flow_through_rehearsal_without_changing_sources(self):
        snapshots, sources = [], []
        for folder, entries in [('first', [('甲', '10'), ('乙', '4'), ('丙', '3')]),
                                ('second', [('甲', '12'), ('丙', '3')])]:
            inv = ManualInventory(Path(self.temporary.name) / folder)
            for name, quantity in entries:
                inv.add(name, quantity)
            inv.finish(True)
            sources.append((inv.output, inv.output.read_bytes()))
            with inv.output.open(encoding='utf-8-sig', newline='') as stream:
                snapshots.append(read_inventory_csv(stream))
        state = advance(None, snapshots[0], 'first')
        save_rehearsal(self.path, state)
        state = advance(load_rehearsal(self.path), snapshots[1], 'second')
        save_rehearsal(self.path, state)
        self.assertEqual([(change['name'], change['delta']) for change in load_rehearsal(self.path)['changes']],
                         [('甲', 2), ('乙', -4)])
        self.assertTrue(all(path.read_bytes() == content for path, content in sources))

    def test_rehearsal_cannot_write_outside_local_temporary_area(self):
        with self.assertRaises(ValueError):
            save_rehearsal(ROOT / 'data/inventory-rehearsal.json', {})


if __name__ == '__main__':
    unittest.main()
