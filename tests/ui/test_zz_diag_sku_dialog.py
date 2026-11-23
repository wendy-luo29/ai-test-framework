"""临时诊断用例：转储 SKU 选择弹窗内部状态。仅排查用，跑完即删，不属于正式用例。"""
from __future__ import annotations

import json
import time

import pytest

from pages.manual_order_page import ManualOrderPage, ShipInfo


@pytest.mark.ui
def test_diag_sku_dialog(manual_order_page: ManualOrderPage):
    page = manual_order_page
    pw = page.page

    # 记录与产品/库存相关的网络响应
    net: list[str] = []
    pw.on(
        "response",
        lambda r: net.append(f"{r.status} {r.url[:180]}")
        if any(k in r.url.lower() for k in ("product", "inventory", "sku", "combo"))
        else None,
    )
    console_errors: list[str] = []
    pw.on(
        "console",
        lambda m: console_errors.append(m.text[:300]) if m.type in ("error", "warning") else None,
    )

    page.click_new()
    page.fill_form(order_type="零售", platform_search="Lasoo", ship=ShipInfo(), remark="DIAG")

    # 主表单关键字段当前值
    main_fields = pw.evaluate(
        """() => {
            const out = {};
            for (const name of ['main.orderType','main.platformId','main.remark']) {
                const f = Ext.ComponentQuery.query('[name=' + name + ']')[0];
                if (f) out[name] = {raw: String(f.getValue()), display: f.getRawValue ? f.getRawValue() : null};
            }
            return out;
        }"""
    )
    print("\n=== MAIN FORM FIELDS ===")
    print(json.dumps(main_fields, ensure_ascii=False, indent=2))

    tool = page.locator(page.SKU_INSERT_TOOL).first
    tool.scroll_into_view_if_needed()
    tool.click()
    dialog = page.locator(page.SKU_DIALOG)
    dialog.wait_for(state="visible", timeout=15000)
    pw.wait_for_timeout(2000)

    def dump(tag: str) -> None:
        info = pw.evaluate(
            """() => {
                const w = Ext.getCmp('ProductComboInventoryDialogWinID');
                if (!w) return {window: false};
                const out = {window: true, title: String(w.title || ''), hidden: w.isHidden()};
                out.grids = w.query('gridpanel').map(g => {
                    const s = g.getStore && g.getStore();
                    const p = s && s.getProxy && s.getProxy();
                    return {
                        id: g.id,
                        hidden: g.isHidden ? g.isHidden() : null,
                        storeCount: s ? s.getCount() : null,
                        storeLoading: s ? s.isLoading() : null,
                        proxyType: p ? p.type : null,
                        proxyUrl: p && p.url ? String(p.url) : null,
                        columns: (g.headerCt ? g.headerCt.getGridColumns() : [])
                            .map(c => ({text: c.text, hidden: !!c.hidden})),
                    };
                });
                const el = w.el && w.el.dom;
                out.htmlHead = el ? el.innerHTML.slice(0, 3000) : null;
                out.fields = w.query('textfield').map(f => ({name: f.name, value: String(f.getValue())}));
                return out;
            }"""
        )
        print(f"\n=== DIALOG DUMP ({tag}) ===")
        print(json.dumps(info, ensure_ascii=False, indent=2)[:6000])

    dump("after-open")

    # 与正式用例一致：点弹窗内「查询」
    dialog.locator("a.x-btn:visible").filter(has_text="查询").first.click()

    # 轮询 store 状态，观察 comboInventoryList 是否最终返回
    req_times: dict[str, float] = {}
    pw.on(
        "request",
        lambda r: req_times.setdefault(r.url, time.time())
        if "comboInventoryList" in r.url
        else None,
    )

    def on_resp(r):
        if "comboInventoryList" in r.url:
            started = req_times.get(r.url)
            took = f"{time.time() - started:.1f}s" if started else "?"
            try:
                body = r.text()[:400]
            except Exception as e:
                body = f"<body unavailable: {e}>"
            net.append(f"{r.status} {r.url[:120]} took={took} body={body!r}")

    pw.on("response", on_resp)

    t0 = time.time()
    while time.time() - t0 < 150:
        st = pw.evaluate(
            """() => {
                const g = Ext.getCmp('ProductComboInventoryDialogWinGridPanelID');
                const s = g && g.getStore && g.getStore();
                return s ? {loading: s.isLoading(), count: s.getCount()} : null;
            }"""
        )
        elapsed = int(time.time() - t0)
        if st is None:
            print(f"[{elapsed}s] grid/store 不可用")
            break
        print(f"[{elapsed}s] storeLoading={st['loading']} storeCount={st['count']}", flush=True)
        if not st["loading"]:
            break
        pw.wait_for_timeout(5000)

    dump("after-search")

    print("\n=== PRODUCT-RELATED RESPONSES ===")
    for line in net[-30:]:
        print(line)
    print("\n=== CONSOLE ERRORS/WARNINGS ===")
    for line in console_errors[-20:]:
        print(line)

    pw.screenshot(path="reports/diag_sku_dialog.png")
    raise AssertionError("DIAG — 见上方输出与 reports/diag_sku_dialog.png")
