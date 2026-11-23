"""0102 手工订单：新建 → 保存 → 提交审核（端到端冒烟）。"""

from __future__ import annotations

import pytest

from pages.manual_order_page import ManualOrderPage

pytestmark = [pytest.mark.ui, pytest.mark.smoke]


def test_create_and_submit_manual_order(manual_order_page: ManualOrderPage):
    """新建手工订单（含产品明细）保存后状态为审核中，再选中该行点审核通过。"""
    page = manual_order_page

    # 1. 记录保存前列表第一行单号
    before_no = page.first_order_info().get(page.COL_NO)

    # 2. 新建 + 填表 + 加一条产品明细（SKU 不能为空，否则保存被后端拒绝）
    page.click_new()
    page.fill_form(order_type="零售", platform_search="Lasoo")
    page.add_first_sku()
    page.set_first_line(quantity=1, unit_price=10)

    # 3. 保存（弹确认框点「是」）
    assert page.save(), "保存确认框未出现或未点中「是」"

    # 4. 列表顶部应出现新订单，审核状态为「审核中」
    after = page.wait_first_order_changed(before_no)
    assert after.get(page.COL_NO), f"保存后未读取到订单号，行数据：{after}"
    assert after[page.COL_NO] != before_no, (
        f"列表第一行未变化（仍是 {before_no}），订单可能未创建成功"
    )
    assert after.get(page.COL_AUDIT_STATUS) == "审核中", (
        f"新订单审核状态期望「审核中」，实际「{after.get(page.COL_AUDIT_STATUS)}」（行：{after}）"
    )

    # 5. 选中该行 → 点审核 → 确认「是」
    assert page.submit_audit(), "审核确认框未出现或未点中「是」"

    # 6. 审核后状态应为「通过」
    audited = page.first_order_info()
    assert audited.get(page.COL_NO) == after[page.COL_NO], (
        f"审核后列表第一行不是刚创建的订单（期望 {after[page.COL_NO]}，实际 {audited.get(page.COL_NO)}）"
    )
    assert audited.get(page.COL_AUDIT_STATUS) == "通过", (
        f"审核后状态期望「通过」，实际「{audited.get(page.COL_AUDIT_STATUS)}」（行：{audited}）"
    )
