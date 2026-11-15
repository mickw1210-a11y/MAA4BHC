"""Offline planning for uncertain item quantities; sends no device actions."""
import math
import re
from copy import deepcopy

from .inventory_comparison import _exact_integer
from .ocr import COUNT, parse_inventory

LABELED_COUNT = re.compile(r'^(?:拥有数量|持有数量|当前拥有|已拥有|拥有|持有|数量)[：:]?')


def plan_detail_checks(rows):
    """Identify grid slots needing a detail check without generating coordinates."""
    plan, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('道具记录格式无效')
        if row.get('invalid'):
            continue
        quantity = row.get('quantity')
        page, slot = row.get('grid_page'), row.get('grid_slot')
        valid_slot = isinstance(page, str) and bool(page) and type(slot) is int and 1 <= slot <= 25
        if valid_slot:
            key = (page, slot)
            if key in seen:
                raise ValueError('有效记录的页面格号重复')
            seen.add(key)
        if isinstance(quantity, str) and _exact_integer(quantity.strip()) is not None:
            continue
        if not valid_slot:
            raise ValueError('数量待核对的记录缺少可靠的页面或格号')
        plan.append({'index': index, 'page': page, 'slot': slot, 'name': row.get('name'), 'quantity': quantity,
                     'reason': 'missing' if quantity is None or not str(quantity).strip() else 'not_exact'})
    return plan


def detail_check_is_current(plan, rows, *, visible_page):
    """Reject stale rows and source pages that are no longer visible."""
    if not isinstance(plan, dict) or plan.get('reason') not in ('missing', 'not_exact'):
        return False
    page, slot = plan.get('page'), plan.get('slot')
    if not isinstance(page, str) or not page or type(slot) is not int or not 1 <= slot <= 25:
        return False
    if visible_page != page:
        return False
    quantity = plan.get('quantity')
    if isinstance(quantity, str) and _exact_integer(quantity.strip()) is not None:
        return False
    index = plan.get('index')
    if type(index) is not int or not 0 <= index < len(rows):
        return False
    row = rows[index]
    return (isinstance(row, dict) and not row.get('invalid') and row.get('grid_page') == page
            and row.get('grid_slot') == slot and row.get('name') == plan.get('name')
            and row.get('quantity') == quantity)


def return_image_is_consistent(before, after):
    """Compare synthetic frame signatures; consistency alone is not page proof."""
    def valid(value):
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return False
        size, pixels = value
        return (isinstance(size, (tuple, list)) and tuple(size) == (630, 1120)
                and isinstance(pixels, (tuple, list, bytes)) and len(pixels) == 64 * 96
                and all(type(pixel) is int and 0 <= pixel <= 255 for pixel in pixels))
    if not valid(before) or not valid(after):
        return False
    # The existing coarse image check is a consistency signal only. Real use
    # still needs verified page identity, current frame, and stable geometry.
    from .bridge import Bridge
    normalized_before = (tuple(before[0]), before[1])
    normalized_after = (tuple(after[0]), after[1])
    return Bridge._same_inventory_frame(normalized_before, normalized_after)


def suggest_detail_quantity(expected_name, tokens):
    """Suggest an exact count only when the labeled detail matches the item.

    A suggestion is not game-page validation or automatic approval. Unknown or
    ambiguous details remain pending and never mutate a saved inventory.
    """
    if not isinstance(expected_name, str) or not expected_name.strip():
        return {'status': 'pending', 'reason': '道具名称尚未确认', 'quantity': None}
    if not isinstance(tokens, (list, tuple)):
        return {'status': 'pending', 'reason': '详情识别结果无效', 'quantity': None}
    for token in tokens:
        if not isinstance(token, dict) or not isinstance(token.get('text'), str):
            return {'status': 'pending', 'reason': '详情识别结果无效', 'quantity': None}
        score, box = token.get('score'), token.get('box')
        if (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1
                or not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in box)
                or min(box) < 0 or box[2] == 0 or box[3] == 0):
            return {'status': 'pending', 'reason': '详情识别结果无效', 'quantity': None}
    try:
        labels = [t for t in tokens if t.get('score', 0) >= .9
                  and LABELED_COUNT.match(re.sub(r'\s+', '', t.get('text', '')))
                  and COUNT.fullmatch(re.sub(r'\s+', '', t.get('text', '')))]
    except (AttributeError, TypeError, ValueError):
        return {'status': 'pending', 'reason': '详情识别结果无效', 'quantity': None}
    if len(labels) != 1:
        return {'status': 'pending', 'reason': '详情数量标签不明确', 'quantity': None}
    try:
        parsed = parse_inventory(tokens)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return {'status': 'pending', 'reason': '详情识别结果无效', 'quantity': None}
    if parsed['status'] != 'recognized' or len(parsed['rows']) != 1:
        return {'status': 'pending', 'reason': '详情识别不完整', 'quantity': None}
    result = parsed['rows'][0]
    if result['name'] != expected_name.strip():
        return {'status': 'pending', 'reason': '详情名称与原道具不一致', 'quantity': None}
    if _exact_integer(result['quantity']) is None:
        return {'status': 'pending', 'reason': '详情数量仍非精确整数', 'quantity': None}
    return {'status': 'suggested', 'reason': '详情名称与数量标签匹配，仍需核对', 'quantity': result['quantity']}


def simulate_detail_result(rows, plan, tokens, *, visible_page, detail_confirmed, returned_to_source,
                           source_signature, returned_signature):
    """Exercise a synthetic detail result without acting on or saving a device.

    The booleans are supplied by an offline test; they are not recognition of
    real game pages. The returned rows still need the normal final review.
    """
    result = deepcopy(rows)
    if detail_confirmed is not True or returned_to_source is not True:
        return {'status': 'pending', 'reason': '详情或返回页面尚未确认', 'rows': result}
    if not return_image_is_consistent(source_signature, returned_signature):
        return {'status': 'pending', 'reason': '返回后的画面与来源不一致', 'rows': result}
    if not detail_check_is_current(plan, result, visible_page=visible_page):
        return {'status': 'pending', 'reason': '原记录或当前页面已变化，需重新核对', 'rows': result}
    suggestion = suggest_detail_quantity(plan['name'], tokens)
    if suggestion['status'] != 'suggested':
        return {'status': 'pending', 'reason': suggestion['reason'], 'rows': result}
    row = result[plan['index']]
    row['quantity_before_detail'] = row.get('quantity')
    row['quantity'] = suggestion['quantity']
    row['quantity_source'] = 'synthetic_detail'
    return {'status': 'review', 'reason': '样例详情已读取，仍需最终核对', 'rows': result}


def simulate_detail_batch(rows, observations):
    """Exercise all required details as a single offline, all-or-nothing batch.

    Observations are synthetic results keyed by (page, slot). No device input,
    OCR execution, or inventory file writes occur here.
    """
    if not isinstance(observations, dict):
        raise ValueError('详情样例格式无效')
    original = deepcopy(rows)
    candidate = deepcopy(rows)
    plans = plan_detail_checks(candidate)
    for plan in plans:
        evidence = observations.get((plan['page'], plan['slot']))
        if not isinstance(evidence, dict):
            return {'status': 'pending', 'reason': '仍有详情样例未提供', 'rows': original}
        result = simulate_detail_result(candidate, plan, evidence.get('tokens', []),
                                        visible_page=evidence.get('visible_page'),
                                        detail_confirmed=evidence.get('detail_confirmed'),
                                        returned_to_source=evidence.get('returned_to_source'),
                                        source_signature=evidence.get('source_signature'),
                                        returned_signature=evidence.get('returned_signature'))
        if result['status'] != 'review':
            return {'status': 'pending', 'reason': result['reason'], 'rows': original}
        candidate = result['rows']
    return {'status': 'review', 'reason': '样例数量已处理，仍需最终核对', 'rows': candidate}
