"""Offline inventory-update rehearsal; no real inventory files are accessed.

This pure-data prototype does not implement the production CSV storage or
recovery protocol. Its caller supplies reviewed sample observations.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from .config import ROOT
from .inventory_comparison import _exact_integer, compare_inventory


def advance_rehearsal(state, rows, observation_id, *, reviewed, complete, order_verified):
    """Return a new rehearsal state; neither input is modified.

    A reappearing item may use its last observed count for an interval net
    change; the intermediate events remain unknown.
    """
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError("必须指定本轮标识")
    if any(type(value) is not bool for value in (reviewed, complete, order_verified)):
        raise ValueError("核对、完整性和顺序状态必须明确")
    if not reviewed:
        raise ValueError("记录尚未核对，不能更新库存")
    snapshot = deepcopy(list(rows))
    validated = compare_inventory([], snapshot)
    if not validated:
        raise ValueError("空记录不能更新库存")
    snapshot = [{"name": row["name"], "quantity": row["current"]} for row in validated]
    if state is None:
        if not complete:
            raise ValueError("首次基线需要完整记录")
        return {"baseline": deepcopy(snapshot), "current": [
            {**row, "observed": True, "last_seen": observation_id, "inferred": False,
             "order_uncertain": False} for row in snapshot],
            "last_snapshot": snapshot, "last_complete": complete,
            "last_order_verified": order_verified, "observations": [observation_id], "changes": []}

    state = deepcopy(state)
    if observation_id in state["observations"]:
        raise ValueError("本轮标识已存在，不能重复更新")
    prior = {row["name"]: row for row in state["current"]}
    comparison = compare_inventory(state["last_snapshot"], snapshot,
                                   current_complete=complete and state["last_complete"],
                                   order_verified=order_verified and state["last_order_verified"])
    by_name = {row["name"]: row for row in comparison}
    # Keep unobserved items in the view without using stale rows as neighbors.
    display = compare_inventory([{"name": row["name"], "quantity": row["quantity"]}
                                 for row in state["current"]], snapshot)
    previously_uncertain = {row['name'] for row in state['current'] if row['order_uncertain']}
    observed_names = {row['name'] for row in snapshot}
    resolved_order = order_verified and previously_uncertain.issubset(observed_names)
    current, changes = [], []
    for row in display:
        name = row["name"]
        compared = by_name.get(name)
        old = prior.get(name)
        uncertain = row['order_uncertain'] or (name in previously_uncertain and not resolved_order)
        if row["current"] is not None:
            current.append({"name": name, "quantity": row["current"], "observed": True,
                            "last_seen": observation_id, "inferred": False,
                            "order_uncertain": uncertain})
        elif compared and compared["status"] == "inferred_depleted":
            current.append({"name": name, "quantity": "0", "observed": False,
                            "last_seen": old["last_seen"], "inferred": True,
                            "inferred_at": observation_id,
                            "order_uncertain": uncertain,
                            "inference_neighbors": compared["inference_neighbors"]})
        else:
            current.append({**old, "observed": False, "order_uncertain": uncertain})
        delta = compared['delta'] if compared else None
        change_status = compared['status'] if compared else None
        change_from = state['observations'][-1]
        neighbors = compared['inference_neighbors'] if compared else None
        previous_display = compared['previous'] if compared else None
        current_display = compared['current'] if compared else None
        record_unknown = False
        if compared and compared['status'] == 'needs_review' and previous_display != current_display:
            change_status = 'changed_unknown_amount'
            record_unknown = True
        elif compared and compared['status'] == 'inferred_depleted' and delta is None:
            change_status = 'inferred_depleted_unknown_amount'
            record_unknown = True
        if compared and compared['status'] == 'newly_seen' and old and not old['observed']:
            previous_display = old['quantity']
            previous_count, new_count = _exact_integer(old['quantity']), _exact_integer(compared['current'])
            if old['inferred']:
                change_status = 'changed_after_inference'
                change_from = old['inferred_at']
                neighbors = old['inference_neighbors']
            else:
                change_status = 'changed_after_gap'
                change_from = old['last_seen']
            if previous_count is not None and new_count is not None:
                delta = new_count - previous_count
            elif previous_display != current_display:
                change_status += '_unknown_amount'
                record_unknown = True
        if delta not in (None, 0) or record_unknown:
            changes.append({"name": name, "delta": delta,
                            "previous_display": previous_display, "current_display": current_display,
                            "from_observation": change_from,
                            "to_observation": observation_id, "status": change_status,
                            "inference_neighbors": neighbors})
    state.update(current=current, last_snapshot=snapshot, last_complete=complete,
                 last_order_verified=order_verified)
    state["observations"].append(observation_id)
    state["changes"].extend(changes)
    return state


def _sample_path(path):
    path = Path(path).resolve()
    sample_root = (ROOT / '.cache' / 'tmp').resolve()
    if not path.is_relative_to(sample_root) or path.name != 'inventory-rehearsal.json':
        raise ValueError('演练文件必须位于项目临时目录')
    return path


def save_rehearsal(path, state):
    """Commit a single offline rehearsal state, keeping the old file on failure."""
    path = _sample_path(path)
    data = json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8')
    # Create an independent staging file, never reuse an earlier interrupted one.
    handle, name = tempfile.mkstemp(prefix='inventory-rehearsal-', suffix='.tmp', dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def load_rehearsal(path):
    path = _sample_path(path)
    with path.open(encoding='utf-8') as stream:
        return json.load(stream)
