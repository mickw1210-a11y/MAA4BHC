<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { isSelectionControl, rowsInRect, selectionRect, selectRectangle, selectRow } from './inventorySelection.js'
import { reviewCounts, matchingGroup, previewWarning as getPreviewWarning, finishBlockReason as getFinishBlockReason, previewIsCurrent } from './inventoryReview.js'

const state = ref({ status: 'disconnected', message: '正在打开', busy: false, stopped: false, offline: false, frame: null })
const form = reactive({ adb_path: '', address: '', x: 0, y: 0, x2: 0, y2: 0, duration: 300 })
const error = ref('')
const image = ref('')
const ready = ref(false)
const inventory = ref({ rows: [], screenshots: [], phase: 'draft' })
const item = reactive({ name: '', quantity: '' })
const editing = ref(-1)
const confirmed = ref(false)
const inventoryBusy = ref(false)
const inventoryImage = ref('')
const inventoryNotice = ref('')
const inlineIndex = ref(-1)
const inlineField = ref('quantity')
const inlineValue = ref('')
let inlineSaving = false
const selectedShot = ref('')
const currentReport = computed(() => inventory.value.ocr_reports?.[selectedShot.value])
const shotGroups = computed(() => (inventory.value.groups || []).filter(group => group.images.length))
const counts = computed(() => reviewCounts(inventory.value.rows))
const validRows = computed(() => counts.value.valid)
const duplicateRows = computed(() => counts.value.duplicate)
const incompleteRows = computed(() => counts.value.incomplete)
const tablePage = ref(0)
const tablePages = computed(() => Math.max(1, Math.ceil(inventory.value.rows.length / 25)))
const visibleRows = computed(() => inventory.value.rows.map((row, index) => ({ row, index })).slice(tablePage.value * 25, (tablePage.value + 1) * 25))
const selectedGroupId = computed(() => shotGroups.value.find(group => group.images.includes(selectedShot.value))?.id || '')
const previewWarning = computed(() => getPreviewWarning(
  !!(inventoryImage.value || image.value), visibleRows.value.map(({ row }) => row),
  shotGroups.value.find(value => value.id === selectedGroupId.value),
))
const editableInventory = computed(() => ready.value && !state.value.busy && !inventoryBusy.value && inventory.value.phase === 'draft')
const selectedRows = ref(new Set())
const selectionAnchor = ref(null)
const inventoryScroll = ref(null)
const marquee = ref(null)
const canSelectRows = computed(() => editableInventory.value && inlineIndex.value < 0)
const selectedValidCount = computed(() => [...selectedRows.value].filter(index => inventory.value.rows[index] && !inventory.value.rows[index].invalid).length)
const selectedInvalidCount = computed(() => [...selectedRows.value].filter(index => inventory.value.rows[index]?.invalid).length)
let drag = null
let dragAnimation = 0
function clearSelection() {
  stopSelectionDrag()
  selectedRows.value = new Set()
  selectionAnchor.value = null
}
function stopSelectionDrag() {
  cancelAnimationFrame(dragAnimation)
  dragAnimation = 0
  if (drag && inventoryScroll.value?.hasPointerCapture(drag.pointerId)) inventoryScroll.value.releasePointerCapture(drag.pointerId)
  drag = null
  marquee.value = null
}
function selectOne(index, event, checkbox = false) {
  if (!canSelectRows.value) return
  selectedRows.value = selectRow(selectedRows.value, index, { additive: checkbox || event.ctrlKey || event.metaKey, range: event.shiftKey, anchor: selectionAnchor.value, visible: visibleRows.value.map(value => value.index) })
  if (!event.shiftKey || selectionAnchor.value === null) selectionAnchor.value = index
}
function localPoint(clientX, clientY) {
  const host = inventoryScroll.value, bounds = host.getBoundingClientRect()
  return { x: Math.max(0, Math.min(host.clientWidth, clientX - bounds.left)) + host.scrollLeft, y: Math.max(0, Math.min(host.clientHeight, clientY - bounds.top)) + host.scrollTop }
}
function updateSelectionDrag() {
  if (!drag?.active) return
  const host = inventoryScroll.value, bounds = host.getBoundingClientRect()
  const edge = 28
  const scroll = drag.clientY < bounds.top + edge ? -12 : drag.clientY > bounds.bottom - edge ? 12 : 0
  if (scroll) host.scrollTop += scroll
  const rect = selectionRect(drag.start, localPoint(drag.clientX, drag.clientY))
  const rows = [...host.querySelectorAll('tbody tr[data-row-index]')].map(row => {
    const box = row.getBoundingClientRect()
    return { index: Number(row.dataset.rowIndex), left: box.left - bounds.left + host.scrollLeft, right: box.right - bounds.left + host.scrollLeft, top: box.top - bounds.top + host.scrollTop, bottom: box.bottom - bounds.top + host.scrollTop }
  })
  selectedRows.value = selectRectangle(drag.before, rowsInRect(rect, rows), drag.additive)
  marquee.value = { left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.right - rect.left}px`, height: `${rect.bottom - rect.top}px` }
  dragAnimation = requestAnimationFrame(updateSelectionDrag)
}
function beginSelection(event) {
  if (event.button !== 0 || !canSelectRows.value || isSelectionControl(event.target)) return
  const row = event.target.closest('tbody tr[data-row-index]')
  if (!row) return
  drag = { pointerId: event.pointerId, start: localPoint(event.clientX, event.clientY), clientX: event.clientX, clientY: event.clientY, initialX: event.clientX, initialY: event.clientY, index: Number(row.dataset.rowIndex), additive: event.ctrlKey || event.metaKey, shift: event.shiftKey, before: new Set(selectedRows.value), active: false }
  inventoryScroll.value.setPointerCapture(event.pointerId)
  event.preventDefault()
}
function moveSelection(event) {
  if (!drag || event.pointerId !== drag.pointerId) return
  drag.clientX = event.clientX; drag.clientY = event.clientY
  if (!drag.active && Math.hypot(event.clientX - drag.initialX, event.clientY - drag.initialY) >= 5) {
    drag.active = true
    selectionAnchor.value = drag.index
    updateSelectionDrag()
  }
}
function endSelection(event) {
  if (!drag || event.pointerId !== drag.pointerId) return
  if (!drag.active) selectOne(drag.index, { ctrlKey: drag.additive, shiftKey: drag.shift })
  stopSelectionDrag()
}
function cancelSelectionDrag() {
  if (drag) selectedRows.value = drag.before
  stopSelectionDrag()
}
async function markSelected(invalid) {
  if (!canSelectRows.value || !selectedRows.value.size) return
  const indexes = [...selectedRows.value].filter(index => !!inventory.value.rows[index]).sort((a, b) => a - b)
  if (await inventoryAct(invalid ? 'invalidate_many' : 'restore_many', { indexes })) {
    clearSelection(); confirmed.value = false
  }
}
watch([tablePage, selectedGroupId], () => {
  clearSelection()
  if (inventoryScroll.value) inventoryScroll.value.scrollTop = 0
}, { flush: 'sync' })
watch(canSelectRows, value => { if (!value) stopSelectionDrag() })
let timer
let polling = false
let closing = false
let pendingActions = 0
let lastFrame = ''
let frameRevision = 0
let lastResetVersion = 0
const labels = { disconnected: '未连接', connecting: '连接中', connected: '已连接', stopped: '已停止', error: '需检查' }
const canOperate = computed(() => ready.value && !state.value.offline && !state.value.busy && state.value.status === 'connected' && !state.value.stopped)
const canInput = computed(() => canOperate.value && !state.value.read_only && !!state.value.frame)
const connectionDisabled = computed(() => !ready.value || state.value.offline || state.value.busy || !form.adb_path || !form.address)
const autoStarting = ref(false)
const canAutoInventory = computed(() => !!state.value.inventory_automation && ready.value && !state.value.offline && !state.value.busy && !inventoryBusy.value && !autoStarting.value && inlineIndex.value < 0 && !!form.adb_path && !!form.address)
const finishBlockReason = computed(() => getFinishBlockReason({
  busy: state.value.busy || inventoryBusy.value,
  phase: inventory.value.phase,
  captureMode: inventory.value.capture_mode,
  captureComplete: state.value.auto_capture?.capture_complete,
  valid: validRows.value,
  editing: editing.value >= 0 || inlineIndex.value >= 0,
  incomplete: incompleteRows.value,
  reports: inventory.value.ocr_reports,
  confirmed: confirmed.value,
}))
const autoCaptureSummary = computed(() => {
  const capture = state.value.auto_capture
  if (!capture || typeof capture !== 'object') return ''
  const phases = { starting: '正在检查准备情况', rewinding: '正在返回背包顶部', running: '采集中', capturing: '正在截图和识别', scrolling: '正在翻页', recognizing: '正在识别', completed: '采集结束，请核对', review: '采集结束，请核对', stopped: '采集已停止', error: '采集遇到问题' }
  const pages = Array.isArray(capture.pages) ? capture.pages.length : capture.pages
  return [phases[capture.phase] || '正在处理，请查看下方提示', pages !== undefined && pages !== null ? `已采集 ${pages} 页` : '', capture.message].filter(Boolean).join(' · ')
})
async function startAutoInventory() {
  if (!canAutoInventory.value) return
  autoStarting.value = true
  confirmed.value = false
  inventoryNotice.value = ''
  inventoryImage.value = ''
  clearSelection()
  try { await act('auto_inventory', form.adb_path, form.address) }
  finally { autoStarting.value = false }
}

async function refresh() {
  if (closing || polling || !window.pywebview?.api) return
  polling = true
  window.__m4bIdle = false
  try {
    const next = await window.pywebview.api.get_state(lastFrame)
    if (error.value === '界面暂时无法连接程序，正在重试；若持续失败请重新打开') error.value = ''
    if (next.reset_version !== undefined && next.reset_version !== lastResetVersion) {
      lastResetVersion = next.reset_version
      frameRevision += 1
      inventoryImage.value = ''; image.value = ''; lastFrame = ''; selectedShot.value = ''
      item.name = ''; item.quantity = ''; inlineIndex.value = -1; editing.value = -1
      confirmed.value = false; tablePage.value = 0
      clearSelection()
    }
    if (!ready.value) Object.assign(form, next.settings)
    if (next.frame?.data) {
      frameRevision += 1
      inventoryImage.value = ''
      image.value = next.frame.data
      selectedShot.value = next.frame.inventory_shot || ''
      lastFrame = next.frame.frame_id
    }
    if (!next.frame) {
      image.value = ''
      lastFrame = ''
    }
    state.value = next
    if (next.inventory) {
      if (next.inventory.rows.length > inventory.value.rows.length) tablePage.value = Math.floor((next.inventory.rows.length - 1) / 25)
      inventory.value = next.inventory
      tablePage.value = Math.min(tablePage.value, tablePages.value - 1)
      if (!next.inventory.rows.length && !next.inventory.screenshots.length) {
        inventoryImage.value = ''; selectedShot.value = ''
      }
    }
    ready.value = true
    window.__m4bReady = true
  } catch {
    error.value = '界面暂时无法连接程序，正在重试；若持续失败请重新打开'
  } finally {
    polling = false
    window.__m4bIdle = pendingActions === 0
  }
}
async function inventoryAct(action, ...args) {
  if (inventoryBusy.value || closing) return false
  inventoryBusy.value = true
  const startingFrameRevision = frameRevision
  pendingActions += 1
  window.__m4bIdle = false
  error.value = ''
  try {
    const result = await window.pywebview.api.inventory_action(action, ...args)
    if (action === 'preview' && !previewIsCurrent(startingFrameRevision, frameRevision)) return false
    if (!result.ok) { error.value = result.error; return false }
    inventory.value = result.inventory
    if (result.image) inventoryImage.value = result.image
    if (action === 'preview') selectedShot.value = args[0]
    if (action === 'import') selectedShot.value = result.inventory.screenshots.at(-1)
    if (action === 'finish') {
      clearSelection()
      inventoryImage.value = ''
      image.value = ''
      lastFrame = ''
      selectedShot.value = ''
      inventoryNotice.value = `CSV已保存：${result.inventory.csv_path}；本次临时截图已删除。`
    }
    if (action === 'reset') {
      clearSelection()
      inventoryImage.value = ''; image.value = ''; lastFrame = ''; selectedShot.value = ''
      item.name = ''; item.quantity = ''; inlineIndex.value = -1; confirmed.value = false
      inventoryNotice.value = '本轮识别记录和临时截图已重置。'
      tablePage.value = 0
    }
    return true
  } catch {
    error.value = '记录操作未得到确认，草稿和截图保留，请核查后重试'
    return false
  } finally {
    inventoryBusy.value = false
    pendingActions -= 1
    window.__m4bIdle = pendingActions === 0 && !polling
  }
}
async function changeTablePage(nextPage) {
  if (nextPage < 0 || nextPage >= tablePages.value || inlineIndex.value >= 0 || inventoryBusy.value || state.value.busy) return
  tablePage.value = nextPage
  const pageRows = inventory.value.rows.slice(nextPage * 25, (nextPage + 1) * 25)
  const group = matchingGroup(pageRows, shotGroups.value)
  inventoryImage.value = ''; image.value = ''; selectedShot.value = ''
  if (group) await inventoryAct('preview', group.selected || group.images.at(-1))
}
async function viewGroup(groupId) {
  if (inlineIndex.value >= 0) return
  const group = shotGroups.value.find(value => value.id === groupId)
  if (!group) return
  const index = inventory.value.rows.findIndex(row => group.images.includes(row.grid_page))
  if (index >= 0) tablePage.value = Math.floor(index / 25)
  inventoryImage.value = ''; image.value = ''; selectedShot.value = ''
  await inventoryAct('preview', group.selected || group.images.at(-1))
}
async function importScreenshot(event) {
  const file = event.target.files?.[0]
  if (!file) return
  if (file.size > 15000000) { error.value = '请选择小于15MB的截图'; return }
  const reader = new FileReader()
  reader.onload = async () => { await inventoryAct('import', reader.result); event.target.value = '' }
  reader.onerror = () => { error.value = '截图文件读取失败' }
  reader.readAsDataURL(file)
}
async function saveItem() {
  const action = editing.value < 0 ? 'add' : 'update'
  const args = editing.value < 0 ? [item.name, item.quantity] : [editing.value, item.name, item.quantity]
  if (await inventoryAct(action, ...args)) {
    item.name = ''; item.quantity = ''; editing.value = -1; confirmed.value = false
  }
}
function editItem(index, row) {
  editing.value = index
  Object.assign(item, row)
  confirmed.value = false
}
async function editCell(index, row, field = 'quantity') {
  if (!editableInventory.value || inlineIndex.value >= 0) return
  inlineIndex.value = index
  inlineField.value = field
  inlineValue.value = row[field]
  confirmed.value = false
  await nextTick()
  const input = document.querySelector('[data-testid="inline-editor"]')
  input?.focus()
  input?.select()
}
async function saveCell() {
  if (inlineIndex.value < 0 || inlineSaving) return
  inlineSaving = true
  try {
    if (await inventoryAct('cell', inlineIndex.value, inlineField.value, inlineValue.value)) inlineIndex.value = -1
  } finally { inlineSaving = false }
}
function cancelCell() { inlineIndex.value = -1 }
async function removeItem(index) {
  const action = inventory.value.rows[index].invalid ? 'restore' : 'remove'
  if (await inventoryAct(action, index)) {
    editing.value = -1; item.name = ''; item.quantity = ''; confirmed.value = false
  }
}
async function act(name, ...args) {
  if (closing) return
  pendingActions += 1
  window.__m4bIdle = false
  error.value = ''
  try {
    const result = await window.pywebview.api[name](...args)
    if (!result.ok) error.value = result.error
    await refresh()
  } catch {
    error.value = '操作未得到确认，请停止并检查'
  } finally {
    pendingActions -= 1
    window.__m4bIdle = pendingActions === 0 && !polling
  }
}
function dispose() {
  stopSelectionDrag()
  closing = true
  clearInterval(timer)
  window.removeEventListener('pywebviewready', boot)
}
function boot() {
  refresh()
  timer = setInterval(refresh, 400)
}
onMounted(() => {
  window.__m4bDispose = dispose
  window.addEventListener('pagehide', dispose, { once: true })
  if (window.pywebview?.api) boot()
  else window.addEventListener('pywebviewready', boot, { once: true })
})
onBeforeUnmount(() => {
  dispose()
  window.removeEventListener('pagehide', dispose)
})
</script>

<template>
  <div class="shell" :class="{ 'inventory-shell': state.manual_inventory }">
    <header>
      <div><p class="eyebrow">MAA FOR BHC</p><h1>百货城小助手</h1></div>
      <span class="status" :class="state.status" data-testid="status">{{ state.manual_inventory ? '背包记录 · ' : '' }}{{ labels[state.status] || '未连接' }}</span>
      <button class="stop" data-action="stop" :disabled="!ready" @click="act('stop')">停止</button>
    </header>
    <p v-if="state.inventory_automation" class="offline">背包采集 · 固定630×1120；自动浏览普通道具并截图，随时点击“停止”。</p>
    <p v-else-if="state.inventory_capture" class="offline">手动背包统计 · 你操作游戏，点击“截图并识别”后临时入库、本地OCR；不点击或翻页。</p>
    <p v-else-if="state.manual_inventory" class="offline">手动背包统计 · 你操作游戏，本应用只记录，不发送设备指令。</p>
    <p v-else-if="state.offline" class="offline">离线检查 · 设备操作已禁用</p>
    <p v-else-if="state.read_only" class="offline">只读验证 · 仅连接和截图</p>
    <div v-if="state.manual_inventory" class="manual-layout">
      <section class="panel">
        <div v-if="state.inventory_capture" class="inventory-connection">
          <h2>连接与手动截图</h2>
          <label>ADB路径<input v-model="form.adb_path" :disabled="state.busy || state.offline" placeholder="MuMu adb.exe完整路径"></label>
          <label>连接地址<input v-model="form.address" :disabled="state.busy || state.offline" placeholder="127.0.0.1:端口"></label>
          <div class="actions"><button data-action="connect" :disabled="connectionDisabled || inventoryBusy || inlineIndex >= 0" @click="act('connect', form.adb_path, form.address)">连接</button><button class="primary" data-action="screenshot" :disabled="!canOperate || !editableInventory || editing >= 0 || inlineIndex >= 0" @click="confirmed = false; inventoryImage = ''; act('screenshot')">截图并识别</button></div>
          <p class="hint">OCR在中间区域逐图定位五排，半露卡片不计入；翻页由你操作。</p>
        </div>
        <div v-if="state.inventory_automation" class="auto-capture-panel">
          <div class="auto-capture-controls"><button class="primary" data-action="auto-inventory" :disabled="!canAutoInventory" @click="startAutoInventory">{{ autoStarting ? '正在开始…' : '自动采集背包' }}</button><span>630×1120 · 普通道具</span></div>
          <p>自动滑动并截图；采集结束后待核对，不自动保存正式CSV或清理截图。</p>
          <p v-if="autoCaptureSummary" class="auto-capture-progress" data-testid="auto-capture-status" aria-live="polite" :title="autoCaptureSummary">{{ autoCaptureSummary }}</p>
        </div>
        <h2>按背包顺序记录 · 每页5×5＝25格</h2>
        <p class="hint record-count">有效{{ validRows }}条 · 其中{{ incompleteRows }}条缺名称或数量 · 无效{{ inventory.rows.length - validRows }}条<span v-if="duplicateRows"> · 疑似重复{{ duplicateRows }}条（已排除，需核对）</span></p>
        <p v-if="state.inventory_capture" class="hint">识别失败自动重新截图、识别最多2次；期间请保持当前页不动。</p>
        <p class="hint exclusion-hint">活动道具和（待）合成道具暂不统计。数量按画面原样填写；翻页重复项不累加。</p>
        <form class="inventory-form" @submit.prevent="saveItem">
          <label>道具名称<input v-model="item.name" :disabled="!editableInventory" required maxlength="100" placeholder="补记道具名称"></label>
          <label>数量<input v-model="item.quantity" :disabled="!editableInventory" required maxlength="40" placeholder="数量"></label>
          <button class="primary" data-action="add-inventory" :disabled="!editableInventory">{{ editing < 0 ? '追加到末尾' : '保存该行' }}</button>
          <button v-if="editing >= 0" type="button" @click="editing = -1; item.name = ''; item.quantity = ''">取消修改</button>
        </form>
        <div class="table-pagination"><button :disabled="tablePage === 0 || inlineIndex >= 0 || inventoryBusy || state.busy" @click="changeTablePage(tablePage - 1)">上一页</button><span>第{{ tablePage + 1 }} / {{ tablePages }}页 · 每页25条</span><button :disabled="tablePage >= tablePages - 1 || inlineIndex >= 0 || inventoryBusy || state.busy" @click="changeTablePage(tablePage + 1)">下一页</button></div>
        <div class="selection-toolbar" data-testid="selection-toolbar">
          <span aria-live="polite">已选 {{ selectedRows.size }} 条</span>
          <button data-action="invalidate-selected" :disabled="!canSelectRows || !selectedValidCount" @click="markSelected(true)">标记无效</button>
          <button data-action="restore-selected" :disabled="!canSelectRows || !selectedInvalidCount" @click="markSelected(false)">恢复</button>
          <button data-action="clear-selection" :disabled="!selectedRows.size" @click="clearSelection">取消选择</button>
          <span class="selection-hint" title="从序号或空白处拖动框选；Ctrl可累加，Shift可连续选择。">拖动框选 · Ctrl多选</span>
        </div>
        <div ref="inventoryScroll" class="inventory-scroll" :class="{ 'is-selecting': marquee }" @pointerdown="beginSelection" @pointermove="moveSelection" @pointerup="endSelection" @pointercancel="cancelSelectionDrag">
          <table data-testid="inventory-table"><thead><tr><th class="selection-column"><span class="sr-only">选择</span></th><th>顺序</th><th>道具名称</th><th>数量</th><th>操作</th></tr></thead>
            <tbody><tr v-for="({ row, index }) in visibleRows" :key="index" :data-row-index="index" :aria-selected="selectedRows.has(index)" :class="{ 'invalid-row': row.invalid, 'selected-row': selectedRows.has(index) }">
              <td class="selection-column"><input type="checkbox" :checked="selectedRows.has(index)" :aria-label="`选择第${index + 1}条`" :disabled="!canSelectRows" @click="selectOne(index, $event, true)"></td>
              <td>{{ index + 1 }}</td>
              <td><input v-if="inlineIndex === index && inlineField === 'name'" v-model="inlineValue" data-testid="inline-editor" class="inline-editor" aria-label="修改道具名称" :disabled="inventoryBusy" @keydown.enter.prevent="saveCell" @keydown.esc.prevent="cancelCell" @blur="saveCell"><button v-else class="name-cell" :title="row.invalid_reason === 'duplicate' ? '疑似重复，已暂时排除；请对照截图核对名称和数量' : '点击修改名称'" :disabled="!editableInventory || inlineIndex >= 0" @click="editCell(index, row, 'name')">{{ row.name || '待识别名称' }}{{ row.invalid_reason === 'duplicate' ? '（疑似重复）' : '' }}</button></td>
              <td>{{ row.quantity === '' || row.quantity == null ? '待核对' : row.quantity }}</td>
              <td class="row-actions"><input v-if="inlineIndex === index && inlineField === 'quantity'" v-model="inlineValue" data-testid="inline-editor" class="inline-editor" aria-label="修改道具数量" inputmode="decimal" :disabled="inventoryBusy" @keydown.enter.prevent="saveCell" @keydown.esc.prevent="cancelCell" @blur="saveCell"><button v-else :disabled="!editableInventory || inlineIndex >= 0 || row.invalid" @click="editCell(index, row)">修改</button><button :disabled="!editableInventory || inlineIndex >= 0" @click="removeItem(index)">{{ row.invalid ? '恢复' : '标记无效' }}</button></td>
            </tr></tbody>
          </table>
        <div v-if="marquee" class="selection-marquee" :style="marquee" aria-hidden="true"></div>
        <p v-if="!inventory.rows.length" class="hint">尚未记录道具。截图后本地识别；也可手动补记，草稿自动保存。</p>
        </div>
        <p v-if="finishBlockReason && inventory.phase !== 'completed'" class="hint record-count" role="status">{{ finishBlockReason }}</p>
        <label class="confirmation"><input v-model="confirmed" type="checkbox" :disabled="!editableInventory || editing >= 0 || inlineIndex >= 0">我已完成本次记录，核对顺序和数量，并跳过活动及（待）合成道具。</label>
        <button class="primary" data-action="finish-inventory" :disabled="!!finishBlockReason" @click="inventoryAct('finish', true)">{{ inventory.phase === 'exported' ? 'CSV已保存，重试清理临时截图' : '完成：保存CSV并删除本次临时截图' }}</button>
        <p class="hint csv-location" :title="inventory.csv_path">CSV：{{ inventory.csv_path || 'data/inventory.csv' }}</p>
        <p v-if="inventory.phase === 'completed' || inventoryNotice" class="hint">{{ inventoryNotice || '本次记录已完成，CSV已保存，临时截图已清理。' }}</p>
        <div class="developer-reset"><button data-action="reset-inventory" title="清空本轮记录与临时图，保留历史/参考图/已导出CSV；也可双击根目录的reset-inventory.cmd。" :disabled="!ready || inventoryBusy || inlineIndex >= 0" @click="inventoryAct('reset')">开发重置：清空本轮记录和截图</button></div>
      </section>
      <section class="panel preview">
        <h2>本次截图组（{{ shotGroups.length }}）</h2>
        <label v-if="!state.inventory_capture" class="import-label">导入手动截图<input data-action="import-inventory" type="file" accept="image/png,image/jpeg" :disabled="!editableInventory" @change="importScreenshot"></label>
        <div class="shot-list"><select :value="selectedGroupId" :disabled="inventoryBusy || state.busy || inlineIndex >= 0" @change="viewGroup($event.target.value)"><option value="" disabled>选择截图组</option><option v-for="(group, index) in shotGroups" :key="group.id" :value="group.id">第{{ index + 1 }}组 · {{ group.images.length }}次识别{{ inventory.ocr_reports?.[group.selected]?.status === 'pending' ? ' · 待核对' : '' }}</option></select></div>
        <p v-if="previewWarning" class="hint" role="status">{{ previewWarning }}</p>
        <div class="canvas"><img v-if="inventoryImage || image" :src="inventoryImage || image" alt="本次临时背包截图"><p v-else class="hint">{{ shotGroups.length ? '尚未显示截图，请选择截图组核对。' : (state.inventory_automation ? '开始采集后，这里会显示背包截图。' : state.inventory_capture ? '连接后点击“截图并识别”，这里会显示截图。' : '导入截图后，对照填写名称和数量。') }}</p></div>
        <p v-if="currentReport" class="hint">{{ currentReport.message }}</p>
        <button v-if="currentReport?.status === 'pending'" :disabled="!editableInventory || editing >= 0" @click="inventoryAct('review', selectedShot)">本图已手动补记或确认跳过</button>
      </section>
    </div>
    <main v-else>
      <section class="controls">
        <div class="panel">
          <h2>连接模拟器</h2>
          <label>ADB路径<input v-model="form.adb_path" placeholder="选择MuMu的adb.exe完整路径" :disabled="state.busy || state.offline" autocomplete="off"></label>
          <label>连接地址<input v-model="form.address" placeholder="127.0.0.1:端口" :disabled="state.busy || state.offline" autocomplete="off"></label>
          <button class="primary" data-action="connect" :disabled="connectionDisabled" @click="act('connect', form.adb_path, form.address)">连接</button>
        </div>
        <div class="panel">
          <h2>基本操作</h2>
          <div class="actions">
            <button data-action="screenshot" :disabled="!canOperate" @click="act('screenshot')">截图</button>
            <button data-action="click" :disabled="!canInput" @click="act('click', form.x, form.y)">点击</button>
            <button data-action="swipe" :disabled="!canInput" @click="act('swipe', form.x, form.y, form.x2, form.y2, form.duration)">滑动</button>
          </div>
          <div class="coordinates">
            <label>X<input v-model.number="form.x" type="number" min="0" step="1" :disabled="!canInput"></label>
            <label>Y<input v-model.number="form.y" type="number" min="0" step="1" :disabled="!canInput"></label>
          </div>
          <div class="coordinates">
            <label>终点X<input v-model.number="form.x2" type="number" min="0" step="1" :disabled="!canInput"></label>
            <label>终点Y<input v-model.number="form.y2" type="number" min="0" step="1" :disabled="!canInput"></label>
          </div>
          <label>滑动时长（毫秒）<input v-model.number="form.duration" type="number" min="100" max="3000" step="100" :disabled="!canInput"></label>
          <p class="hint">先截图核对页面。坐标以实际截图为准。</p>
        </div>
      </section>
      <section class="panel preview">
        <div class="preview-title"><h2>游戏画面</h2><span v-if="state.frame">{{ state.frame.width }} × {{ state.frame.height }}</span></div>
        <div class="canvas">
          <img v-if="image" :src="image" alt="最近一次手动采集的游戏截图">
          <div v-else class="empty"><div class="empty-icon">▯</div><p>尚无截图</p><small>连接模拟器后，点击“截图”</small></div>
        </div>
        <p v-if="state.frame" class="hint">读取于 {{ state.frame.time }}</p>
      </section>
    </main>
    <footer aria-live="polite" :title="state.message"><span v-if="state.busy" class="spinner"></span>{{ state.message }}</footer>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
  </div>
</template>

