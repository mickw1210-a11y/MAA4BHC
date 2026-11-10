import base64
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app.config import ROOT
from app.bridge import Bridge
from app.inventory import ManualInventory
from app.ocr import CONTENT_ROI, LocalOcr, _cell_name, _grid_geometry, parse_inventory
from tests.test_worker import wait_idle


def token(text, y, score=0.99):
    return {'text': text, 'score': score, 'box': [80, y, 220, 30]}


class OcrParsingTests(unittest.TestCase):
    def grid(self):
        values = [token('背包', 20)]
        labels = ''.join(chr(0x4e00 + index) for index in range(25))
        for row, y in enumerate([278, 435, 590, 745, 900]):
            for col, center in enumerate([84, 200, 317, 433, 550]):
                values.append({'text': '测试道具' + labels[row * 5 + col], 'score': 0.99,
                               'box': [center - 40, y, 80, 20]})
                values.append({'text': str(row * 5 + col + 1), 'score': 0.99,
                               'box': [center + 25, y - 33, 20, 20]})
        return values

    def test_bag_grid_pairs_badges_and_names_in_reading_order(self):
        result = parse_inventory(list(reversed(self.grid())), image_size=(630, 1120))
        self.assertEqual(result['layout'], 'bag_grid_5cols')
        self.assertEqual(result['status'], 'recognized')
        self.assertEqual([row['quantity'] for row in result['rows']], list(map(str, range(1, 26))))

    def test_grid_missing_badge_keeps_slot_and_does_not_assume_one(self):
        values = [value for value in self.grid() if value['text'] != '1']
        result = parse_inventory(values, image_size=(630, 1120))
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(len(result['rows']), 25)
        self.assertEqual(result['rows'][0]['quantity'], '')
        self.assertEqual(result['rows'][1]['quantity'], '2')

    def test_merged_first_row_names_do_not_move_the_page_anchor(self):
        values = [value for value in self.grid()
                  if not (value['text'].startswith('测试道具') and value['box'][1] == 278
                          and value['box'][0] in (277, 393))]
        values.append({'text': '中级经营许可初级经营许可', 'score': .999,
                       'box': [260, 285, 228, 17]})
        result = parse_inventory(values, image_size=(630, 1120))
        self.assertEqual(result['rows'][0]['quantity'], '1')
        self.assertEqual(result['rows'][5]['quantity'], '6')
        self.assertEqual(result['rows'][2]['name'], '')
        self.assertEqual(result['rows'][3]['name'], '')
        self.assertEqual(result['status'], 'pending')

    def test_partial_sixth_row_is_reference_not_an_extra_page_row(self):
        values = self.grid() + [{'text': '半露道具', 'score': 0.99, 'box': [44, 1055, 80, 20]}]
        result = parse_inventory(values, image_size=(630, 1120))
        self.assertEqual(len(result['rows']), 25)
        self.assertEqual(result['status'], 'recognized')
        self.assertEqual(result['expected_cells'], 25)
        self.assertNotIn('半露道具', [row['name'] for row in result['rows']])

    def test_labeled_items_keep_page_order(self):
        result = parse_inventory([token('拥有数量：20', 300), token('道具名称：道具乙', 200),
                                  token('道具名称：道具甲', 500), token('拥有：1.2万', 550)])
        self.assertEqual(result['status'], 'recognized')
        self.assertEqual(result['rows'], [{'name': '道具乙', 'quantity': '20'}, {'name': '道具甲', 'quantity': '1.2万'}])

    def test_unique_title_and_explicit_count(self):
        self.assertEqual(parse_inventory([token('测试宝箱', 200), token('拥有：123', 300)])['rows'],
                         [{'name': '测试宝箱', 'quantity': '123'}])

    def test_ambiguous_or_low_confidence_stays_pending(self):
        for tokens in [[token('测试宝箱', 200), token('普通宝箱', 240), token('拥有：123', 300)],
                       [token('道具名称：测试宝箱', 200), token('拥有：123', 300, 0.6)],
                       [token('价格：123', 200), token('剩余时间', 300)]]:
            result = parse_inventory(tokens)
            self.assertEqual(result['status'], 'pending')
            self.assertEqual(result['rows'], [])

    def test_excluded_category_produces_no_rows(self):
        for category in ['活动道具', '待合成', '合成道具']:
            self.assertEqual(parse_inventory([token('道具类型：' + category, 100), token('拥有：123', 300)])['status'], 'excluded')

    def test_visible_inactive_tab_does_not_exclude_normal_item(self):
        result = parse_inventory([token('活动道具', 100), token('道具名称：普通宝箱', 200), token('拥有：123', 300)])
        self.assertEqual(result['status'], 'recognized')


class InventoryCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp')
        self.addCleanup(self.temp.cleanup)
        self.inventory = ManualInventory(Path(self.temp.name))
        stream = io.BytesIO()
        Image.new('RGB', (6, 10), 'white').save(stream, format='PNG')
        self.data = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()

    def bridge(self, tokens):
        data = self.data
        class ScreenshotOnly:
            def screenshot(self, token, *, save=True):
                assert save is False, 'No permanent screenshot copy'
                return {'data': data, 'width': 6, 'height': 10, 'frame_id': 'test', 'time': 'fixture'}
            def __getattr__(self, name):
                raise AssertionError('Unexpected device access: ' + name)
        class FakeOcr:
            def read_inventory(self, path, token):
                assert path.is_file()
                token.check()
                return tokens, parse_inventory(tokens)
        with patch('app.bridge.ManualInventory', return_value=self.inventory):
            bridge = Bridge(inventory_capture=True, device=ScreenshotOnly())
        bridge._ocr = FakeOcr()
        bridge._status = 'connected'
        self.addCleanup(bridge.shutdown)
        return bridge

    def capture(self, bridge):
        self.assertTrue(bridge.screenshot()['ok'])
        wait_idle(bridge._worker)
        deadline = time.monotonic() + 2
        while bridge.get_state()['frame'] is None and time.monotonic() < deadline:
            time.sleep(0.01)

    def test_capture_ocr_temp_storage_and_no_game_input(self):
        bridge = self.bridge([token('道具名称：测试宝箱', 200), token('拥有：123', 300)])
        self.assertFalse(bridge.click(1, 1)['ok'])
        self.assertFalse(bridge.swipe(1, 1, 2, 2, 300)['ok'])
        self.capture(bridge)
        self.assertEqual(self.inventory.rows, [{'name': '测试宝箱', 'quantity': '123'}])
        self.assertEqual(len(self.inventory.shots), 1)
        self.capture(bridge)
        self.assertEqual(len(self.inventory.rows), 1)
        self.assertEqual(len(self.inventory.shots), 2)
        self.assertEqual(len(self.inventory.groups), 2)
        self.assertTrue(bridge.inventory_action('finish', True)['ok'])
        self.assertEqual(self.inventory.shots, [])

    def test_pending_blocks_completion_and_next_capture_until_reviewed(self):
        bridge = self.bridge([token('未知页面', 100)])
        self.capture(bridge)
        self.assertFalse(bridge.screenshot()['ok'])
        self.inventory.add('人工确认道具', '10')
        with self.assertRaises(ValueError):
            self.inventory.finish(True)
        self.inventory.review(self.inventory.shots[0])
        self.assertEqual(self.inventory.finish(True)['phase'], 'completed')

    def test_quantity_conflict_preserves_old_count(self):
        self.inventory.add('测试宝箱', '100')
        bridge = self.bridge([token('道具名称：测试宝箱', 200), token('拥有：123', 300)])
        self.capture(bridge)
        self.assertEqual(self.inventory.rows[0]['quantity'], '100')
        self.assertEqual(next(iter(self.inventory.ocr_reports.values()))['status'], 'pending')

    def test_grid_unread_quantity_is_saved_but_cannot_be_exported(self):
        self.inventory.import_image(self.data)
        shot = self.inventory.shots[0]
        self.inventory.apply_ocr(shot, [], {'rows': [{'name': '缺数道具', 'quantity': ''}],
                                          'status': 'pending', 'message': '待核对'})
        self.assertEqual(self.inventory.rows[0]['quantity'], '')
        self.inventory.review(shot)
        with self.assertRaises(ValueError):
            self.inventory.finish(True)
        self.inventory.update(0, '缺数道具', '1')
        self.assertEqual(self.inventory.finish(True)['phase'], 'completed')


class RetryTests(unittest.TestCase):
    setUp = InventoryCaptureTests.setUp
    bridge = InventoryCaptureTests.bridge
    capture = InventoryCaptureTests.capture
    def test_second_attempt_success_does_not_duplicate_rows(self):
        bridge = self.bridge([])
        class RetryOcr:
            calls = 0
            def read_inventory(self, path, token):
                self.calls += 1
                if self.calls == 1:
                    return [], {'rows': [], 'status': 'pending', 'message': '失败'}
                values = [globals()['token']('道具名称：测试宝箱', 200), globals()['token']('拥有：123', 300)]
                return values, parse_inventory(values)
        engine = RetryOcr()
        bridge._ocr = engine
        self.capture(bridge)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(len(self.inventory.shots), 2)
        self.assertEqual(len(self.inventory.groups), 1)
        self.assertEqual(len(self.inventory.rows), 1)
        self.assertTrue(all(value['status'] != 'pending' for value in self.inventory.ocr_reports.values()))

    def test_failure_is_limited_to_initial_plus_two_recaptures(self):
        bridge = self.bridge([])
        self.capture(bridge)
        self.assertEqual(len(self.inventory.shots), 3)
        self.assertEqual(len(self.inventory.groups), 1)
        self.assertEqual(sum(report['status'] == 'pending' for report in self.inventory.ocr_reports.values()), 1)
        self.assertEqual(len(self.inventory.rows), 0)

    def test_ocr_exception_also_retries_only_twice(self):
        bridge = self.bridge([])
        class BrokenOcr:
            def read_inventory(self, path, token):
                raise RuntimeError('fixture OCR error')
        bridge._ocr = BrokenOcr()
        self.capture(bridge)
        self.assertEqual(len(self.inventory.shots), 3)

    def test_stop_prevents_another_recapture(self):
        bridge = self.bridge([])
        class StoppedOcr:
            def read_inventory(self, path, token):
                bridge.stop()
                return [], {'rows': [], 'status': 'pending', 'message': '失败'}
        bridge._ocr = StoppedOcr()
        self.assertTrue(bridge.screenshot()['ok'])
        wait_idle(bridge._worker)
        self.assertEqual(len(self.inventory.shots), 1)
        self.assertEqual(bridge.get_state()['status'], 'stopped')

    def test_stable_image_spelling_changes_retry_and_leave_disputed_name_empty(self):
        bridge = self.bridge([])
        class ChangedOcr:
            calls = 0
            def read_inventory(self, path, token):
                self.calls += 1
                name = '原页道具' if self.calls == 1 else '另一页道具'
                return [], {'rows': [{'name': name, 'quantity': '10'}],
                            'status': 'pending', 'message': '部分识别'}
        engine = ChangedOcr()
        bridge._ocr = engine
        self.capture(bridge)
        self.assertEqual(engine.calls, 3)
        self.assertEqual([row['name'] for row in self.inventory.rows], [''])
        self.assertTrue(any(report['status'] == 'pending' for report in self.inventory.ocr_reports.values()))

    def test_inline_cell_update_keeps_order_and_other_values(self):
        self.inventory.add('道具甲', '1')
        self.inventory.add('道具乙', '2')
        self.inventory.update_cell(0, 'quantity', '27')
        self.assertEqual(self.inventory.rows, [{'name': '道具甲', 'quantity': '27'}, {'name': '道具乙', 'quantity': '2'}])
        resumed = ManualInventory(self.inventory.root)
        self.assertEqual(resumed.rows, self.inventory.rows)


class DynamicGeometryTests(unittest.TestCase):
    def samples(self):
        path = ROOT / 'tests/fixtures/step59/grid_geometry.json'
        return json.loads(path.read_text('utf-8'))['samples']

    def test_recorded_detector_geometry_follows_each_manual_scroll(self):
        # These are detector boxes from actual retained reports, with all item
        # names/counts replaced. They include the failed third-page phase.
        expected = [[280, 434, 588, 744, 899], [287, 441, 596, 753, 907],
                    [296, 450, 607, 761, 916], [295, 450, 603, 761, 916],
                    [352, 507, 663, 817, 972]]
        for sample, tops in zip(self.samples(), expected):
            with self.subTest(sample=sample['sample']):
                geometry = _grid_geometry(sample['tokens'])
                if tops is None:
                    self.assertIsNone(geometry)
                else:
                    self.assertEqual(geometry['row_name_tops'], tops)
                    self.assertEqual(geometry['support_columns'], [0, 1, 2, 3, 4])

    def test_blank_sparse_and_single_column_are_not_a_grid(self):
        values = OcrParsingTests().grid()
        for tokens in [[], [token('未知页面', 280)],
                       [value for value in values if value['box'][0] == 44]]:
            self.assertIsNone(_grid_geometry(tokens))

    def test_first_row_missing_all_names_does_not_shift_to_second_row(self):
        values = [value for value in OcrParsingTests().grid() if value['box'][1] != 278]
        self.assertIsNone(_grid_geometry(values))

    def test_second_line_wrap_with_single_character_is_joined_in_order(self):
        values = [{'text': '测试高级材料碎', 'score': .99, 'box': [28, 296, 108, 18]},
                  {'text': '片', 'score': .99, 'box': [76, 316, 18, 18]}]
        self.assertEqual(_cell_name(list(reversed(values)), [24, 292, 116, 46]), '测试高级材料碎片')

    def test_overlapping_name_alternatives_are_not_concatenated(self):
        values = [{'text': '测试材料', 'score': .99, 'box': [30, 296, 80, 18]},
                  {'text': '测试材科', 'score': .99, 'box': [31, 296, 80, 18]}]
        self.assertEqual(_cell_name(values, [24, 292, 116, 46]), '')

    def test_half_top_row_is_skipped_and_bottom_two_items_keep_their_slots(self):
        values = self.samples()[-1]['tokens'] + [
            {'text': '第六排道具', 'score': .99, 'box': [30 + 116 * col, 972, 100, 20]}
            for col in range(2)]
        geometry = _grid_geometry(values)
        self.assertEqual(geometry['row_name_tops'], [352, 507, 663, 817, 972])
        self.assertEqual(geometry['row_support'][-1], 2)
        result = parse_inventory([token('背包', 10)] + values, image_size=(630, 1120))
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['rows'][20]['name'], '第六排道具')
        self.assertEqual(result['rows'][21]['name'], '第六排道具')
        self.assertEqual(result['rows'][22]['name'], '')

    def test_inventory_reader_uses_measured_name_and_quantity_regions(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as temp:
            path = Path(temp) / 'blank.png'
            Image.new('RGB', (630, 1120), 'white').save(path)
            calls = []
            detections = self.samples()[2]['tokens']
            class Token:
                def check(self): pass
            engine = LocalOcr()
            def read(path, token, *, roi=None, only_rec=False, scale=None):
                calls.append((roi, only_rec, scale))
                if roi == (24, 0, 584, 150):
                    return [globals()['token']('背包', 10)]
                if roi == CONTENT_ROI:
                    return detections
                return []
            with patch.object(engine, 'read', side_effect=read):
                _, result = engine.read_inventory(path, Token())
            self.assertTrue(result['layout_valid'])
            self.assertEqual(result['geometry']['row_name_tops'][0], 296)
            self.assertEqual(calls[2], ([24, 292, 116, 46], False, 3))
            self.assertEqual(calls[3], ([48, 257, 88, 34], True, None))
            self.assertEqual(len(result['rows']), 25)
            self.assertEqual(len(calls), 52)

    def test_wrong_page_and_blank_page_do_not_generate_25_hallucinated_slots(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as temp:
            path = Path(temp) / 'blank.png'
            Image.new('RGB', (630, 1120), 'white').save(path)
            class Token:
                def check(self): pass
            engine = LocalOcr()
            for header, detected in [([], self.samples()[2]['tokens']),
                                     ([token('背包', 10)], [])]:
                with patch.object(engine, 'read', side_effect=[header, detected]) as read:
                    _, result = engine.read_inventory(path, Token())
                self.assertEqual(read.call_count, 2)
                self.assertFalse(result['layout_valid'])
                self.assertEqual(result['rows'], [])
                self.assertEqual(result['status'], 'pending')

    def test_high_confidence_spelling_conflict_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cache/tmp') as temp:
            path = Path(temp) / 'blank.png'
            Image.new('RGB', (630, 1120), 'white').save(path)
            detections = OcrParsingTests().grid()[1:]
            class Token:
                def check(self): pass
            engine = LocalOcr()
            def read(path, token, *, roi=None, only_rec=False, scale=None):
                if roi == (24, 0, 584, 150): return [globals()['token']('背包', 10)]
                if roi == CONTENT_ROI: return detections
                if not only_rec:
                    return [{'text': '错别名称', 'score': .999, 'box': [roi[0] + 5, roi[1] + 4, 80, 20]}]
                return []
            with patch.object(engine, 'read', side_effect=read):
                _, result = engine.read_inventory(path, Token())
            self.assertTrue(result['layout_valid'])
            self.assertEqual(result['status'], 'pending')
            self.assertTrue(all(row['name'] == '' for row in result['rows']))

    def test_all_wrapped_labels_choose_first_line_as_name_top(self):
        values = OcrParsingTests().grid()
        second_lines = [dict(value, text='第二行字', box=[value['box'][0], value['box'][1] + 20, 80, 18])
                        for value in values if value['text'].startswith('测试道具')]
        self.assertEqual(_grid_geometry(values + second_lines)['row_name_tops'], [278, 435, 590, 745, 900])
