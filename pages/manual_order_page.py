"""0102 手工订单页 — 订单列表 + 新建表单 + 产品明细（SKU）。

选择器策略：
- 表单字段用 name 属性（ExtJS 生成的 id 不稳定）
- 按钮用文本 + :visible（页面上有重复的隐藏按钮）
- 列表行定位到含 "MNO" 的 grid view（避开左侧菜单树）
- 产品明细行定位到含 "平台售价" 列的 grid view（全页唯一）
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from playwright.sync_api import expect

from pages.base_page import BasePage


@dataclass
class ShipInfo:
    first_name: str = "Test"
    last_name: str = "User"
    address1: str = "123 Test St"
    address2: str = "No.456"
    state: str = "VIC"
    city: str = "Melbourne"
    postcode: str = "3000"
    telephone: str = "0400000000"


class ManualOrderPage(BasePage):
    # ── 顶部 tab / 菜单 ──
    BUSINESS_TAB = "#tab-1029"
    MENU_0102 = "span.x-tree-node-text:has-text('0102手工订单')"

    # ── 工具栏按钮（文本 + 可见）──
    BTN_NEW = "a.x-btn:visible:has-text('新建')"
    BTN_SAVE = "a.x-btn:visible:has-text('保存')"
    BTN_AUDIT = "a.x-btn:visible:has-text('审核')"

    # ── 新建表单字段（name 定位）──
    F_ORDER_TYPE = "input[name='main.orderType']"
    F_PLATFORM = "input[name='main.platformId']"
    F_REMARK = "textarea[name='main.remark']"
    F_SHIP_FIRST = "input[name='main.ship.firstName']"
    F_SHIP_LAST = "input[name='main.ship.lastName']"
    F_SHIP_ADDR1 = "input[name='main.ship.address1']"
    F_SHIP_STATE = "input[name='main.ship.state']"
    F_SHIP_CITY = "input[name='main.ship.city']"
    F_SHIP_POSTCODE = "input[name='main.ship.postcode']"
    F_SHIP_TELEPHONE = "input[name='main.ship.telephone']"

    # ── 订单列表 grid（含 MNO 单号的表格）──
    ORDER_VIEW = ".x-grid-view:has-text('MNO')"

    # ── 产品明细面板（订单商品信息）──
    SKU_INSERT_TOOL = ".x-panel-header:has-text('订单商品信息') .x-tool[data-qtip='插入']"

    # ── 选择 SKU 对话框 ──
    SKU_DIALOG = "#ProductComboInventoryDialogWinID"
    SKU_DIALOG_LIST = "#ProductComboInventoryDialogWinGridPanelID .x-grid-row"
    SKU_DIALOG_SELECTED = "#ProductComboInventoryDialogWinSelectGridPanelID .x-grid-row"

    # ── 列表列名 ──
    COL_NO = "手工单号"
    COL_AUDIT_STATUS = "审核状态"

    # ── 导航 ──────────────────────────────────────────────
    def open_0102(self) -> None:
        """点业务管理 tab → 点 0102 手工订单。"""
        self.page.click(self.BUSINESS_TAB)
        self.page.wait_for_timeout(1500)
        self.page.locator(self.MENU_0102).first.click()
        self.page.wait_for_timeout(2500)
        self.wait_overlay()

    # ── 新建 + 填表 ───────────────────────────────────────
    def click_new(self) -> None:
        self.page.locator(self.BTN_NEW).first.click()
        self.page.wait_for_timeout(1500)
        self.wait_overlay()

    def fill_form(self, order_type: str = "零售",
                  platform_search: str = "Lasoo",
                  ship: ShipInfo | None = None,
                  remark: str = "UI_AUTO_TEST") -> None:
        ship = ship or ShipInfo()
        self.select_combo(self.F_ORDER_TYPE, order_type)
        self.select_remote_combo(self.F_PLATFORM, platform_search)
        self.fill(self.F_SHIP_FIRST, ship.first_name)
        self.fill(self.F_SHIP_LAST, ship.last_name)
        self.fill(self.F_SHIP_ADDR1, ship.address1)
        self.fill(self.F_SHIP_STATE, ship.state)
        self.fill(self.F_SHIP_CITY, ship.city)
        self.fill(self.F_SHIP_POSTCODE, ship.postcode)
        self.fill(self.F_SHIP_TELEPHONE, ship.telephone)
        self.fill(self.F_REMARK, remark)

    # ── 产品明细（SKU）────────────────────────────────────
    def add_first_sku(self) -> None:
        """插入 → 查询 → 双击第一行加入已选 → 确认。"""
        tool = self.page.locator(self.SKU_INSERT_TOOL).first
        tool.scroll_into_view_if_needed()
        tool.click()

        dialog = self.page.locator(self.SKU_DIALOG)
        expect(dialog).to_be_visible()

        dialog.locator("a.x-btn:visible").filter(has_text="查询").first.click()
        first = self.page.locator(self.SKU_DIALOG_LIST).first
        expect(first).to_be_visible(timeout=20000)
        first.dblclick()
        expect(self.page.locator(self.SKU_DIALOG_SELECTED).first).to_be_visible()

        dialog.locator("a.x-btn:visible").filter(has_text="确认").first.click()
        expect(dialog).to_be_hidden()
        self.wait_overlay()

    def _detail_view_selector(self) -> str:
        """取产品明细 grid 的 DOM id（空数据时列名不在 grid-view 文本里，不能靠文本定位）。"""
        sel = self.page.evaluate(
            """() => {
                const grids = Ext.ComponentQuery.query('gridpanel');
                for (const g of grids) {
                    if (g.up('window')) continue;
                    const s = g.getStore && g.getStore();
                    if (!s || !s.getCount()) continue;
                    const r = s.getAt(0);
                    if (r && r.get('sku') !== undefined && r.get('quantity') !== undefined) {
                        const v = g.getView && g.getView();
                        if (v && v.el && v.el.id) return '#' + v.el.id;
                    }
                }
                return null;
            }"""
        )
        if not sel:
            raise AssertionError("未找到产品明细 grid（SKU 行未写入）")
        return sel

    def set_first_line(self, quantity: int = 1, unit_price: float = 10) -> None:
        """给明细第一行填购买数与平台售价（订单类型 1/2 时售价必须 > 0）。

        ExtJS 4 内联编辑的单元格在隐藏列与窄视口下无法稳定双击，
        这里通过 grid store 写入数值；保存与审核仍走真实按钮点击。
        """
        ok = self.page.evaluate(
            """({qty, price}) => {
                const grids = Ext.ComponentQuery.query('gridpanel');
                for (const g of grids) {
                    if (g.up('window')) continue;
                    const s = g.getStore && g.getStore();
                    if (!s || !s.getCount()) continue;
                    const r = s.getAt(0);
                    if (r.get('sku') === undefined || r.get('quantity') === undefined) continue;
                    const total = Number((qty * price).toFixed(2));
                    r.set('quantity', qty);
                    r.set('unitPrice', price);
                    r.set('amountTotal', total);
                    r.raw.quantity = qty;
                    r.raw.unitPrice = price;
                    r.raw.amountTotal = total;
                    if (g.getView()) g.getView().refresh();
                    return true;
                }
                return false;
            }""",
            {"qty": quantity, "price": unit_price},
        )
        if not ok:
            raise AssertionError("未找到产品明细 grid（SKU 行未写入）")
        view = self._detail_view_selector()
        expect(self.page.locator(f"{view} .x-grid-row").first).to_be_visible()

    # ── 保存 / 审核 ───────────────────────────────────────
    def save(self) -> bool:
        """点保存 → 确认框点是 → 等待刷新。返回是否确认成功。"""
        self.page.locator(self.BTN_SAVE).first.click()
        self.page.wait_for_timeout(1000)
        ok = self.click_confirm("是")
        self.wait_overlay()
        self.page.wait_for_timeout(2500)
        return ok

    def select_first_row(self) -> None:
        self.page.locator(self.ORDER_VIEW).first.locator(".x-grid-row").first.click()
        self.page.wait_for_timeout(800)

    def submit_audit(self) -> bool:
        """选中第一行 → 点审核 → 确认框点是。返回是否确认成功。"""
        self.select_first_row()
        self.page.locator(self.BTN_AUDIT).first.click()
        self.page.wait_for_timeout(1000)
        ok = self.click_confirm("是")
        self.wait_overlay()
        self.page.wait_for_timeout(2500)
        return ok

    # ── 列表读取 ──────────────────────────────────────────
    def first_order_info(self) -> dict:
        """读取订单列表第一行，返回 {列名: 单元格文本}。

        隐藏列不渲染 td，因此按「可见列头」与「可见 td」的顺序对齐。
        """
        info = self.page.evaluate(
            """() => {
                const wide = el => el.getBoundingClientRect().width > 1;
                const grids = Ext.ComponentQuery.query('gridpanel');
                for (const g of grids) {
                    if (g.up('window')) continue;
                    const s = g.getStore && g.getStore();
                    if (!s || !s.getCount()) continue;
                    const r = s.getAt(0);
                    if (r.get('manualOrderNo') === undefined) continue;
                    const view = g.getView && g.getView();
                    const rowEl = view && view.getNode(r);
                    if (!rowEl) continue;
                    let box = rowEl;
                    while (box && !box.querySelector('.x-column-header')) {
                        box = box.parentElement;
                    }
                    if (!box) continue;
                    const headers = Array.from(box.querySelectorAll('.x-column-header'))
                        .filter(wide).map(h => h.innerText.trim());
                    const tds = Array.from(rowEl.querySelectorAll('td.x-grid-cell'))
                        .filter(wide);
                    const obj = {};
                    headers.forEach((name, i) => {
                        obj[name] = tds[i] ? tds[i].innerText.trim() : '';
                    });
                    return obj;
                }
                return {};
            }"""
        )
        return info or {}

    def wait_first_order_changed(self, old_no: str | None, timeout_ms: int = 20000) -> dict:
        """保存后等待列表第一行单号变化（列表可能异步刷新）。"""
        deadline = time.time() + timeout_ms / 1000
        info = self.first_order_info()
        while time.time() < deadline:
            info = self.first_order_info()
            if info.get(self.COL_NO) and info[self.COL_NO] != old_no:
                return info
            self.page.wait_for_timeout(500)
        return info
