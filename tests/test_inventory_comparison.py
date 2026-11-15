import io
import tempfile
import unittest
from pathlib import Path

from app.inventory import ManualInventory
from app.inventory_comparison import compare_inventory, missing_between_neighbors, read_inventory_csv
from app.config import ROOT


class InventoryComparisonTests(unittest.TestCase):
    def test_observed_changes_and_missing_are_distinct(self):
        before = [{'name': '钻石', 'quantity': '100'}, {'name': '券', 'quantity': '4'},
                  {'name': '材料', 'quantity': '7'}, {'name': '金币', 'quantity': '1,000'}]
        after = [{'name': '钻石', 'quantity': '120'}, {'name': '券', 'quantity': '0'},
                 {'name': '金币', 'quantity': '1000'}, {'name': '新道具', 'quantity': '3'}]
        result = {r['name']: r for r in compare_inventory(before, after)}
        self.assertEqual(result['钻石']['delta'], 20)
        self.assertEqual(result['券']['delta'], -4)
        self.assertEqual(result['金币']['status'], 'unchanged')
        self.assertEqual((result['材料']['status'], result['材料']['current'], result['材料']['delta']), ('not_seen', None, None))
        self.assertEqual((result['新道具']['status'], result['新道具']['delta']), ('newly_seen', None))

    def test_abbreviated_or_unreadable_values_are_not_guessed(self):
        result = compare_inventory([{'name': '金币', 'quantity': '1.2万'}], [{'name': '金币', 'quantity': '1.3万'}])[0]
        self.assertEqual((result['status'], result['delta']), ('needs_review', None))
        self.assertEqual((result['previous'], result['current']), ('1.2万', '1.3万'))

    def test_unreasonably_long_quantity_is_not_assumed_exact(self):
        value = '1' * 5000
        result = compare_inventory([{'name': '甲', 'quantity': '1'}], [{'name': '甲', 'quantity': value}])[0]
        self.assertEqual((result['status'], result['delta'], result['current']), ('needs_review', None, value))

    def test_duplicate_and_empty_names_or_quantities_stop_comparison(self):
        with self.assertRaises(ValueError):
            compare_inventory([], [{'name': '券', 'quantity': '1'}, {'name': ' 券 ', 'quantity': '2'}])
        with self.assertRaises(ValueError):
            compare_inventory([{'name': '券', 'quantity': ''}], [])

    def test_real_export_format_can_be_compared_without_modifying_either_file(self):
        base = ROOT / '.cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            paths = []
            for folder, amount in [('first', '100'), ('second', '120')]:
                inv = ManualInventory(Path(tmp) / folder)
                inv.add('钻石', amount)
                inv.finish(True)
                paths.append(inv.output)
            original = [path.read_bytes() for path in paths]
            observations = []
            for path in paths:
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    observations.append(read_inventory_csv(stream))
            self.assertEqual(compare_inventory(*observations)[0]['delta'], 20)
            self.assertEqual([path.read_bytes() for path in paths], original)

    def test_malformed_or_ambiguous_csv_is_rejected(self):
        for content in ['', '道具名称,数量\n', '名称,数量\n券,1\n',
                        '道具名称,数量\n券,1,2\n', '道具名称,数量\n券,1\n券,2\n',
                        '道具名称,数量\n券,"未结束']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                read_inventory_csv(io.StringIO(content))

    def test_neighbor_clues_identify_multiple_missing_without_asserting_zero(self):
        def rows(*names):
            return [{'name': name, 'quantity': '1'} for name in names]
        before = rows('甲', '乙', '丙', '丁')
        after = rows('甲', '丁')
        self.assertEqual(missing_between_neighbors(before, after),
                         [{'left': '甲', 'missing': ['乙', '丙'], 'right': '丁'}])
        result = compare_inventory(before, after)
        self.assertEqual([(r['status'], r['delta']) for r in result[1:3]],
                         [('not_seen', None), ('not_seen', None)])

    def test_neighbor_clues_require_both_bounds_in_order_and_no_intervening_item(self):
        def rows(*names):
            return [{'name': name, 'quantity': '1'} for name in names]
        before = rows('甲', '乙', '丙')
        for after in [rows('丙', '甲'), rows('甲', '新道具', '丙'), rows('甲'), rows('丙')]:
            with self.subTest(after=after):
                self.assertEqual(missing_between_neighbors(before, after), [])
        self.assertEqual(missing_between_neighbors(rows('甲', '乙', '丙', '丁'), rows('乙', '丙')), [])

    def test_verified_complete_order_infers_zero_only_between_matching_neighbors(self):
        def rows(*pairs):
            return [{'name': name, 'quantity': quantity} for name, quantity in pairs]
        before = rows(('首', '5'), ('甲', '2'), ('乙', '1.2万'), ('丙', '4'), ('尾', '9'))
        after = rows(('甲', '3'), ('丙', '4'))
        result = {r['name']: r for r in compare_inventory(before, after, current_complete=True, order_verified=True)}
        self.assertEqual((result['乙']['status'], result['乙']['current'], result['乙']['delta']),
                         ('inferred_depleted', '0', None))
        self.assertEqual((result['首']['status'], result['尾']['status']), ('not_seen', 'not_seen'))
        exact = compare_inventory(rows(('甲', '1'), ('乙', '8'), ('丙', '2')),
                                  rows(('甲', '1'), ('丙', '2')),
                                  current_complete=True, order_verified=True)
        self.assertEqual((exact[1]['current'], exact[1]['delta']), ('0', -8))

    def test_inference_requires_both_confirmations_and_consistent_order(self):
        rows = lambda *names: [{'name': name, 'quantity': '1'} for name in names]
        before, after = rows('甲', '乙', '丙'), rows('甲', '丙')
        for flags in [{}, {'current_complete': True}, {'order_verified': True}]:
            with self.subTest(flags=flags):
                self.assertEqual(compare_inventory(before, after, **flags)[1]['status'], 'not_seen')
        with self.assertRaises(ValueError):
            compare_inventory(rows('甲', '乙', '丙', '丁'), rows('丁', '甲', '丙'),
                              current_complete=True, order_verified=True)
        with self.assertRaises(ValueError):
            compare_inventory(before, after, current_complete='yes', order_verified=True)

    def test_new_items_follow_current_bag_order(self):
        rows = lambda *names: [{'name': name, 'quantity': '1'} for name in names]
        result = compare_inventory(rows('甲', '丁'), rows('甲', '乙', '丙', '丁'))
        self.assertEqual([r['name'] for r in result], ['甲', '乙', '丙', '丁'])
        self.assertFalse(any(r['order_uncertain'] for r in result))

    def test_unknown_relative_position_is_flagged_without_claiming_order(self):
        rows = lambda *names: [{'name': name, 'quantity': '1'} for name in names]
        result = compare_inventory(rows('甲', '旧', '丁'), rows('甲', '新', '丁'))
        self.assertEqual({r['name'] for r in result if r['order_uncertain']}, {'旧', '新'})
        result = compare_inventory(rows('甲', '乙', '丙'), rows('丙', '甲'))
        self.assertEqual([r['name'] for r in result[:2]], ['丙', '甲'])
        self.assertTrue(result[-1]['order_uncertain'])

    def test_reviewed_export_roundtrip_infers_zero_and_preserves_sources(self):
        base = ROOT / '.cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            paths = []
            for folder, entries in [('before', [('甲', '1'), ('乙', '4'), ('丙', '3')]),
                                    ('after', [('甲', '2'), ('丙', '3'), ('丁', '9')])]:
                inv = ManualInventory(Path(tmp) / folder)
                for name, quantity in entries:
                    inv.add(name, quantity)
                inv.add('被排除', '6')
                inv.remove(len(inv.rows) - 1)
                inv.finish(True)
                paths.append(inv.output)
            originals = [path.read_bytes() for path in paths]
            snapshots = []
            for path in paths:
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    snapshots.append(read_inventory_csv(stream))
            result = compare_inventory(iter(snapshots[0]), iter(snapshots[1]),
                                       current_complete=True, order_verified=True)
            self.assertEqual([row['name'] for row in result], ['甲', '乙', '丙', '丁'])
            self.assertEqual((result[0]['delta'], result[1]['current'], result[1]['delta']), (1, '0', -4))
            self.assertEqual(result[1]['inference_neighbors'], {'left': '甲', 'right': '丙'})
            self.assertEqual(result[3]['status'], 'newly_seen')
            self.assertEqual([path.read_bytes() for path in paths], originals)


if __name__ == '__main__':
    unittest.main()
