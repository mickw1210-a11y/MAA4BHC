export function selectionRect(start, end) {
  return { left: Math.min(start.x, end.x), right: Math.max(start.x, end.x), top: Math.min(start.y, end.y), bottom: Math.max(start.y, end.y) }
}

export function rowsInRect(rect, rows) {
  return rows.filter(row => row.right >= rect.left && row.left <= rect.right && row.bottom >= rect.top && row.top <= rect.bottom).map(row => row.index)
}

export function selectRectangle(previous, hits, additive = false) {
  return new Set(additive ? [...previous, ...hits] : hits)
}

export function selectRow(previous, index, { additive = false, range = false, anchor = null, visible = [] } = {}) {
  if (range && anchor !== null && visible.includes(anchor)) {
    const low = Math.min(index, anchor), high = Math.max(index, anchor)
    return new Set([...previous, ...visible.filter(value => value >= low && value <= high)])
  }
  if (!additive) return new Set([index])
  const result = new Set(previous)
  if (result.has(index)) result.delete(index)
  else result.add(index)
  return result
}

export function isSelectionControl(target) {
  return !!target?.closest?.('button, input, select, textarea, a, [contenteditable="true"], [data-no-row-select]')
}
