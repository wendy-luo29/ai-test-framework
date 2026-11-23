# -*- coding: utf-8 -*-
"""REQ-002 承运商运费计算同步接口（POST /quote/price_sync）——"少而准"用例集。

设计依据:
    需求     requirements/docs/REQ-002_quote_price_sync.md (V1.1)
    AC 清单  requirements/decomposition/REQ-002-AC-list.yaml（35 个原子能力）
    设计文档 testcases/REQ-002-quote_price/REQ-002-TC-distilled.md

设计原则（对齐 REQ-002-testcase-review.md 门禁结论）:
    1. 一个原子能力(AC)至多一条用例，可合并的 AC 合并进同一条主流程用例；
       73 条旧清单收敛为 15 个测试函数（约 21 个可执行实例）。
    2. 单分支断言：金额一律用 lsp_scp 验证 SQL 现算现比（round half-up 三位），
       负向统一断言 code != "200" + 计费任务未落库（R-002 闭环前唯一可执行口径）。
    3. requestId/shipmentCode/packageCode/orderCode 每次构造时重新生成
       （时间戳+随机），避免重复执行触发幂等或脏数据（评审 M-13）。
    4. 待回填数据（dest_b / 无价卡承运商 / 澳邮承运商）为空时对应用例 skip，
       skip reason 直接给出回填指引；见设计文档"校准点清单"。

运行前提:
    - config/base.yaml: services.lsp_quote.<env> 指向被测环境；
    - 环境变量 TEST_LSP_QUOTE_TOKEN 携带 Bearer Token；
    - 环境变量 TEST_DB_PASSWORD 提供 lsp_scp 只读密码（金额现算用例必需）。
"""

from __future__ import annotations

import copy
import json
import math
import os
import random
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

from api_clients.lsp_quote.price_sync_client import PriceSyncClient
from config.config_loader import get_config, get_module_config, get_service_url
from utils.db import Database

pytestmark = [pytest.mark.api, pytest.mark.module_lsp_quote, pytest.mark.feature_pricing]

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "lsp_quote" / "price_sync_base.json"

# §3.2 QuotePriceSyncVo 必备字段（类型在 assert_vo_schema 中逐一校验）
VO_REQUIRED = {
    "calcMode": int,
    "canShipping": bool,
    "agentCode": str,
    "agentName": str,
    "channelCode": str,
    "channelName": str,
    "carrierCode": str,
    "carrierName": str,
    "bookingCarrierId": str,
    "bookingCarrierCode": str,
    "bookingCarrierCalc": str,
    "shippingCost": (int, float),
    "closePoboxCheck": int,
    "isBest": int,
}
# 暂未启用字段（REQ §3.2），成功响应中恒为 null
VO_NULLABLE = ("choiceShippingCost", "shippingCostWithTax", "surcharge")


# ────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────

def _suffix() -> str:
    """时间戳+随机后缀，保证 requestId/orderCode 等 id 每次执行唯一（评审 M-13）。"""
    return f"{int(time.time() * 1000)}{random.randint(1000, 9999)}"


def money(value) -> float:
    """四舍五入保留三位（half-up，对齐需求口径，避免 Python 银行家舍入）。"""
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def chargeable_kg(weight: float) -> int:
    """发运重向上取整（REQ §7 计算规则）。"""
    return math.ceil(float(weight))


def expected_cost(rate: dict, weight_kg: float, basic_limit_kg: float) -> float:
    """运费 = 基础运费 × (1 + fuel_rate)，基础运费按 ≤5kg 首重 / >5kg 续重（REQ §7）。"""
    weight_kg = float(weight_kg)
    fee = float(rate["fee"])
    fuel = float(rate["fuel_rate"])
    if weight_kg > basic_limit_kg:
        per_kg = float(rate.get("per_kilogram_fee") or 0)
        fee = fee + (weight_kg - basic_limit_kg) * per_kg
    return money(fee * (1 + fuel))


def fail_ctx(carrier_id: str, postcode: str, weight: float) -> str:
    return f"carrier_id={carrier_id}, postcode={postcode}, weight={weight}"


# ────────────────────────────────────────────────────────────
# fixtures（模块内自洽，不依赖根 conftest 修改）
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def price_sync_cfg():
    return get_module_config("lsp_quote", "price_sync")


@pytest.fixture(scope="module")
def quote_client(price_sync_cfg):
    base_url = get_service_url("lsp_quote")
    if not base_url:
        pytest.skip("lsp_quote 服务地址未配置：config/base.yaml services.lsp_quote.<env> 为空")
    token_env = (price_sync_cfg.get("auth") or {}).get("token_env", "")
    token = os.getenv(token_env, "") if token_env else ""
    if token_env and not token:
        pytest.skip(f"鉴权 Token 未提供：环境变量 {token_env} 为空")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    client = PriceSyncClient(base_url, timeout=float(get_config().get("api_timeout", 30)),
                             path=price_sync_cfg["path"], headers=headers)
    yield client
    client.close()


@pytest.fixture(scope="module")
def quote_client_noauth(price_sync_cfg):
    """不带 Authorization 头的客户端，仅供鉴权用例使用。"""
    base_url = get_service_url("lsp_quote")
    if not base_url:
        pytest.skip("lsp_quote 服务地址未配置：config/base.yaml services.lsp_quote.<env> 为空")
    client = PriceSyncClient(base_url, timeout=float(get_config().get("api_timeout", 30)),
                             path=price_sync_cfg["path"], headers=None)
    yield client
    client.close()


@pytest.fixture(scope="module")
def scp_db():
    db = Database.from_config(get_config())
    if db is None:
        pytest.skip("DB 断言未配置：base.yaml database 区块不完整或 TEST_DB_PASSWORD 为空")
    yield db
    db.close()


@pytest.fixture(scope="module")
def build_payload(price_sync_cfg):
    """基于 §4 基础请求体构造请求；每次调用重新生成全部唯一 id。"""
    base = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    md = price_sync_cfg["master_data"]
    base["ownerId"] = md["owner_id"]
    wh = base["warehouse"][0]
    wh["warehouseCode"] = md["warehouse_code"]
    wh.update(md.get("warehouse_address") or {})

    def _build(**overrides) -> dict:
        payload = copy.deepcopy(base)
        uid = _suffix()
        payload["requestId"] = f"SAC{uid}"[:64]
        payload["orderCode"] = f"TESTSO{uid}"[:32]
        payload["warehouse"][0]["shipmentCode"] = f"TS{uid}"[:64]
        payload["warehouse"][0]["packages"][0]["packageCode"] = f"QTP{uid}"[:32]
        payload.update(copy.deepcopy(overrides))
        return payload

    return _build


@pytest.fixture(scope="module")
def md(price_sync_cfg):
    return price_sync_cfg["master_data"]


@pytest.fixture(scope="module")
def rules(price_sync_cfg):
    return price_sync_cfg["rules"]


# ────────────────────────────────────────────────────────────
# 断言助手（三层断言的公共部分）
# ────────────────────────────────────────────────────────────

def assert_success_body(response, request_id: str, order_code: str) -> dict:
    """L1 HTTP 200 + L2 包装层契约（§3.1）+ 回显一致。"""
    assert response.status_code == 200, (
        f"HTTP 状态码应为 200，实际 {response.status_code}，响应体: {response.text[:500]}"
    )
    body = response.json()
    for key in ("requestId", "orderCode", "code", "msg", "tc", "tp", "hasMore", "success", "data"):
        assert key in body, f"包装层缺少字段 {key}，实际: {body}"
    assert body["requestId"] == request_id, (
        f"requestId 未回显一致：期望 {request_id}，实际 {body['requestId']}"
    )
    assert body["orderCode"] == order_code, (
        f"orderCode 未回显一致：期望 {order_code}，实际 {body['orderCode']}"
    )
    assert body["success"] is True, f"success 应为 true，实际 {body['success']}，msg={body['msg']}"
    assert body["code"] == "200", f"code 应为 '200'，实际 {body['code']}"
    assert isinstance(body["data"], list) and body["data"], "data 应为非空数组"
    return body


def assert_vo_schema(row: dict) -> None:
    """L2 报价行契约（§3.2）：必备字段存在且类型正确，未启用字段为 null。"""
    for field, types in VO_REQUIRED.items():
        assert field in row, f"报价行缺少字段 {field}，实际: {row}"
        value = row[field]
        if value is not None:
            assert isinstance(value, types), (
                f"{field} 类型应为 {types}，实际 {type(value).__name__}（值={value}）"
            )
    for field in VO_NULLABLE:
        assert field in row, f"报价行缺少（暂未启用）字段 {field}"
        assert row[field] is None, (
            f"{field} 暂未启用应为 null（REQ §3.2），实际 {row[field]}"
        )


def rows_for(body: dict, carrier_id: str) -> list[dict]:
    return [r for r in body["data"] if r.get("bookingCarrierId") == carrier_id]


def assert_zone_rate_amount(scp_db, price_sync_cfg, row: dict, carrier_id: str,
                            postcode: str, weight_kg: float) -> float:
    """L3 金额现算现比：zone→价卡段 SQL 实查 → 公式复算 → 与响应值比对。"""
    rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
        "carrier_id": carrier_id,
        "postcode": postcode,
        "weight": chargeable_kg(weight_kg),
    })
    assert rate is not None, (
        f"验证 SQL 未取到价卡（请先校准 config/lsp_quote/price_sync.yaml sql.zone_rate 列名）: "
        f"{fail_ctx(carrier_id, postcode, weight_kg)}"
    )
    expected = expected_cost(rate, chargeable_kg(weight_kg), price_sync_cfg["rules"]["basic_limit_kg"])
    actual = float(row["shippingCost"])
    assert abs(actual - expected) <= 0.0005, (
        f"运费与 SQL 现算不一致: 期望 {expected}，实际 {actual}；"
        f"价卡行 fee={rate['fee']} per_kg={rate.get('per_kilogram_fee')} fuel={rate['fuel_rate']}；"
        f"{fail_ctx(carrier_id, postcode, weight_kg)}"
    )
    return actual


def task_count(scp_db, price_sync_cfg, sql_key: str, param: dict) -> int:
    cnt = scp_db.scalar(price_sync_cfg["sql"][sql_key], param)
    assert cnt is not None, f"计数 SQL 未返回结果: {sql_key} {param}（请校准 sql 模板）"
    return int(cnt)


def base_package(length, width, height, weight, sku="SKU-TEST"):
    """构造单包裹单 SKU，包裹层与 SKU 层尺寸一致。"""
    return {
        "packageCode": f"QTP{_suffix()}"[:32],
        "length": length, "width": width, "height": height, "weight": weight,
        "items": [{
            "sku": sku, "qty": 1,
            "length": length, "width": width, "height": height, "weight": weight,
        }],
    }


def one_warehouse(warehouse_code: str, packages: list[dict]) -> list[dict]:
    return [{
        "warehouseCode": warehouse_code,
        "shipmentCode": f"TS{_suffix()}"[:64],
        "country": "AU", "state": "VIC", "suburb": "Maidstone",
        "postcode": "3012", "address1": "C 35-77 Emu Road",
        "packages": packages,
    }]


# ════════════════════════════════════════════════════════════
# P0 冒烟集
# ════════════════════════════════════════════════════════════

@pytest.mark.smoke
@pytest.mark.db
def test_main_flow_two_carriers(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-001 (P0) 主流程：双承运商成功报价 + 响应契约 + 全局择优 + 金额现算。
    覆盖 AC-01/02/09/14/18/26/28。"""
    # case_id: TC-QPS-001
    payload = build_payload(carrierIds=[md["carrier_pro_id"], md["carrier_base_id"]])
    response = quote_client.price_sync(payload)

    body = assert_success_body(response, payload["requestId"], payload["orderCode"])  # L1+L2

    # L3: 每承运商恰一条内部最优行；行级唯一键 bookingCarrierId 不重复（AC-02/09）
    for carrier_id in (md["carrier_pro_id"], md["carrier_base_id"]):
        rows = rows_for(body, carrier_id)
        assert len(rows) == 1, (
            f"承运商 {carrier_id} 应恰有 1 条内部最优行，实际 {len(rows)} 行: {rows}"
        )
        row = rows[0]
        assert_vo_schema(row)  # L2 行级契约
        assert_zone_rate_amount(scp_db, price_sync_cfg, row, carrier_id,
                                payload["shipTo"]["postcode"], 1.15)  # L3 金额

    # L3: 排序——isBest=1 行优先，其余按 shippingCost 升序（AC-02）
    data = body["data"]
    best_indexes = [i for i, r in enumerate(data) if r["isBest"] == 1]
    assert len(best_indexes) == 1, f"isBest=1 应恰一行，实际 {len(best_indexes)} 行: {data}"
    assert best_indexes[0] == 0, f"isBest=1 行应排在 data[0]，实际位于 index {best_indexes[0]}"
    rest = [r["shippingCost"] for r in data[1:]]
    assert rest == sorted(rest), f"isBest=2 行应按 shippingCost 升序，实际 {rest}"

    # L3: 全局择优——isBest=1 即全局最低（AC-28）
    best = data[0]
    lowest = min(float(r["shippingCost"]) for r in data)
    assert float(best["shippingCost"]) == lowest, (
        f"isBest=1 行金额 {best['shippingCost']} 不是全局最低 {lowest}"
    )


@pytest.mark.smoke
@pytest.mark.db
def test_idempotent_replay(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-002 (P0) 幂等重放：相同 requestId+orderCode 不重复计费（AC-03）。
    断言口径：两次响应报价一致 + 计费任务数不增（响应 code/msg 形态见 R-034，不在本次断言）。"""
    # case_id: TC-QPS-002
    payload = build_payload(carrierIds=[md["carrier_base_id"]])
    first = assert_success_body(quote_client.price_sync(payload),
                                payload["requestId"], payload["orderCode"])

    count_before = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                              {"request_id": payload["requestId"]})
    assert count_before >= 1, f"首次请求后 lsp_quote_task 应有计费任务，实际 {count_before} 条"

    second_response = quote_client.price_sync(payload)  # 完全相同 requestId+orderCode 重放
    second = assert_success_body(second_response, payload["requestId"], payload["orderCode"])

    first_quotes = sorted((r["bookingCarrierId"], float(r["shippingCost"])) for r in first["data"])
    second_quotes = sorted((r["bookingCarrierId"], float(r["shippingCost"])) for r in second["data"])
    assert first_quotes == second_quotes, (
        f"重放响应报价应与首次一致: 首次 {first_quotes}，重放 {second_quotes}"
    )
    count_after = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                             {"request_id": payload["requestId"]})
    assert count_after == count_before, (
        f"幂等重放不应新增计费任务: 请求前 {count_before}，重放后 {count_after}"
    )


@pytest.mark.db
def test_new_request_same_order(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-003 (P1) 不同 requestId + 相同 orderCode 视为新请求（AC-04）。"""
    # case_id: TC-QPS-003
    payload = build_payload(carrierIds=[md["carrier_base_id"]])
    order_code = payload["orderCode"]
    assert_success_body(quote_client.price_sync(payload), payload["requestId"], order_code)
    count_before = task_count(scp_db, price_sync_cfg, "task_count_by_order",
                              {"order_code": order_code})

    second = copy.deepcopy(payload)
    second["requestId"] = f"SAC{_suffix()}"[:64]  # 仅换 requestId → 联合键不同
    assert_success_body(quote_client.price_sync(second), second["requestId"], order_code)
    count_after = task_count(scp_db, price_sync_cfg, "task_count_by_order",
                             {"order_code": order_code})
    assert count_after > count_before, (
        f"新 requestId 应触发新计费: 前次 {count_before}，新请求后 {count_after}"
    )


@pytest.mark.db
def test_zone_mapping_switch(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-004 (P0) zone 映射：两个目的 postcode 分别命中各自价卡段（AC-20）。
    dest_b 未回填时 skip（校准点3）。"""
    # case_id: TC-QPS-004
    dest_b = price_sync_cfg["destinations"]["dest_b"]
    if not dest_b.get("postcode"):
        pytest.skip("校准点3: dest_b 未回填——请从 lsp_carrier_zone 实查与 2000 不同 zone 的 postcode")
    weight = 1.15
    for dest_key in ("dest_a", "dest_b"):
        dest = price_sync_cfg["destinations"][dest_key]
        payload = build_payload(carrierIds=[md["carrier_base_id"]], shipTo=dest)
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        rows = rows_for(body, md["carrier_base_id"])
        assert len(rows) == 1, f"{dest_key}: 承运商应恰 1 行，实际 {rows}"
        assert_zone_rate_amount(scp_db, price_sync_cfg, rows[0], md["carrier_base_id"],
                                dest["postcode"], weight)  # 每个 postcode 各自现算


@pytest.mark.smoke
@pytest.mark.db
def test_multi_package_sum(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-005 (P0) 一票一件多包裹：运费 = Σ 每包裹独立计费（AC-17）。"""
    # case_id: TC-QPS-005
    packages = [base_package(30, 12, 10, 5, "SKU-P1"), base_package(60, 20, 15, 10, "SKU-P2")]
    payload = build_payload(
        carrierIds=[md["carrier_base_id"]],
        warehouse=one_warehouse(md["warehouse_code"], packages),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, md["carrier_base_id"])
    assert len(rows) == 1, f"承运商应恰 1 行，实际 {len(rows)}"
    row = rows[0]
    assert row["calcMode"] == 1, f"多包裹逐个计费应为 calcMode=1（一票一件），实际 {row['calcMode']}"

    # L3: 期望值 = 两个包裹各自称重段现算之和
    postcode = payload["shipTo"]["postcode"]
    expected_total = 0.0
    for pkg in packages:
        rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
            "carrier_id": md["carrier_base_id"], "postcode": postcode,
            "weight": chargeable_kg(pkg["weight"]),
        })
        assert rate is not None, f"包裹 {pkg['packageCode']} 未取到价卡段: {fail_ctx(md['carrier_base_id'], postcode, pkg['weight'])}"
        expected_total += expected_cost(rate, chargeable_kg(pkg["weight"]),
                                        price_sync_cfg["rules"]["basic_limit_kg"])
    expected_total = money(expected_total)
    actual = float(row["shippingCost"])
    assert abs(actual - expected_total) <= 0.0005, (
        f"多包裹运费应等于逐包现算之和: 期望 {expected_total}，实际 {actual}"
    )


# ════════════════════════════════════════════════════════════
# P1 计算引擎与择优
# ════════════════════════════════════════════════════════════

@pytest.mark.db
def test_per_kg_above_5kg(quote_client, scp_db, price_sync_cfg, build_payload, md, rules):
    """TC-QPS-006 (P1) 续重段：称重取整 >5kg 时基础运费 = fee + (称重-5)×per_kg（AC-19）。"""
    # case_id: TC-QPS-006
    payload = build_payload(
        carrierIds=[md["carrier_base_id"]],
        warehouse=one_warehouse(md["warehouse_code"], [base_package(30, 20, 15, 5.1)]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    row = rows_for(body, md["carrier_base_id"])[0]
    assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_base_id"],
                            payload["shipTo"]["postcode"], 5.1)  # 5.1→ceil 6kg 续重段


@pytest.mark.db
def test_internal_optimal_two_modes(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-007 (P0) 承运商内部择优：返回金额 = 一票一件与一票多件的较低者（AC-27）。
    无需预知哪种模式胜出：两种模式分别现算，断言响应值 == min。"""
    # case_id: TC-QPS-007
    packages = [base_package(30, 12, 10, 5, "SKU-P1"), base_package(60, 20, 15, 10, "SKU-P2")]
    payload = build_payload(
        carrierIds=[md["carrier_base_id"]],
        warehouse=one_warehouse(md["warehouse_code"], packages),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, md["carrier_base_id"])
    assert len(rows) == 1, (
        f"两层择优后承运商应仅 1 条内部最优行，实际 {len(rows)} 行: {rows}"
    )

    postcode = payload["shipTo"]["postcode"]
    carrier_id = md["carrier_base_id"]
    limit = price_sync_cfg["rules"]["basic_limit_kg"]

    def rate_at(weight):
        rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
            "carrier_id": carrier_id, "postcode": postcode, "weight": weight})
        assert rate is not None, f"未取到价卡段: {fail_ctx(carrier_id, postcode, weight)}"
        return rate

    mode1 = (expected_cost(rate_at(5), 5, limit)          # 一票一件: 包裹1(5kg) + 包裹2(10kg)
             + expected_cost(rate_at(10), 10, limit))
    mode2 = expected_cost(rate_at(15), 15, limit)          # 一票多件: 最长边60 + 合计计费重15kg
    expected = money(min(mode1, mode2))
    actual = float(rows[0]["shippingCost"])
    assert abs(actual - expected) <= 0.0005, (
        f"内部择优金额应等于两种 calcMode 较低者: 期望 min({mode1}, {mode2})={expected}，实际 {actual}"
    )


@pytest.mark.db
@pytest.mark.parametrize("scenario,packages,charge_weight", [
    ("single_sku_fallback", [base_package(0, 0, 0, 0, "SKU-FALL")], 1.15),
    ("multi_sku_compose",
     [{  # 组包: 长=max(40,20)=40 宽=max(25,15)=25 高=10+20=30 重=3+2=5 → 降序 40/30/25，计费重 5kg
         "packageCode": f"QTP{_suffix()}"[:32],
         "length": 0, "width": 0, "height": 0, "weight": 0,
         "items": [
             {"sku": "SKU-C1", "qty": 1, "length": 40, "width": 25, "height": 10, "weight": 3},
             {"sku": "SKU-C2", "qty": 1, "length": 20, "width": 15, "height": 20, "weight": 2},
         ],
     }],
     5),
], ids=["sku-fallback", "sku-compose"])
def test_package_dims_zero_fallback(quote_client, scp_db, price_sync_cfg, build_payload, md,
                                    scenario, packages, charge_weight):
    """TC-QPS-008 (P1) 包裹层尺寸为 0 时取 SKU 层（AC-15）/ 多 SKU 组包规则（AC-16）。
    组包用例 SKU 均 qty=1，规避 R-050（累加基数按明细行 vs qty 折算）未决口径。"""
    # case_id: TC-QPS-008
    payload = build_payload(
        carrierIds=[md["carrier_base_id"]],
        warehouse=one_warehouse(md["warehouse_code"], copy.deepcopy(packages)),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    row = rows_for(body, md["carrier_base_id"])[0]
    assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_base_id"],
                            payload["shipTo"]["postcode"], charge_weight)


@pytest.mark.db
def test_oversized_carrier_filtered(quote_client, scp_db, price_sync_cfg, build_payload, md, rules):
    """TC-QPS-009 (P1) 超箱规承运商被过滤，另一承运商正常报价（AC-22）。
    三边和 125 > 120 触发不可发；期望箱规受限承运商无行、正常承运商有行。"""
    # case_id: TC-QPS-009
    oversized = base_package(80, 25, 20, 5)  # 80+25+20=125 > max_sum_cm
    assert 80 + 25 + 20 > rules["max_sum_cm"]
    payload = build_payload(
        carrierIds=[md["carrier_pro_id"], md["carrier_base_id"]],
        warehouse=one_warehouse(md["warehouse_code"], [oversized]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert rows_for(body, md["carrier_pro_id"]) == [], (
        "超箱规承运商不应出现在 data（REQ §7: 直接过滤不参与计算）"
    )
    assert rows_for(body, md["carrier_base_id"]), "未超箱规承运商应正常返回报价行"


@pytest.mark.db
@pytest.mark.parametrize("scenario,dims,weight", [
    ("sum_equal_120", (119.9, 0.05, 0.05), 5),   # 三边和恰 120 → 可发（> 为不可发）
    ("weight_equal_22", (30, 20, 15), 22),        # 称重恰 22kg → 可发（> 为不可发）
], ids=["sum-120", "weight-22"])
def test_boundary_billable(quote_client, scp_db, price_sync_cfg, build_payload, md,
                           scenario, dims, weight):
    """TC-QPS-010 (P2) 箱规边界恰好可发（AC-21）。
    注: "最长边=120" 与三边和规则数学上互斥（其余边必须为 0），该组合不设用例，
    已在设计文档登记为需求缺口。"""
    # case_id: TC-QPS-010
    length, width, height = dims
    payload = build_payload(
        carrierIds=[md["carrier_base_id"]],
        warehouse=one_warehouse(md["warehouse_code"], [base_package(length, width, height, weight)]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    row = rows_for(body, md["carrier_base_id"])[0]
    assert row["canShipping"] is True, f"边界值（{scenario}）应为可发，实际 canShipping={row['canShipping']}"
    assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_base_id"],
                            payload["shipTo"]["postcode"], weight)


@pytest.mark.db
@pytest.mark.parametrize("pobox_check,expect_filtered", [
    (200, True),   # 200=不关闭 PO Box 检查 → 邮筒地址不走非澳邮承运商（REQ §2.2/§7）
    (100, False),  # 100=关闭检查 → 不做邮筒过滤，正常计算
], ids=["check-200-filter", "check-100-pass"])
def test_pobox_filter(quote_client, scp_db, price_sync_cfg, build_payload, md,
                      pobox_check, expect_filtered):
    """TC-QPS-011 (P1) PO Box 检查（AC-24/25）：closePoboxCheck=200 邮筒地址只走澳邮；
    =100/缺省不拦截。地址采用 gotcha_001 小写变体 'po box 1234'。
    澳邮承运商未回填时 skip（校准点2）。"""
    # case_id: TC-QPS-011
    au_post = md["au_post_carrier_id"]
    if not au_post:
        pytest.skip("校准点2: au_post_carrier_id 未回填——请从 lsp_carrier 实查澳邮承运商 id")
    dest = dict(price_sync_cfg["destinations"]["dest_a"])
    dest["address1"] = "po box 1234"  # gotcha_001: 大小写/标点变体
    payload = build_payload(
        carrierIds=[md["carrier_base_id"], au_post],
        shipTo=dest,
        closePoboxCheck=pobox_check,
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    base_rows = rows_for(body, md["carrier_base_id"])
    if expect_filtered:
        assert base_rows == [], (
            f"closePoboxCheck=200 时邮筒地址不应返回非澳邮承运商报价，实际 {base_rows}"
        )
    else:
        assert base_rows, "closePoboxCheck=100 时不应拦截邮筒地址，非澳邮承运商应正常报价"


@pytest.mark.smoke
@pytest.mark.db
def test_no_rate_carrier_skipped(quote_client, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-012 (P0) 无价卡承运商不返回报价行，其余正常比价不报错（AC-30，R-037 已闭环）。"""
    # case_id: TC-QPS-012
    no_rate = md["carrier_no_rate_id"]
    if not no_rate:
        pytest.skip("校准点1: carrier_no_rate_id 未回填——请按 lsp_carrier_rate 实查无有效价卡的承运商 id")
    payload = build_payload(carrierIds=[md["carrier_base_id"], no_rate])
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert rows_for(body, no_rate) == [], f"无价卡承运商 {no_rate} 不应出现在 data"
    assert rows_for(body, md["carrier_base_id"]), "有价卡承运商应正常返回"


# ════════════════════════════════════════════════════════════
# P2 负向与鉴权（R-002 闭环前：断言 code != "200" + 计费任务未落库）
# ════════════════════════════════════════════════════════════

@pytest.mark.db
@pytest.mark.parametrize("scenario", [
    "missing_owner_id",
    "missing_order_code",
    "missing_ship_to",
    "missing_warehouse",
    "carrier_fields_both_empty",
    "order_code_over_limit",
    "request_id_at_limit_ok",
], ids=["no-ownerId", "no-orderCode", "no-shipTo", "no-warehouse",
        "no-carrier-both", "orderCode-33", "requestId-64-ok"])
def test_request_validation(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    """TC-QPS-013 (P2) 参数校验族（AC-05/07/12）。
    负向单分支断言：code != "200"（§6 仅 200=成功）且 lsp_quote_task 无该 requestId 任务；
    正向边界（requestId 恰 64 字符）走完整金额现算。"""
    # case_id: TC-QPS-013
    payload = build_payload(carrierIds=[md["carrier_base_id"]])
    if scenario == "missing_owner_id":
        payload.pop("ownerId")
    elif scenario == "missing_order_code":
        payload.pop("orderCode")
    elif scenario == "missing_ship_to":
        payload.pop("shipTo")
    elif scenario == "missing_warehouse":
        payload.pop("warehouse")
    elif scenario == "carrier_fields_both_empty":
        payload.pop("carrierIds")  # 未传策略编码也未传 carrierIds
    elif scenario == "order_code_over_limit":
        payload["orderCode"] = "X" * 33  # DB varchar(32) 超界 1 字符
    elif scenario == "request_id_at_limit_ok":
        payload["requestId"] = "R" * 64  # 恰好上界（AC-07 边界内不误拒）

    response = quote_client.price_sync(payload)
    assert response.status_code in (200, 400), (
        f"状态码应属 200/400，实际 {response.status_code}，响应体: {response.text[:300]}"
    )

    if scenario == "request_id_at_limit_ok":
        body = assert_success_body(response, payload["requestId"], payload["orderCode"])
        row = rows_for(body, md["carrier_base_id"])[0]
        assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_base_id"],
                                payload["shipTo"]["postcode"], 1.15)
        return

    if response.status_code == 200:
        body = response.json()
        assert body.get("code") != "200", (
            f"参数校验失败场景 code 不应为 '200'，实际: {body}"
        )
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": payload["requestId"]})
    assert cnt == 0, f"校验拒绝的请求不应产生计费任务: requestId={payload['requestId']} 落库 {cnt} 条"


@pytest.mark.db
@pytest.mark.parametrize("scenario", ["unknown_carrier", "unknown_warehouse"],
                         ids=["unknown-carrier", "unknown-warehouse"])
def test_master_data_missing(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    """TC-QPS-014 (P2) 主数据引用不存在（AC-13/32）。
    推定口径（R-046 待闭环后固化）:
      - 不存在承运商 ID → 按无价卡口径静默跳过（data 无该行）；
      - 不存在 warehouseCode → 整单失败（code != "200"）且无成功报价任务落库。"""
    # case_id: TC-QPS-014
    if scenario == "unknown_carrier":
        payload = build_payload(carrierIds=[md["carrier_base_id"], "CAR-NOT-EXIST-000000"])
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        assert rows_for(body, "CAR-NOT-EXIST-000000") == [], "不存在的承运商不应返回报价行"
        assert rows_for(body, md["carrier_base_id"]), "有效承运商应正常报价"
    else:
        payload = build_payload(
            carrierIds=[md["carrier_base_id"]],
            warehouse=one_warehouse("WH-NOT-EXIST-0000", [base_package(30, 20, 15, 2)]),
        )
        response = quote_client.price_sync(payload)
        assert response.status_code in (200, 400, 500), (
            f"状态码应属 200/400/500，实际 {response.status_code}"
        )
        if response.status_code == 200:
            body = response.json()
            assert body.get("code") != "200", (
                f"warehouseCode 不存在应计费失败（推定 code=500），实际: {body}"
            )
        cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                         {"request_id": payload["requestId"]})
        assert cnt == 0, f"失败的计费请求不应产生成功报价任务: 落库 {cnt} 条"


@pytest.mark.db
def test_auth_rejected_no_billing(quote_client_noauth, scp_db, price_sync_cfg, build_payload, md):
    """TC-QPS-015 (P1) 鉴权拒绝（AC-35）：无 Token 请求不得产生计费任务。
    HTTP 状态码语义（401/403）挂 R-005，闭环前不锁定状态码断言。"""
    # case_id: TC-QPS-015
    payload = build_payload(carrierIds=[md["carrier_base_id"]])
    response = quote_client_noauth.price_sync(payload)
    assert response.status_code != 200 or not response.json().get("success"), (
        f"无 Token 请求不应成功，实际 HTTP {response.status_code}: {response.text[:300]}"
    )
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": payload["requestId"]})
    assert cnt == 0, f"未鉴权请求不应进入计费: requestId={payload['requestId']} 落库 {cnt} 条"
