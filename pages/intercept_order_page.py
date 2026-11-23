"""0109 拦截订单页 — 按 ERP 订单ID 关键字查询订单是否进入拦截。

列表 grid 组件 id 为 OrderInterceptionGridPanelID。
ERP 订单ID 在 store 里是 orderId（隐藏列），列表可见的「渠道订单ID」是 rd3OrderId；
顶部关键字查询可以直接用 ERP 订单ID 命中。
"""

from __future__ import annotations

from playwright.sync_api import expect

from pages.base_page import BasePage


class InterceptOrderPage(BasePage):
    BUSINESS_TAB = "#tab-1029"
    MENU_0109 = "span.x-tree-node-text:has-text('0109拦截订单')"

    GRID_ID = "OrderInterceptionGridPanelID"

    COL_INTERCEPT_STATUS = "拦截状态"
    COL_INTERCEPT_TYPE = "拦截类型"
    COL_INTERCEPT_TIME = "拦截时间"
    COL_RD3_ORDER_ID = "渠道订单ID"

    def open_0109(self) -> None:
        """业务管理 tab → 0109 拦截订单。"""
        self.page.click(self.BUSINESS_TAB)
        self.page.wait_for_timeout(1500)
        self.page.locator(self.MENU_0109).first.click()
        self.page.wait_for_timeout(2500)
        self.wait_overlay()
        expect(self.page.locator(f"#{self.GRID_ID}")).to_be_visible()

    def rows(self, limit: int = 50) -> list[dict]:
        return self.grid_rows(self.GRID_ID, limit)

    def find_by_erp_order_id(self, erp_order_id: str) -> dict | None:
        """关键字查询 ERP 订单ID；命中返回该行（含 data/texts），未命中返回 None。"""
        self.search_keywords(erp_order_id, self.GRID_ID)
        for row in self.rows():
            if row["data"].get("orderId") == erp_order_id:
                return row
        return None
