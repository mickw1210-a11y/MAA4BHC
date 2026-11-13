import test from 'node:test'
import assert from 'node:assert/strict'
import { reviewCounts, matchingGroup, previewWarning, finishBlockReason, previewIsCurrent } from './inventoryReview.js'

const groupA = { id: 'a', images: ['a.png', 'retry.png'] }
const groupB = { id: 'b', images: ['b.png'] }
const ready = { busy: false, phase: 'draft', captureMode: 'automatic', captureComplete: true,
  valid: 1, editing: false, incomplete: 0, reports: {}, confirmed: true }

test('有效、缺项与疑似重复分别计数，不把零数量视为缺项', () => {
  assert.deepEqual(reviewCounts([
    {name: '中文道具', quantity: '0'}, {name: '', quantity: '2'},
    {name: '重复', quantity: '2', invalid: true, invalid_reason: 'duplicate'},
    {name: '', quantity: '', invalid: true},
  ]), {valid: 2, incomplete: 1, duplicate: 1})
})
test('翻页查找截图组并支持同组重试图，不凭空匹配手动项', () => {
  assert.equal(matchingGroup([{grid_page: 'retry.png'}], [groupA, groupB]), groupA)
  assert.equal(matchingGroup([{grid_page: 'b.png'}], [groupA, groupB]), groupB)
  assert.equal(matchingGroup([{name: '手动项'}], [groupA, groupB]), undefined)
})
test('未关联或混合来源的画面提示核对', () => {
  assert.match(previewWarning(true, [{grid_page: 'a.png'}], null), /未关联/)
  assert.match(previewWarning(true, [{grid_page: 'a.png'}, {grid_page: 'b.png'}], groupA), /其他截图/)
  assert.match(previewWarning(true, [{grid_page: 'a.png'}, {name: '手动项'}], groupA), /手动填写/)
  assert.equal(previewWarning(true, [{grid_page: 'retry.png'}], groupA), '')
  assert.equal(previewWarning(false, [{grid_page: 'b.png'}], groupA), '')
})
test('新截图到达后不显示旧的延迟预览', () => {
  assert.equal(previewIsCurrent(4, 4), true)
  assert.equal(previewIsCurrent(4, 5), false)
})
test('未完整采集、缺项或待核对时不能保存', () => {
  assert.match(finishBlockReason({...ready, captureComplete: false}), /采集未完成/)
  assert.match(finishBlockReason({...ready, incomplete: 2}), /2 条/)
  assert.match(finishBlockReason({...ready, reports: {a: {status: 'pending'}}}), /截图需要核对/)
  assert.match(finishBlockReason({...ready, confirmed: false}), /勾选/)
  assert.match(finishBlockReason({...ready, valid: 0}), /有效道具/)
  assert.match(finishBlockReason({...ready, editing: true}), /修改/)
  assert.match(finishBlockReason({...ready, busy: true}), /稍候/)
  assert.equal(finishBlockReason(ready), '')
})
test('已导出的轮次允许继续清理，仍需采集完成和记录有效', () => {
  assert.equal(finishBlockReason({...ready, phase: 'exported', confirmed: false}), '')
  assert.match(finishBlockReason({...ready, phase: 'exported', captureComplete: false}), /采集未完成/)
  assert.match(finishBlockReason({...ready, phase: 'completed'}), /已完成/)
})
