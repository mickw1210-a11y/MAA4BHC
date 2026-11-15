"""Compare confirmed observations without reading or writing inventory files."""
import csv
import re


def _index(rows):
    indexed = {}
    for row in rows:
        name, quantity = row.get("name"), row.get("quantity")
        if not isinstance(name, str) or not name.strip() or not isinstance(quantity, str) or not quantity.strip():
            raise ValueError("道具名称和数量不能为空")
        name, quantity = name.strip(), quantity.strip()
        if name in indexed:
            raise ValueError("存在同名道具，请先核对")
        indexed[name] = quantity
    return indexed


def _exact_integer(value):
    # Abbreviations such as 1.2万 may be rounded on screen, not exact counts.
    if len(value) <= 40 and re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", value):
        return int(value.replace(",", ""))
    return None


def _merge_order(before, after):
    """Keep each observation's order; flag relative positions that are unknown."""
    old, new = list(before), list(after)
    common_old = [name for name in old if name in after]
    common_new = [name for name in new if name in before]
    if common_old != common_new:
        missing = [name for name in old if name not in after]
        return new + missing, set(missing)
    merged, uncertain = [], set()
    i = j = 0
    for anchor in common_old + [None]:
        old_gap, new_gap = [], []
        while i < len(old) and old[i] != anchor:
            old_gap.append(old[i]); i += 1
        while j < len(new) and new[j] != anchor:
            new_gap.append(new[j]); j += 1
        if old_gap and new_gap:
            uncertain.update(old_gap + new_gap)
        merged.extend(old_gap + new_gap)
        if anchor is not None:
            merged.append(anchor)
            i += 1; j += 1
    return merged, uncertain


def compare_inventory(previous, current, *, current_complete=False, order_verified=False):
    """Return observations in bag order when the relative position is known.

    Both inputs must be reviewed, valid rows from their respective observations.
    Depletion is inferred only when the caller has verified completeness and
    ordering; newly seen names do not imply acquisition.
    """
    previous, current = list(previous), list(current)
    before, after = _index(previous), _index(current)
    if type(current_complete) is not bool or type(order_verified) is not bool:
        raise ValueError("采集完整性和排列顺序必须明确确认")
    inferred = {}
    if current_complete and order_verified:
        # A reordered common item invalidates the ordering assumption globally.
        common_before = [name for name in before if name in after]
        common_after = [name for name in after if name in before]
        if common_before != common_after:
            raise ValueError("两轮道具顺序不一致，不能按相邻道具推断")
        inferred = {name: {"left": clue["left"], "right": clue["right"]}
                    for clue in missing_between_neighbors(previous, current)
                    for name in clue["missing"]}
    names, uncertain = _merge_order(before, after)
    result = []
    for name in names:
        old, new = before.get(name), after.get(name)
        delta = None
        if old is None:
            status = "newly_seen"
        elif name in inferred:
            new = "0"
            old_count = _exact_integer(old)
            delta = -old_count if old_count is not None else None
            status = "inferred_depleted"
        elif new is None:
            status = "not_seen"
        else:
            old_count, new_count = _exact_integer(old), _exact_integer(new)
            if old_count is None or new_count is None:
                status = "needs_review"
            else:
                delta = new_count - old_count
                status = "unchanged" if delta == 0 else "changed"
        result.append({"name": name, "previous": old, "current": new, "status": status,
                       "delta": delta, "order_uncertain": name in uncertain,
                       "inference_neighbors": inferred.get(name)})
    return result


def missing_between_neighbors(previous, current):
    """Find missing runs bracketed by two adjacent, ordered current names.

    This returns clues for review, not proof of depletion or a zero count. The
    caller must provide reviewed observations in actual bag order.
    """
    before, after = _index(previous), _index(current)
    old_names, new_names = list(before), list(after)
    positions = {name: index for index, name in enumerate(new_names)}
    clues = []
    index = 0
    while index < len(old_names):
        if old_names[index] in positions:
            index += 1
            continue
        start = index
        while index < len(old_names) and old_names[index] not in positions:
            index += 1
        if start == 0 or index == len(old_names):
            continue
        left, right = old_names[start - 1], old_names[index]
        if positions[right] == positions[left] + 1:
            clues.append({"left": left, "missing": old_names[start:index], "right": right})
    return clues


def read_inventory_csv(stream):
    """Read an already-reviewed export; caller owns the text stream and encoding."""
    reader = csv.reader(stream, strict=True)
    try:
        header = next(reader)
        if header != ["道具名称", "数量"]:
            raise ValueError("CSV表头不符合背包记录格式")
        rows = []
        for line in reader:
            if len(line) != 2:
                raise ValueError("CSV记录列数不正确")
            rows.append({"name": line[0], "quantity": line[1]})
    except (StopIteration, csv.Error) as error:
        raise ValueError("CSV为空或格式不完整") from error
    if not rows:
        raise ValueError("CSV没有库存记录")
    _index(rows)
    return rows
