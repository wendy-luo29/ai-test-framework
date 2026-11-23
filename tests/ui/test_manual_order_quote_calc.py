"""0102 手工订单 → 0109 拦截检查 → 0801 出库申请单 → lsp_quote 计费数据校验。

流程（在原用例 test_create_manual_order.py 之外新增，不改动原脚本）：
1. 新建 / 保存 / 审核手工订单（复用 ManualOrderPage）
2. 等待 intercept_check_delay 秒 → 0109 用 ERP订单ID 关键字查询
   - 查询为空 = 未进入拦截，继续
   - 查到记录 = 已进入拦截，用例失败并打印拦截类型/时间
3. 未拦截再等 outbound_check_delay 秒 → 0801 按来源单号（ERP订单ID）查询，
   等待单据状态变为「转执行单」，此时计费计算已完成
4. 校验计费表：
   - lsp_quote_task               1 条，status=200 且 predict_price > 0
   - lsp_quote_task_address       2 条（发货地 type=100 / 收件地 type=200），收件地址与下单一致
   - lsp_quote_task_package       >= 1 条，与 quote_task_id 关联、status=100
   - lsp_quote_task_package_sku   >= 1 条，件数合计 = 下单件数
   - lsp_quote_task_job_log       >= 1 条，含 calc 与最终 choice 日志
"""

from __future__ import annotations

import time

import pytest

from pages.intercept_order_page import InterceptOrderPage
from pages.manual_order_page import ManualOrderPage, ShipInfo
from pages.outbound_apply_page import OutboundApplyPage

pytestmark = [pytest.mark.ui, pytest.mark.regression, pytest.mark.db,
              pytest.mark.module_lsp_quote]

COL_ERP_ORDER_ID = "ERP订单ID"

# lsp_quote_task.status 取值（本环境实测）：200=计费完成，300=计费失败
QUOTE_TASK_DONE = 200
QUOTE_TASK_FAILED = 300


def _assert_quote_tables(db, erp_order_id: str, ship: ShipInfo) -> None:
    """校验 5 张计费表的数据与本次订单一致。"""
    task = db.fetch_one(
        "SELECT * FROM lsp_quote_task WHERE order_code = %s and push_result_to=301 ORDER BY created_at DESC LIMIT 1",
        (erp_order_id,),
    )
    assert task, f"lsp_quote_task 中未找到 order_code={erp_order_id} 的计费任务"
    tid = task["id"]
    assert task["status"] == QUOTE_TASK_DONE, (
        f"lsp_quote_task.status 期望 {QUOTE_TASK_DONE}（计费完成），实际 {task['status']}（{task}）"
    )
    assert float(task["predict_price"]) > 0, f"lsp_quote_task.predict_price 应大于 0，实际 {task['predict_price']}"
    assert task["predict_carrier_code"], "lsp_quote_task.predict_carrier_code 为空（未选出承运商）"

    # ── 地址：1 条发货地(100) + 1 条收件地(200) ──
    addrs = db.fetch_all(
        "SELECT * FROM lsp_quote_task_address WHERE quote_task_id = %s AND status = 100", (tid,))
    assert len(addrs) == 2, f"lsp_quote_task_address 期望 2 条（发件+收件），实际 {len(addrs)}：{addrs}"
    types = {a["type"] for a in addrs}
    assert types == {100, 200}, f"lsp_quote_task_address.type 期望 {{100, 200}}，实际 {types}"
    to_addr = next(a for a in addrs if a["type"] == 200)
    assert (to_addr["country"] or "").upper() == "AU", \
        f"收件国家期望 AU，实际 {to_addr['country']}"
    assert (to_addr["state"] or "").upper() == ship.state.upper(), \
        f"收件州期望 {ship.state}，实际 {to_addr['state']}"
    assert (to_addr["postcode"] or "") == ship.postcode, \
        f"收件邮编期望 {ship.postcode}，实际 {to_addr['postcode']}"
    assert (to_addr["address1"] or "").strip().casefold() == ship.address1.strip().casefold(), \
        f"收件地址期望 {ship.address1}，实际 {to_addr['address1']}"

    # ── 包裹：与任务关联，状态正常，体积重量已计算 ──
    packages = db.fetch_all(
        "SELECT * FROM lsp_quote_task_package WHERE quote_task_id = %s AND status = 100", (tid,))
    assert packages, f"lsp_quote_task_package 未找到 quote_task_id={tid} 的包裹"
    for p in packages:
        assert float(p["length"]) > 0 and float(p["width"]) > 0 and float(p["height"]) > 0, \
            f"包裹 {p['package_code']} 尺寸异常：{p['length']}x{p['width']}x{p['height']}"
        assert float(p["weight"]) > 0, f"包裹 {p['package_code']} 重量异常：{p['weight']}"

    # ── 包裹 SKU：件数合计应等于订单明细件数（本用例下单 1 件） ──
    skus = db.fetch_all(
        "SELECT s.* FROM lsp_quote_task_package_sku s "
        "JOIN lsp_quote_task_package p ON p.id = s.quote_task_package_id "
        "WHERE p.quote_task_id = %s AND s.status = 100", (tid,))
    assert skus, f"lsp_quote_task_package_sku 未找到关联 quote_task_id={tid} 的明细"
    for s in skus:
        assert s["sku"], f"lsp_quote_task_package_sku 存在空 sku：{s}"
    assert sum(int(s["qty"]) for s in skus) == 1, \
        f"包裹 SKU 件数合计期望 1，实际 {sum(int(s['qty']) for s in skus)}：{skus}"

    # ── 计算日志：每个任务至少一条 calc，最终有 choice ──
    logs = db.fetch_all(
        "SELECT * FROM lsp_quote_task_job_log WHERE quote_task_id = %s", (tid,))
    assert logs, f"lsp_quote_task_job_log 未找到 quote_task_id={tid} 的计算日志"
    actions = {log["action"] for log in logs}
    assert "calc" in actions, f"计算日志缺少 calc 动作，实际动作：{actions}"
    assert "choice" in actions, f"计算日志缺少 choice（最终择优）动作，实际动作：{actions}"


def test_manual_order_quote_calc_and_tables(manual_order_page: ManualOrderPage,
                                            config, db):
    cfg = config.get("manual_order_quote") or {}
    intercept_delay = int(cfg.get("intercept_check_delay", 30))
    outbound_delay = int(cfg.get("outbound_check_delay", 60))
    calc_timeout = int(cfg.get("calc_timeout", 240)) * 1000
    poll_ms = int(cfg.get("poll_interval", 10)) * 1000

    page = manual_order_page
    ship = ShipInfo()

    # ── 1. 新建 / 保存 / 审核手工订单 ──
    before_no = page.first_order_info().get(page.COL_NO)
    page.click_new()
    page.fill_form(order_type="零售", platform_search="Lasoo", ship=ship,
                   remark="UI_AUTO_QUOTE")
    page.add_first_sku()
    page.set_first_line(quantity=1, unit_price=10)
    assert page.save(), "保存确认框未出现或未点中「是」"

    after = page.wait_first_order_changed(before_no)
    assert after.get(page.COL_NO), f"保存后未读取到订单号，行数据：{after}"
    assert after[page.COL_NO] != before_no, \
        f"列表第一行未变化（仍是 {before_no}），订单可能未创建成功"

    assert page.submit_audit(), "审核确认框未出现或未点中「是」"
    audited = page.first_order_info()
    assert audited.get(page.COL_NO) == after[page.COL_NO], \
        f"审核后列表第一行不是刚创建的订单（期望 {after[page.COL_NO]}，实际 {audited.get(page.COL_NO)}）"
    assert audited.get(page.COL_AUDIT_STATUS) == "通过", \
        f"审核后状态期望「通过」，实际「{audited.get(page.COL_AUDIT_STATUS)}」"

    erp_order_id = audited.get(COL_ERP_ORDER_ID)
    assert erp_order_id, f"未读取到 ERP订单ID，行数据：{audited}"

    # ── 2. 等待后检查 0109 是否进入拦截 ──
    time.sleep(intercept_delay)
    intercept = InterceptOrderPage(page.page)
    intercept.open_0109()
    hit = intercept.find_by_erp_order_id(erp_order_id)
    assert hit is None, (
        f"订单 {erp_order_id} 已进入 0109 拦截："
        f"拦截类型「{hit['texts'].get(InterceptOrderPage.COL_INTERCEPT_TYPE)}」，"
        f"拦截时间「{hit['texts'].get(InterceptOrderPage.COL_INTERCEPT_TIME)}」"
    )

    # ── 3. 未拦截 → 等待计费，0801 单据状态应为「转执行单」 ──
    time.sleep(outbound_delay)
    outbound = OutboundApplyPage(page.page)
    outbound.open_0801()
    row = outbound.wait_for_status(erp_order_id, expected=OutboundApplyPage.STATUS_TO_EXEC,
                                   timeout_ms=calc_timeout, poll_ms=poll_ms)
    assert row["texts"].get(OutboundApplyPage.COL_STATUS) == OutboundApplyPage.STATUS_TO_EXEC

    # ── 4. 校验计费相关表 ──
    _assert_quote_tables(db, erp_order_id, ship)
