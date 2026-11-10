"""Local screenshot alignment for the locked 630 x 1120 bag screen.

No device access, OCR, file writes or navigation. A failed/ambiguous match is
never an instruction to continue scrolling or proof that the bag bottom exists.
"""
from pathlib import Path

import numpy as np
from PIL import Image


SCREEN_SIZE = (630, 1120)
SCROLL_ROI = (24, 160, 584, 880)
MIN_OVERLAP = 220


def _load(path):
    with Image.open(Path(path)) as image:
        if image.size != SCREEN_SIZE:
            raise ValueError("背包对齐仅支持已锁定的630×1120原始截图")
        x, y, width, height = SCROLL_ROI
        return image.convert("RGB").crop((x, y, x + width, y + height))


def _features(image, vertical_scale):
    image = image.resize((146, SCROLL_ROI[3] // vertical_scale), Image.Resampling.BILINEAR)
    color = np.asarray(image, dtype=np.float32) / 255
    gray = color.mean(axis=2)
    horizontal = np.zeros_like(gray)
    vertical = np.zeros_like(gray)
    horizontal[:, 1:] = np.abs(np.diff(gray, axis=1))
    vertical[1:] = np.abs(np.diff(gray, axis=0))
    edge = horizontal + vertical
    # Flat tile backgrounds should not outweigh the actual icons and letters.
    weight = .04 + np.minimum(edge * 4, 1)
    return color, edge, weight


def _cost(before, after, shift):
    height = before[0].shape[0]
    if shift >= 0:
        old = tuple(array[shift:] for array in before)
        new = tuple(array[:height - shift] for array in after)
    else:
        old = tuple(array[:height + shift] for array in before)
        new = tuple(array[-shift:] for array in after)
    weight = np.maximum(old[2], new[2])
    distance = np.mean(np.abs(old[0] - new[0]), axis=2) * .8 + np.abs(old[1] - new[1]) * .2
    weighted = distance * weight
    errors = [float(weighted[:, left:right].sum() / weight[:, left:right].sum())
              for left, right in zip((0, 29, 58, 88, 117), (29, 58, 88, 117, 146))]
    return float(weighted.sum() / weight.sum()), errors


def estimate_vertical_shift(before_path, after_path):
    """Return shift in original pixels (positive means content moved upward).

    Result keys: shift (float or None), confidence [0, 1], error (normalized
    weighted pixel error), unchanged, reliable, reason. Diagnostics include
    candidate_shift, overlap, ambiguity_gap, supporting_columns and roi.
    ``unchanged`` is only true for a reliable near-zero alignment. The caller
    must still verify page identity and use repeated settled observations to
    determine a scroll boundary; this function alone cannot prove the bottom.
    """
    old_image, new_image = _load(before_path), _load(after_path)
    old, new = _features(old_image, 2), _features(new_image, 2)
    texture = min(float(old[1].mean()), float(new[1].mean()))
    limit = (SCROLL_ROI[3] - MIN_OVERLAP) // 2
    scored = [(shift, *_cost(old, new, shift)) for shift in range(-limit, limit + 1)]
    scored.sort(key=lambda value: value[1])
    coarse_shift, coarse_error, _ = scored[0]
    competitor = next(value for value in scored if abs(value[0] - coarse_shift) > 6)
    gap = competitor[1] - coarse_error
    # Refine using original vertical resolution, so odd-pixel movement and
    # cumulative row alignment are not rounded to the downsampled grid.
    full_old, full_new = _features(old_image, 1), _features(new_image, 1)
    refined = [(shift, *_cost(full_old, full_new, shift))
               for shift in range(max(-limit * 2, coarse_shift * 2 - 2),
                                  min(limit * 2, coarse_shift * 2 + 2) + 1)]
    shift, error, columns = min(refined, key=lambda value: value[1])
    column_minima = [min(value[2][index] for value in scored) for index in range(5)]
    supporting = sum(cost < .16 and cost <= best + .035 for cost, best in zip(columns, column_minima))
    fit = max(0., min(1., 1. - error / .16))
    uniqueness = max(0., min(1., gap / .055))
    confidence = round(fit * uniqueness * min(1., supporting / 3), 4)
    reliable = texture >= .008 and error < .12 and gap >= .018 and supporting >= 3
    if texture < .008:
        reason = "insufficient_texture"
    elif error >= .12:
        reason = "scene_changed_or_no_overlap"
    elif gap < .018:
        reason = "ambiguous_repeating_rows"
    elif supporting < 3:
        reason = "columns_disagree"
    else:
        reason = "matched"
    return {"shift": float(shift) if reliable else None,
            "confidence": confidence if reliable else min(confidence, .49),
            "error": round(error, 6), "unchanged": bool(reliable and abs(shift) <= 2),
            "reliable": bool(reliable), "reason": reason,
            "candidate_shift": float(shift), "overlap": SCROLL_ROI[3] - abs(shift),
            "ambiguity_gap": round(gap, 6), "supporting_columns": int(supporting),
            "roi": list(SCROLL_ROI)}
