// Pure presentation decisions; the Python backend remains responsible for data validation.
export function reviewCounts(rows) {
  const valid = rows.filter(row => !row.invalid)
  return {
    valid: valid.length,
    incomplete: valid.filter(row => !String(row.name ?? '').trim() || !String(row.quantity ?? '').trim()).length,
    duplicate: rows.filter(row => row.invalid && row.invalid_reason === 'duplicate').length,
  }
}

export function matchingGroup(rows, groups) {
  return groups.find(group => rows.some(row => group.images.includes(row.grid_page)))
}

export function previewWarning(hasImage, rows, group) {
  if (!hasImage || !rows.length) return ''
  if (!group) return '当前画面未关联截图组，请选择截图组核对。'
  if (rows.some(row => !group.images.includes(row.grid_page))) return '本页还包含其他截图或手动填写的记录，请切换截图组核对。'
  return ''
}

export function finishBlockReason({ busy, phase, captureMode, captureComplete, valid, editing, incomplete, reports, confirmed }) {
  if (busy) return '正在处理，请稍候。'
  if (phase === 'completed') return '本次记录已完成。'
  if (captureMode === 'automatic' && !captureComplete) return '本轮采集未完成，请重新采集后再保存。'
  if (!valid) return '请先记录有效道具。'
  if (editing) return '请先保存或取消正在修改的记录。'
  if (incomplete) return `还有 ${incomplete} 条记录缺名称或数量，请先核对。`
  if (Object.values(reports || {}).some(report => report.status === 'pending')) return '还有截图需要核对，请选择待核对的截图组。'
  if (!confirmed && phase === 'draft') return '请核对记录并勾选下方确认。'
  return ''
}

export function previewIsCurrent(startingRevision, currentRevision) {
  return startingRevision === currentRevision
}
