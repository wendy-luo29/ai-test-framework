"""0801 出库申请单页 — 按 ERP 订单ID 查询单据状态（计费完成后应为「转执行单」）。

列表 grid 组件 id 为 SoApplyGridPanelID，来源单号 fromOrderNo = 0102 的 ERP订单ID。
「单据状态」是字典渲染列，文本值：转执行单 / 物流计费失败 / 取消订单 / 导入失败。
"""

from __future__ import annotations

import time

from playwright.sync_api import expect

from pages.base_page import BasePage


class OutboundApplyPage(BasePage):
    BUSINESS_TAB = "#tab-1029"
    MENU_0801 = "span.x-tree-node-text:has-text('0801出库申请单')"

    GRID_ID = "SoApplyGridPanelID"

    COL_APPLY_NO = "申请单号"
    COL_FROM_ORDER_NO = "来源单号"
    COL_STATUS = "单据状态"

    STATUS_TO_EXEC = "转执行单"
    STATUS_FAILED = {"物流计费失败", "取消订单", "导入失败"}

    def open_0801(self) -> None:
        """业务管理 tab → 0801 出库申请单。"""
        self.page.click(self.BUSINESS_TAB)
        self.page.wait_for_timeout(1500)
        self.page.locator(self.MENU_0801).first.click()
        self.page.wait_for_timeout(2500)
        self.wait_overlay()
        expect(self.page.locator(f"#{self.GRID_ID}")).to_be_visible()

    def rows(self, limit: int = 50) -> list[dict]:
        return self.grid_rows(self.GRID_ID, limit)

    def find_by_from_order_no(self, erp_order_id: str) -> dict | None:
        """关键字查询 ERP 订单ID（即来源单号）；命中返回该行，未命中返回 None。"""
        self.search_keywords(erp_order_id, self.GRID_ID)
        for row in self.rows():
            if row["data"].get("fromOrderNo") == erp_order_id:
                return row
        return None

    def wait_for_status(self, erp_order_id: str,
                        expected: str = STATUS_TO_EXEC,
                        timeout_ms: int = 240_000,
                        poll_ms: int = 10_000) -> dict:
        """轮询直到单据状态为 expected；遇到明确的失败状态立即报错。"""
        deadline = time.time() + timeout_ms / 1000
        last = None
        while True:
            row = self.find_by_from_order_no(erp_order_id)
            if row is not None:
                last = row
                status = row["texts"].get(self.COL_STATUS)
                if status == expected:
                    return row
                if status in self.STATUS_FAILED:
                    raise AssertionError(
                        f"0801 单据状态为「{status}」，未按预期「{expected}」"
                        f"（申请单 {row['texts'].get(self.COL_APPLY_NO)}，来源单号 {erp_order_id}）"
                    )
            if time.time() >= deadline:
                break
            self.page.wait_for_timeout(poll_ms)
        raise AssertionError(
            f"等待 {timeout_ms / 1000:.0f}s 后 0801 仍未出现来源单号 {erp_order_id} 且状态为「{expected}」的记录，"
            f"最后一次查询结果：{last and last['texts']}"
        )
