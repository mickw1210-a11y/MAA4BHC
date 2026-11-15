import unittest
import tempfile
from pathlib import Path

from app.config import ROOT
from app.inventory_csv_sample import CsvSampleStore
from app.inventory_detail_review import (detail_check_is_current, plan_detail_checks,
                                         return_image_is_consistent, simulate_detail_batch,
                                         simulate_detail_result, suggest_detail_quantity)


def token(text, y, score=.99):
    return {'text': text, 'score': score, 'box': [80, y, 220, 30]}


def signature(value=100):
    return ((630, 1120), (value,) * (64 * 96))


class DetailQuantityReviewTests(unittest.TestCase):
    def test_only_ambiguous_quantities_get_detail_checks(self):
        rows = [{'name': '甲', 'quantity': '0', 'grid_page': 'page', 'grid_slot': 1},
                {'name': '乙', 'quantity': '1,200', 'grid_page': 'page', 'grid_slot': 2},
                {'name': '丙', 'quantity': '1.2万', 'grid_page': 'page', 'grid_slot': 3},
                {'name': '丁', 'quantity': '', 'grid_page': 'page', 'grid_slot': 4},
                {'name': '戊', 'quantity': '', 'grid_page': 'page', 'grid_slot': 5, 'invalid': True}]
        self.assertEqual([(item['slot'], item['reason']) for item in plan_detail_checks(rows)],
                         [(3, 'not_exact'), (4, 'missing')])

    def test_ambiguous_slot_requires_unambiguous_source_and_valid_grid(self):
        for rows in [[{'name': '甲', 'quantity': ''}],
                     [{'name': '甲', 'quantity': '', 'grid_page': 'p', 'grid_slot': True}],
                     [{'name': '甲', 'quantity': '', 'grid_page': 'p', 'grid_slot': 1},
                      {'name': '乙', 'quantity': '1.2万', 'grid_page': 'p', 'grid_slot': 1}],
                     [{'name': '甲', 'quantity': '10', 'grid_page': 'p', 'grid_slot': 1},
                      {'name': '乙', 'quantity': '', 'grid_page': 'p', 'grid_slot': 1}]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                plan_detail_checks(rows)

    def test_labeled_detail_with_matching_name_suggests_exact_count(self):
        for text in ('拥有：12345', '拥有 12345', '数量12345'):
            with self.subTest(text=text):
                result = suggest_detail_quantity('测试宝箱', [token('测试宝箱', 200), token(text, 300)])
                self.assertEqual((result['status'], result['quantity']), ('suggested', '12345'))

    def test_return_frame_consistency_never_accepts_missing_or_wrong_geometry(self):
        reference = ((630, 1120), (100,) * (64 * 96))
        self.assertTrue(return_image_is_consistent(reference, ((630, 1120), (103,) * (64 * 96))))
        self.assertFalse(return_image_is_consistent(reference, ((630, 1120), (160,) * (64 * 96))))
        for value in (None, ((750, 1334), (100,) * (64 * 96)), ((630, 1120), ()),
                      ((630, 1120), (True,) * (64 * 96))):
            with self.subTest(value_type=type(value)):
                self.assertFalse(return_image_is_consistent(reference, value))

    def test_coarse_image_similarity_never_replaces_page_identity_check(self):
        row = {'name': '测试宝箱', 'quantity': '1.2万', 'grid_page': 'page', 'grid_slot': 2}
        plan = plan_detail_checks([row])[0]
        similar = signature(103)
        self.assertTrue(return_image_is_consistent(signature(), similar))
        result = simulate_detail_result([row], plan, [token('测试宝箱', 200), token('拥有：12345', 300)],
                                        visible_page='page', detail_confirmed=True, returned_to_source=False,
                                        source_signature=signature(), returned_signature=similar)
        self.assertEqual((result['status'], result['rows'][0]['quantity']), ('pending', '1.2万'))

    def test_stale_plan_cannot_survive_edits_moving_or_exclusion(self):
        row = {'name': '样例', 'quantity': '1.2万', 'grid_page': 'page', 'grid_slot': 2}
        plan = plan_detail_checks([row])[0]
        self.assertTrue(detail_check_is_current(plan, [row], visible_page='page'))
        self.assertFalse(detail_check_is_current(plan, [row], visible_page='other'))
        for changed in [{**row, 'quantity': '12345'}, {**row, 'name': '其他'},
                        {**row, 'grid_page': 'other'}, {**row, 'grid_slot': 3}, {**row, 'invalid': True}]:
            with self.subTest(changed=changed):
                self.assertFalse(detail_check_is_current(plan, [changed], visible_page='page'))
        self.assertFalse(detail_check_is_current(plan, [], visible_page='page'))
        self.assertFalse(detail_check_is_current({'index': 0}, [{}], visible_page='page'))
        self.assertFalse(detail_check_is_current({**plan, 'quantity': '3'}, [{**row, 'quantity': '3'}], visible_page='page'))

    def test_ambiguous_or_nonmatching_detail_never_supplies_quantity(self):
        cases = [('', [token('测试宝箱', 200), token('拥有：123', 300)]),
                 ('测试宝箱', [token('其他道具', 200), token('拥有：123', 300)]),
                 ('测试宝箱', [token('测试宝箱', 200), token('123', 300)]),
                 ('测试宝箱', [token('测试宝箱', 200), token('拥有', 280), token('123', 300)]),
                 ('测试宝箱', [token('测试宝箱', 200), token('拥有：1.2万', 300)]),
                 ('测试宝箱', [token('测试宝箱', 200), token('拥有：123', 300, .5)]),
                 ('测试宝箱', [token('测试宝箱', 200), token('拥有：123', 300), token('数量：456', 340)])]
        for name, tokens in cases:
            with self.subTest(name=name, tokens=tokens):
                result = suggest_detail_quantity(name, tokens)
                self.assertEqual((result['status'], result['quantity']), ('pending', None))

    def test_malformed_ocr_result_stays_pending(self):
        for tokens in (None, [None], [{'text': '拥有：123', 'score': .99}],
                       [{'text': None, 'score': .99, 'box': [1, 2, 3, 4]}],
                       [token('测试宝箱', 200), token('拥有：123', 300, True)],
                       [token('测试宝箱', 200), token('拥有：123', 300, float('nan'))]):
            with self.subTest(tokens=tokens):
                result = suggest_detail_quantity('测试宝箱', tokens)
                self.assertEqual((result['status'], result['quantity']), ('pending', None))

    def test_synthetic_result_retains_original_and_requires_final_review(self):
        row = {'name': '测试宝箱', 'quantity': '1.2万', 'grid_page': 'page', 'grid_slot': 2}
        plan = plan_detail_checks([row])[0]
        result = simulate_detail_result([row], plan, [token('测试宝箱', 200), token('拥有：12345', 300)],
                                        visible_page='page', detail_confirmed=True, returned_to_source=True,
                                        source_signature=signature(), returned_signature=signature())
        self.assertEqual(result['status'], 'review')
        self.assertEqual((result['rows'][0]['quantity'], result['rows'][0]['quantity_before_detail']), ('12345', '1.2万'))
        self.assertEqual(row['quantity'], '1.2万')

    def test_synthetic_result_never_changes_row_after_uncertain_page_or_edit(self):
        row = {'name': '测试宝箱', 'quantity': '1.2万', 'grid_page': 'page', 'grid_slot': 2}
        plan = plan_detail_checks([row])[0]
        tokens = [token('测试宝箱', 200), token('拥有：12345', 300)]
        for detail, returned in [(False, True), (True, False), (None, True)]:
            with self.subTest(detail=detail, returned=returned):
                result = simulate_detail_result([row], plan, tokens, visible_page='page', detail_confirmed=detail,
                                                returned_to_source=returned, source_signature=signature(), returned_signature=signature())
                self.assertEqual((result['status'], result['rows'][0]['quantity']), ('pending', '1.2万'))
        changed = {**row, 'quantity': '手动修改'}
        result = simulate_detail_result([changed], plan, tokens, visible_page='page', detail_confirmed=True, returned_to_source=True,
                                        source_signature=signature(), returned_signature=signature())
        self.assertEqual((result['status'], result['rows'][0]['quantity']), ('pending', '手动修改'))
        result = simulate_detail_result([row], plan, tokens, visible_page='other', detail_confirmed=True, returned_to_source=True,
                                        source_signature=signature(), returned_signature=signature())
        self.assertEqual((result['status'], result['rows'][0]['quantity']), ('pending', '1.2万'))
        result = simulate_detail_result([row], plan, tokens, visible_page='page', detail_confirmed=True, returned_to_source=True,
                                        source_signature=signature(), returned_signature=signature(160))
        self.assertEqual((result['status'], result['rows'][0]['quantity']), ('pending', '1.2万'))

    def test_synthetic_batch_checks_only_uncertain_counts_and_keeps_order(self):
        rows = [{'name': '普通道具', 'quantity': '5', 'grid_page': 'p', 'grid_slot': 1},
                {'name': '测试宝箱', 'quantity': '1.2万', 'grid_page': 'p', 'grid_slot': 2},
                {'name': '样例道具', 'quantity': '', 'grid_page': 'p', 'grid_slot': 3}]
        evidence = {('p', 2): {'tokens': [token('测试宝箱', 200), token('拥有：12345', 300)],
                               'visible_page': 'p', 'detail_confirmed': True, 'returned_to_source': True,
                               'source_signature': signature(), 'returned_signature': signature()},
                    ('p', 3): {'tokens': [token('样例道具', 200), token('拥有：22', 300)],
                               'visible_page': 'p', 'detail_confirmed': True, 'returned_to_source': True,
                               'source_signature': signature(), 'returned_signature': signature()}}
        result = simulate_detail_batch(rows, evidence)
        self.assertEqual(result['status'], 'review')
        self.assertEqual([r['quantity'] for r in result['rows']], ['5', '12345', '22'])
        self.assertEqual([r['quantity'] for r in rows], ['5', '1.2万', ''])

    def test_fully_exact_page_needs_no_detail_observations(self):
        rows = [{'name': '甲', 'quantity': '0', 'grid_page': 'p', 'grid_slot': 1},
                {'name': '乙', 'quantity': '1,234', 'grid_page': 'p', 'grid_slot': 2}]
        result = simulate_detail_batch(rows, {})
        self.assertEqual(result['status'], 'review')
        self.assertEqual(result['rows'], rows)
        self.assertIsNot(result['rows'], rows)

    def test_synthetic_batch_rolls_back_partial_results_if_any_detail_unresolved(self):
        rows = [{'name': '测试宝箱', 'quantity': '1.2万', 'grid_page': 'p', 'grid_slot': 2},
                {'name': '样例道具', 'quantity': '', 'grid_page': 'p', 'grid_slot': 3}]
        first = {'tokens': [token('测试宝箱', 200), token('拥有：12345', 300)],
                 'visible_page': 'p', 'detail_confirmed': True, 'returned_to_source': True,
                 'source_signature': signature(), 'returned_signature': signature()}
        result = simulate_detail_batch(rows, {('p', 2): first})
        self.assertEqual(result['status'], 'pending')
        self.assertEqual([r['quantity'] for r in result['rows']], ['1.2万', ''])

    def test_synthetic_batch_stops_before_later_items_when_one_is_unresolved(self):
        class Observations(dict):
            def get(self, key, default=None):
                if key == ('p', 3):
                    raise AssertionError('不能继续处理后续道具')
                return super().get(key, default)
        rows = [{'name': name, 'quantity': '', 'grid_page': 'p', 'grid_slot': slot}
                for slot, name in [(1, '甲道具'), (2, '乙道具'), (3, '丙道具')]]
        first = {'tokens': [token('甲道具', 200), token('拥有：12', 300)], 'visible_page': 'p',
                 'detail_confirmed': True, 'returned_to_source': True,
                 'source_signature': signature(), 'returned_signature': signature()}
        result = simulate_detail_batch(rows, Observations({('p', 1): first}))
        self.assertEqual(result['status'], 'pending')
        self.assertEqual([row['quantity'] for row in result['rows']], ['', '', ''])

    def test_detail_results_require_final_review_before_sample_csv(self):
        rows = [{'name': '测试宝箱', 'quantity': '1.2万', 'grid_page': 'p', 'grid_slot': 2}]
        evidence = {('p', 2): {'tokens': [token('测试宝箱', 200), token('拥有：12345', 300)],
                               'visible_page': 'p', 'detail_confirmed': True, 'returned_to_source': True,
                               'source_signature': signature(), 'returned_signature': signature()}}
        result = simulate_detail_batch(rows, evidence)
        (ROOT / '.cache/tmp').mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='detail-csv-', dir=ROOT / '.cache/tmp') as folder:
            store = CsvSampleStore(folder)
            args = dict(scope='ordinary-items', complete=True, order_verified=True,
                        started_at='2026-11-15T09:00:00+08:00', observed_at='2026-11-15T09:05:00+08:00')
            with self.assertRaisesRegex(ValueError, '核对'):
                store.commit(result['rows'], 'first', reviewed=False, **args)
            self.assertFalse((Path(folder) / 'baseline.csv').exists())
            state = store.commit(result['rows'], 'first', reviewed=True, **args)
            self.assertEqual(state['baseline'], [{'name': '测试宝箱', 'quantity': '12345'}])
            self.assertEqual(rows[0]['quantity'], '1.2万')


if __name__ == '__main__':
    unittest.main()
