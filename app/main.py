import argparse
import hashlib
import json
import logging
import os
import sys
import threading
import time
import tempfile
from datetime import datetime

from .config import LOGS, ROOT, RUNTIME, prepare_paths


def main():
    parser = argparse.ArgumentParser(description="MAA for BHC")
    parser.add_argument("--offline", action="store_true", help="禁止设备操作，仅检查窗口")
    parser.add_argument("--smoke-test", action="store_true", help="离线窗口与桥接检查后自动关闭")
    parser.add_argument("--read-only", action="store_true", help="仅允许连接与截图")
    parser.add_argument("--manual-inventory", action="store_true", help="手动背包统计，不发送设备指令")
    parser.add_argument("--inventory-capture", action="store_true", help="手动截图入库并本地OCR；禁止游戏输入")
    parser.add_argument("--capture-check", action="store_true", help="执行获批的只读连接/截图及界面显示核查")
    parser.add_argument("--adb-path", default="")
    parser.add_argument("--address", default="")
    args = parser.parse_args()
    if (args.manual_inventory or args.inventory_capture) and args.capture_check:
        parser.error("手动统计不能与设备截图核查同时使用")
    if args.capture_check and (args.offline or args.smoke_test or not args.adb_path or not args.address):
        parser.error("截图核查需指定ADB路径和地址，不能与离线检查同时使用")
    prepare_paths()
    logging.basicConfig(
        filename=str(LOGS / "app.log"), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s", encoding="utf-8",
    )
    page = ROOT / "ui" / "dist" / "index.html"
    if not page.is_file():
        raise SystemExit("界面尚未构建，请先运行scripts/setup.ps1")
    # WebView2 keeps its project-local profile across launches. A build-specific
    # document path prevents an older index.html from loading a stale UI bundle.
    html = page.read_bytes()
    page = page.with_name("view-" + hashlib.sha256(html).hexdigest()[:12] + ".html")
    if not page.exists():
        page.write_bytes(html)
    import webview
    from .bridge import Bridge

    offline = args.offline or args.smoke_test or (args.manual_inventory and not args.inventory_capture)
    inventory_lease = None
    if (args.manual_inventory or args.inventory_capture) and not args.smoke_test:
        from .reset import SessionLease
        inventory_lease = SessionLease()
        if not inventory_lease.acquire():
            raise SystemExit("本项目已有背包记录窗口，请先关闭旧窗口")
    bridge = Bridge(offline=offline, read_only=args.read_only or args.capture_check or args.manual_inventory,
                    manual_inventory=args.manual_inventory, inventory_capture=args.inventory_capture)
    validation_directory = None
    if args.smoke_test and bridge._manual_inventory:
        from .inventory import ManualInventory
        validation_directory = tempfile.TemporaryDirectory(dir=ROOT / ".cache/tmp")
        bridge._inventory = ManualInventory(validation_directory.name)
        bridge._auto_capture = None
    if args.capture_check or (args.inventory_capture and args.adb_path and args.address):
        bridge._settings = {"adb_path": args.adb_path, "address": args.address}
    window = webview.create_window(
        "MAA for BHC", str(page), js_api=bridge,
        width=1200 if bridge._manual_inventory else 900,
        height=820 if bridge._manual_inventory else 790,
        min_size=(1000, 680) if bridge._manual_inventory else (700, 600),
        text_select=False,
    )
    window.events.closed += bridge.shutdown
    smoke_result = {"ok": False, "mode": "offline", "checked_at": datetime.now().astimezone().isoformat()}
    smoke_finished = threading.Event()

    def invoke_bridge(script):
        completed = threading.Event()
        reply = {}

        def receive(value):
            reply["value"] = value
            completed.set()

        window.evaluate_js(script, callback=receive)
        if not completed.wait(10):
            raise RuntimeError("界面指令未得到确认")
        return reply["value"]

    def capture_check():
        result = {"ok": False, "mode": "read_only", "address": args.address,
                  "checked_at": datetime.now().astimezone().isoformat()}
        try:
            deadline = time.monotonic() + 25
            while not window.evaluate_js("Boolean(window.__m4bReady)"):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Vue页面未就绪")
                time.sleep(0.1)
            connect_script = "window.pywebview.api.connect(" + json.dumps(args.adb_path) + "," + json.dumps(args.address) + ")"
            accepted = invoke_bridge(connect_script)
            if not accepted or not accepted.get("ok"):
                raise RuntimeError("连接请求未被接受：" + str(accepted))
            deadline = time.monotonic() + 60
            while bridge.get_state()["busy"]:
                if time.monotonic() >= deadline:
                    bridge.stop()
                    raise RuntimeError("连接超时，已阻止后续操作")
                time.sleep(0.1)
            state = bridge.get_state()
            if state["status"] != "connected":
                raise RuntimeError(state["message"])
            accepted = invoke_bridge("window.pywebview.api.screenshot()")
            if not accepted or not accepted.get("ok"):
                raise RuntimeError("截图请求未被接受：" + str(accepted))
            deadline = time.monotonic() + 30
            while bridge.get_state()["busy"]:
                if time.monotonic() >= deadline:
                    bridge.stop()
                    raise RuntimeError("截图超时，已阻止后续操作")
                time.sleep(0.1)
            state = bridge.get_state()
            frame = state["frame"]
            if state["status"] != "connected" or not frame:
                raise RuntimeError(state["message"])
            deadline = time.monotonic() + 10
            while True:
                display = window.evaluate_js("""(() => {
                  const image = document.querySelector('.canvas img');
                  return {
                    loaded: Boolean(image && image.complete && image.naturalWidth > 0),
                    width: image ? image.naturalWidth : 0,
                    height: image ? image.naturalHeight : 0,
                    inputsDisabled: ['click','swipe'].every(name => document.querySelector('[data-action="'+name+'"]').disabled),
                    status: document.querySelector('[data-testid="status"]').textContent,
                    readOnly: document.body.textContent.includes('只读验证')
                  };
                })()""")
                if display["loaded"] and display["width"] == frame["width"] and display["height"] == frame["height"]:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("截图已读取但Vue显示未通过核查")
                time.sleep(0.1)
            if not display["inputsDisabled"] or not display["readOnly"]:
                raise RuntimeError("只读输入限制未通过核查")
            result.update(ok=True, frame={key: value for key, value in frame.items() if key != "data"},
                          display=display, screenshot_path="runtime/screenshots/" + frame["frame_id"] + ".png",
                          input_backend="MaaAdbInputMethodEnum.Null", screencap_backend="Encode")
        except Exception as error:
            bridge.stop()
            result["error"] = str(error)
            logging.exception("只读连接截图核查失败")
        finally:
            (LOGS / "capture-check55.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def smoke_check():
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if window.evaluate_js("Boolean(window.__m4bReady)"):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Vue页面或Python桥接未就绪")
            snapshot = window.evaluate_js("""(() => ({
              manual: Boolean(document.querySelector('.inventory-shell')),
              hasCaptureOrImport: Boolean(document.querySelector('[data-action="import-inventory"]') || document.querySelector('[data-action="screenshot"]')),
              hasTable: Boolean(document.querySelector('[data-testid="inventory-table"]')),
              excluded: document.body.textContent.includes('活动道具和（待）合成道具暂不统计'),
              expectedDeviceControls: document.querySelector('[data-action="screenshot"]')
                ? Boolean(document.querySelector('[data-action="connect"]') && document.querySelector('[data-action="screenshot"]').disabled)
                : !document.querySelector('[data-action="connect"]'),
              hasFinish: Boolean(document.querySelector('[data-action="finish-inventory"]')),
              hasReset: Boolean(document.querySelector('[data-action="reset-inventory"]')),
              groupedGallery: document.body.textContent.includes('本次截图组'),
              automaticEntry: !document.querySelector('[data-action="screenshot"]') || Boolean(document.querySelector('[data-action="auto-inventory"]')?.disabled),
              noGameInput: !document.querySelector('[data-action="click"]') && !document.querySelector('[data-action="swipe"]')
            }))()""" if args.manual_inventory or args.inventory_capture else """(() => ({
              title: document.querySelector('h1').textContent,
              status: document.querySelector('[data-testid="status"]').textContent,
              disabled: ['connect','screenshot','click','swipe'].every(
                name => document.querySelector('[data-action="'+name+'"]').disabled),
              hasPreview: Boolean(document.querySelector('.canvas')),
              hasStop: !document.querySelector('[data-action="stop"]').disabled,
              offline: document.body.textContent.includes('离线检查')
            }))()""")
            if args.manual_inventory or args.inventory_capture:
                if not all(snapshot.values()):
                    raise RuntimeError("背包记录窗口未达到预期：" + json.dumps(snapshot, ensure_ascii=False))
                if bridge.connect("", "")["ok"] or bridge.screenshot()["ok"] or bridge.click(1, 1)["ok"]:
                    raise RuntimeError("手动记录模式设备禁用核查失败")
                if bridge.auto_inventory()["ok"]:
                    raise RuntimeError("离线检查不得启动真实自动采集")
                with bridge._lock:
                    for index in range(25):
                        bridge._inventory.add("界面测试道具" + str(index + 1), "1")
                deadline = time.monotonic() + 5
                while not window.evaluate_js("Boolean(document.querySelector('[data-testid=inventory-table] tbody button'))"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("测试行未显示")
                    time.sleep(0.05)
                window.evaluate_js("[...document.querySelectorAll('[data-testid=inventory-table] tbody button')].find(button => button.textContent === '修改').click()")
                deadline = time.monotonic() + 5
                while not window.evaluate_js("Boolean(document.querySelector('[data-testid=inline-editor]'))"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("原位编辑框未显示")
                    time.sleep(0.05)
                window.evaluate_js("""(() => {
                    const input = document.querySelector('[data-testid=inline-editor]');
                    input.value = '27'; input.dispatchEvent(new Event('input', {bubbles:true}));
                    input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
                })()""")
                deadline = time.monotonic() + 5
                while bridge._inventory.rows[0]["quantity"] != "27" or window.evaluate_js("Boolean(document.querySelector('[data-testid=inline-editor]'))"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("原位输入并回车保存未通过")
                    time.sleep(0.05)
                snapshot["inlineQuantityEdit"] = True
                window.evaluate_js("[...document.querySelectorAll('[data-testid=inventory-table] tbody button')].find(button => button.textContent === '标记无效').click()")
                deadline = time.monotonic() + 5
                while not bridge._inventory.rows[0].get("invalid"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("无效标记未通过界面生效")
                    time.sleep(.05)
                snapshot["invalidMarker"] = True
                layout = window.evaluate_js("""(() => {
                    const table = document.querySelector('[data-testid=inventory-table]');
                    const frame = document.querySelector('.inventory-scroll').getBoundingClientRect();
                    const rows = [...table.querySelectorAll('tbody tr')];
                    const scroll = document.querySelector('.inventory-scroll');
                    return {rows:rows.length, tableBottom:rows.at(-1).getBoundingClientRect().bottom,
                            frameBottom:frame.bottom, viewport:innerHeight,
                            resetBottom:document.querySelector('[data-action=reset-inventory]').getBoundingClientRect().bottom,
                            rowHeight:rows[0].getBoundingClientRect().height,
                            internalScroll:scroll.scrollHeight > scroll.clientHeight && getComputedStyle(scroll).overflowY === 'auto',
                            pageScroll:document.documentElement.scrollHeight > innerHeight + 1};
                })()""")
                if layout["rows"] != 25 or layout["rowHeight"] < 32 or not layout["internalScroll"] or layout["resetBottom"] > layout["viewport"] or layout["pageScroll"]:
                    raise RuntimeError("表内滚动和固定全局布局未通过：" + json.dumps(layout))
                snapshot["fixedLayout"] = layout
                window.evaluate_js("""(() => {
                    const host = document.querySelector('.inventory-scroll'); host.scrollTop = host.scrollHeight;
                })()""")
                if not window.evaluate_js("document.querySelector('.inventory-scroll').scrollTop > 0 && scrollY === 0"):
                    raise RuntimeError("列表内部滚动未通过")
                window.evaluate_js("document.querySelector('.inventory-scroll').scrollTop = 0")
                # Dispatch a drag through Vue's actual DOM handlers, with capture
                # stubbed only because synthetic pointers have no OS pointer ID.
                window.evaluate_js("""(() => {
                    const host = document.querySelector('.inventory-scroll');
                    host.__capture = host.setPointerCapture; host.__hasCapture = host.hasPointerCapture;
                    host.setPointerCapture = () => {}; host.hasPointerCapture = () => false;
                    const cells = [...host.querySelectorAll('tbody tr')].map(row => row.cells[1]);
                    const a = cells[1].getBoundingClientRect(), b = cells[3].getBoundingClientRect();
                    cells[1].dispatchEvent(new PointerEvent('pointerdown', {bubbles:true,pointerId:99,button:0,clientX:a.left+10,clientY:a.top+10}));
                    host.dispatchEvent(new PointerEvent('pointermove', {bubbles:true,pointerId:99,clientX:b.right-4,clientY:b.top+10}));
                })()""")
                deadline = time.monotonic() + 5
                while not window.evaluate_js("document.querySelector('[data-testid=selection-toolbar]').textContent.replaceAll(' ', '').includes('已选3条')"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("鼠标框选事件未选中预期三行")
                    time.sleep(.05)
                window.evaluate_js("""(() => {
                    const host = document.querySelector('.inventory-scroll');
                    host.dispatchEvent(new PointerEvent('pointerup', {bubbles:true,pointerId:99}));
                    host.setPointerCapture = host.__capture; host.hasPointerCapture = host.__hasCapture;
                    document.querySelector('[data-action=clear-selection]').click();
                })()""")
                snapshot["marqueeSelectionEvents"] = True
                window.evaluate_js("""(() => {
                    const boxes = document.querySelectorAll('[data-testid=inventory-table] tbody input[type=checkbox]');
                    boxes[1].click(); boxes[2].click();
                })()""")
                deadline = time.monotonic() + 5
                while not window.evaluate_js("document.querySelector('[data-testid=selection-toolbar]').textContent.replaceAll(' ', '').includes('已选2条')"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("列表多选未通过")
                    time.sleep(.05)
                window.evaluate_js("document.querySelector('[data-action=invalidate-selected]').click()")
                deadline = time.monotonic() + 5
                while not all(bridge._inventory.rows[index].get('invalid') for index in (1, 2)):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("批量无效标记未生效")
                    time.sleep(.05)
                snapshot["batchSelection"] = True
                with bridge._lock:
                    for index in range(25, 50):
                        bridge._inventory.add("分页测试道具" + str(index + 1), "1")
                deadline = time.monotonic() + 5
                while not window.evaluate_js("document.querySelector('.table-pagination').textContent.includes('/ 2页')"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("分页未显示")
                    time.sleep(.05)
                window.evaluate_js("document.querySelector('.table-pagination button:first-child').click()")
                window.evaluate_js("document.querySelector('.table-pagination button:last-child').click()")
                deadline = time.monotonic() + 5
                while not window.evaluate_js("document.querySelector('[data-testid=inventory-table] tbody tr').dataset.rowIndex === '25'"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("第二页起始编号未通过")
                    time.sleep(.05)
                snapshot["pagination"] = True
                window.resize(1000, 700)
                deadline = time.monotonic() + 5
                while not window.evaluate_js("innerHeight < 720"):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("紧凑窗口尺寸未生效")
                    time.sleep(.05)
                compact = window.evaluate_js("""(() => ({
                    pageScroll:document.documentElement.scrollHeight > innerHeight + 1,
                    resetBottom:document.querySelector('[data-action=reset-inventory]').getBoundingClientRect().bottom,
                    viewport:innerHeight,
                    listHeight:document.querySelector('.inventory-scroll').clientHeight
                }))()""")
                if compact['pageScroll'] or compact['resetBottom'] > compact['viewport'] or compact['listHeight'] < 100:
                    raise RuntimeError("紧凑窗口主控被遮挡：" + json.dumps(compact))
                snapshot['compactLayout'] = compact
                # Exercise reset only on the isolated smoke-test inventory.
                window.evaluate_js("document.querySelector('[data-action=reset-inventory]').click()")
                deadline = time.monotonic() + 5
                while bridge._inventory.rows:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("隔离数据重置未完成")
                    time.sleep(.05)
                snapshot["isolatedReset"] = True
            elif not (snapshot["title"] == "百货城小助手" and snapshot["status"] == "未连接"
                    and snapshot["disabled"] and snapshot["hasPreview"] and snapshot["hasStop"] and snapshot["offline"]):
                raise RuntimeError("离线窗口内容未达到预期：" + json.dumps(snapshot, ensure_ascii=False))
            window.evaluate_js("document.querySelector('[data-action=\"stop\"]').click()")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if bridge.get_state()["status"] == "stopped":
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("停止按钮没有通过桥接生效")
            window.evaluate_js("window.__m4bDispose()")
            deadline = time.monotonic() + 5
            while not window.evaluate_js("Boolean(window.__m4bIdle)"):
                if time.monotonic() >= deadline:
                    raise RuntimeError("窗口关闭前仍有未完成的界面请求")
                time.sleep(0.05)
            if "maa.controller" in sys.modules:
                raise RuntimeError("离线检查不应导入设备控制器")
            smoke_result.update(ok=True, page=snapshot, stop_bridge=True, maa_controller_imported=False)
        except Exception as error:
            smoke_result["error"] = str(error)
            logging.exception("离线窗口检查失败")
        finally:
            (LOGS / ("inventory-window-smoke.json" if args.inventory_capture else "manual-window-smoke.json" if args.manual_inventory else "window-smoke.json")).write_text(
                json.dumps(smoke_result, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            try:
                window.destroy()
            finally:
                smoke_finished.set()

    try:
        webview.start(
            smoke_check if args.smoke_test else capture_check if args.capture_check else None,
            gui="edgechromium", debug=False,
            storage_path=str(RUNTIME / ("webview-readonly" if args.read_only or args.capture_check or args.inventory_capture else "webview")),
            private_mode=False,
        )
    finally:
        if args.smoke_test:
            smoke_finished.wait(10)
        bridge.shutdown()
        if inventory_lease:
            inventory_lease.close()
        if validation_directory:
            from pathlib import Path
            if not Path(validation_directory.name).resolve().is_relative_to((ROOT / ".cache/tmp").resolve()):
                raise RuntimeError("检查临时目录超出项目范围")
            validation_directory.cleanup()
    if args.smoke_test and not smoke_result["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

