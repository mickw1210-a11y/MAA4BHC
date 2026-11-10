import test from 'node:test'
import assert from 'node:assert/strict'
import { isSelectionControl, rowsInRect, selectionRect, selectRectangle, selectRow } from './inventorySelection.js'

const values = selection => [...selection].sort((a, b) => a - b)
test('拖选任意方向得到相同矩形，命中相交行', () => {
  const rect = selectionRect({ x: 80, y: 110 }, { x: 10, y: 36 })
  assert.deepEqual(rect, { left: 10, right: 80, top: 36, bottom: 110 })
  assert.deepEqual(rowsInRect(rect, [
    { index: 25, left: 0, right: 500, top: 0, bottom: 35 },
    { index: 26, left: 0, right: 500, top: 36, bottom: 71 },
    { index: 27, left: 0, right: 500, top: 72, bottom: 107 },
    { index: 28, left: 0, right: 500, top: 108, bottom: 143 },
    { index: 29, left: 81, right: 500, top: 108, bottom: 143 },
  ]), [26, 27, 28])
})
test('普通框选替换；Ctrl框选累加；不改原选择', () => {
  const before = new Set([25, 26])
  assert.deepEqual(values(selectRectangle(before, [30, 31])), [30, 31])
  assert.deepEqual(values(selectRectangle(before, [26, 30], true)), [25, 26, 30])
  assert.deepEqual(values(before), [25, 26])
})
test('普通单击只选当前行；复选框和Ctrl切换当前行', () => {
  assert.deepEqual(values(selectRow(new Set([1, 2]), 3)), [3])
  assert.deepEqual(values(selectRow(new Set([1, 2]), 2, { additive: true })), [1])
  assert.deepEqual(values(selectRow(new Set([1, 2]), 3, { additive: true })), [1, 2, 3])
})
test('Shift仅选本页范围，全局索引保持26起', () => {
  const visible = Array.from({ length: 25 }, (_, index) => index + 25)
  assert.deepEqual(values(selectRow(new Set(), 29, { range: true, anchor: 26, visible })), [26, 27, 28, 29])
  assert.deepEqual(values(selectRow(new Set(), 26, { range: true, anchor: 29, visible })), [26, 27, 28, 29])
  assert.deepEqual(values(selectRow(new Set(), 26, { range: true, anchor: 1, visible })), [26])
})
test('按钮、输入框及嵌套控件点击不启动行拖选', () => {
  for (const selector of ['button', 'input', 'select', 'textarea', 'a', '[contenteditable="true"]', '[data-no-row-select]']) {
    assert.equal(isSelectionControl({ closest: query => query.includes(selector) ? {} : null }), true)
  }
  assert.equal(isSelectionControl({ closest: () => null }), false)
  assert.equal(isSelectionControl(null), false)
})
