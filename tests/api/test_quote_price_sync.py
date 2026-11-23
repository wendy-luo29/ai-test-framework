# -*- coding: utf-8 -*-
"""REQ-002 承运商运费计算同步接口（POST /quote/price_sync）——V1.6 用例集。

设计依据:
    需求     requirements/docs/REQ-002_quote_price_sync.md (V1.6)
    AC 清单  requirements/decomposition/REQ-002-AC-list.yaml（44 条有效 AC + 9 条 retired）
    设计文档 testcases/REQ-002-quote_price/REQ-002-TC-distilled.md

V1.6 口径:
    1. 不做幂等：每次调用生成新计费任务；requestId 仅追踪、非必填。
    2. 接口层只认 carrierStrategyCode（策略编码或 VIR|id|id），carrierIds 仅兼容保留。
    3. 失败按响应体 code="500" + msg 非空 + data=null 断言（HTTP 视为传输层，不强制 500）；
       响应不返回 requestId/orderCode，需按入参查库；参数校验失败不落任务行。
    4. 无价卡三分支、超箱规仅新增承运商失败、PO Box/澳邮过滤移出本接口。
    5. 不鉴权、不经网关：客户端不带 Authorization，也不因 token 缺失 skip。
    6. 金额一律用 lsp_scp 验证 SQL 现算现比（每步四舍五入保留三位）。

运行前提:
    - config/base.yaml: services.lsp_quote.<env> 指向被测环境；
    - 环境变量 TEST_DB_PASSWORD 提供 lsp_scp 只读密码（金额现算/落库用例必需）。
"""

from __future__ import annotations

import copy
import json
import math
import random
import time
import warnings
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
    "shippingCostWithTax": (int, float),
    "surcharge": (int, float),
    "closePoboxCheck": int,
    "isBest": int,
}
# 暂未启用字段（REQ §3.2），成功响应中恒为 null
VO_NULLABLE = ("choiceShippingCost",)


# ────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────

def _suffix() -> str:
    """时间戳+随机后缀，保证 requestId/orderCode 等 id 每次执行唯一。"""
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


def vir(*carrier_ids: str) -> str:
    """构造 VIR 策略编码：VIR|carrierId|carrierId（REQ §2.2/§7）。"""
    return "VIR|" + "|".join(carrier_ids)


def fail_ctx(carrier_id: str, postcode: str, weight: float) -> str:
    return f"carrier_id={carrier_id}, postcode={postcode}, weight={weight}"


def json_or_none(response):
    """非 JSON 响应体（如网关 HTML 页）返回 None，避免用例报错而非干净失败。"""
    try:
        return response.json()
    except ValueError:
        return None


# ────────────────────────────────────────────────────────────
# fixtures（模块内自洽，不依赖根 conftest 修改）
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def price_sync_cfg():
    return get_module_config("lsp_quote", "price_sync")


@pytest.fixture(scope="module")
def quote_client(price_sync_cfg):
    """直连客户端：本接口不鉴权、不经网关，不设置 Authorization。"""
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
    """基于 §4 基础请求体构造请求；每次调用重新生成全部唯一 id。

    默认按 V1.6 口径使用 carrierStrategyCode=VIR|PRO|BASE（移除 deprecated 的 carrierIds）；
    需要其他策略时通过 carrierStrategyCode 覆盖。
    """
    base = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    md = price_sync_cfg["master_data"]
    base.pop("carrierIds", None)  # V1.6：接口层不使用 carrierIds
    base["isPushWms"] = 200       # V1.6：100 推送 / 200 不推送，默认 200
    base["carrierStrategyCode"] = vir(md["carrier_pro_id"], md["carrier_base_id"])
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
# 断言助手
# ────────────────────────────────────────────────────────────

def assert_success_body(response, request_id: str | None = None,
                        order_code: str | None = None) -> dict:
    """L1 HTTP 200 + L2 包装层契约（§3.1）。

    响应不返回 requestId/orderCode（2026-11-23 业务方确认），入参仅用于失败信息与查库定位。
    """
    assert response.status_code == 200, (
        f"HTTP 状态码应为 200，实际 {response.status_code}，响应体: {response.text[:500]}"
    )
    body = response.json()
    for key in ("code", "msg", "tc", "tp", "hasMore", "success", "data"):
        assert key in body, f"包装层缺少字段 {key}，实际: {body}"
    assert body["success"] is True, f"success 应为 true，实际 {body['success']}，msg={body['msg']}"
    assert body["code"] == "200", f"code 应为 '200'，实际 {body['code']}"
    assert isinstance(body["data"], list) and body["data"], (
        f"data 应为非空数组（requestId={request_id}, orderCode={order_code}）"
    )
    return body


def assert_failure_body(response, request_id: str | None = None,
                        order_code: str | None = None) -> dict:
    """失败统一契约（§6/AC-44）：code="500" + msg 非空 + data=null。

    口径（2026-11-23 用户确认）：HTTP 状态码视为传输层，不强制 500，失败以响应体 code 判定；
    code 非 "500" 属实现差异，登记缺陷而非放宽断言。响应不返回 requestId/orderCode，
    入参仅用于失败信息与查库定位。
    """
    body = json_or_none(response)
    assert body is not None, f"失败响应体不是 JSON: {response.text[:500]}"
    assert body.get("code") == "500", (
        f"失败响应 code 应为 '500'，实际: {body}"
        f"（requestId={request_id}, orderCode={order_code}）"
    )
    assert isinstance(body.get("msg"), str) and body["msg"].strip(), (
        f"失败响应 msg 应为非空字符串，实际: {body}"
    )
    assert "data" in body and body["data"] is None, f"失败响应 data 应为 null，实际: {body}"
    assert body.get("success") is False, f"失败响应 success 应为 false，实际: {body}"
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
        "from_zone": price_sync_cfg["master_data"]["warehouse_zone"],
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


def status_task_count(scp_db, price_sync_cfg, request_id: str, status: int) -> int:
    return task_count(scp_db, price_sync_cfg, "task_status_count_by_request",
                      {"request_id": request_id, "status": status})


def base_package(length, width, height, weight, sku="SKU-TEST", cube=None, cube_weight=None):
    """构造单包裹单 SKU，包裹层与 SKU 层尺寸一致。"""
    item = {
        "sku": sku, "qty": 1,
        "length": length, "width": width, "height": height, "weight": weight,
    }
    if cube is not None:
        item["cube"] = cube
    if cube_weight is not None:
        item["cubeWeight"] = cube_weight
    return {
        "packageCode": f"QTP{_suffix()}"[:32],
        "length": length, "width": width, "height": height, "weight": weight,
        "items": [item],
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
    # case_id: TC-QPS-001
    """TC-QPS-001 (P0) 主流程：VIR 双承运商成功 + 响应契约 + 全局择优 + PRO 金额现算 +
    §9.3.1 成功落库（requestId/orderCode 查库校验，响应不返回）。覆盖 AC-01/02/14/18/26/28/49。"""
    payload = build_payload()  # 默认 carrierStrategyCode=VIR|PRO|BASE
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])  # L1+L2

    # L3: 每承运商恰一条内部最优行；行级唯一键 bookingCarrierId 不重复
    assert len(body["data"]) == 2, f"双承运商应恰 2 行，实际 {len(body['data'])} 行: {body['data']}"
    # 金额断言只做 PRO（用户口径）；BASE 只校验参与比价、结构合法且金额为正
    pro_rows = rows_for(body, md["carrier_pro_id"])
    base_rows = rows_for(body, md["carrier_base_id"])
    for carrier_id, rows in ((md["carrier_pro_id"], pro_rows), (md["carrier_base_id"], base_rows)):
        assert len(rows) == 1, f"承运商 {carrier_id} 应恰有 1 条内部最优行，实际 {rows}"
        assert_vo_schema(rows[0])
        assert float(rows[0]["shippingCost"]) > 0, (
            f"承运商 {carrier_id} 参与比价应有正金额，实际 {rows[0]['shippingCost']}"
        )
    assert_zone_rate_amount(scp_db, price_sync_cfg, pro_rows[0], md["carrier_pro_id"],
                            payload["shipTo"]["postcode"], 1.15)

    # L3: 排序——isBest=1 行优先，其余按 shippingCost 升序
    data = body["data"]
    best_indexes = [i for i, r in enumerate(data) if r["isBest"] == 1]
    assert len(best_indexes) == 1, f"isBest=1 应恰一行，实际 {best_indexes}"
    assert best_indexes[0] == 0, f"isBest=1 行应排在 data[0]，实际 index {best_indexes[0]}"
    rest = [r["shippingCost"] for r in data[1:]]
    assert rest == sorted(rest), f"isBest=2 行应按 shippingCost 升序，实际 {rest}"

    # L3: 全局择优——isBest=1 即全局最低
    lowest = min(float(r["shippingCost"]) for r in data)
    assert float(data[0]["shippingCost"]) == lowest, (
        f"isBest=1 行金额 {data[0]['shippingCost']} 不是全局最低 {lowest}"
    )

    # L3: §9.3.1 成功路径必断落库
    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": payload["requestId"]})
    assert len(tasks) == 1, f"成功计费应恰落 1 行 lsp_quote_task，实际 {tasks}"
    task = tasks[0]
    assert task["request_id"] == payload["requestId"], (
        f"落库 request_id 应与入参一致：期望 {payload['requestId']}，实际 {task['request_id']}"
    )
    # 实测落库 order_code 形如 "{入参orderCode}-{6位序号}"（不做幂等，按任务追加序号）；
    # 定位以 request_id 为准，order_code 校验前缀归属。
    assert str(task["order_code"]).startswith(payload["orderCode"]), (
        f"落库 order_code 应以入参为前缀：期望前缀 {payload['orderCode']}，实际 {task['order_code']}"
    )
    assert task["status"] == 200, f"任务 status 应为 200，实际 {task}"
    assert float(task["predict_price"] or 0) > 0, f"predict_price 应 > 0，实际 {task}"
    assert task["predict_carrier_code"], f"predict_carrier_code 应非空，实际 {task}"
    assert int(task["predict_calc_mode"]) in (1, 2), f"predict_calc_mode 应 ∈{{1,2}}，实际 {task}"

    addresses = scp_db.query_all(price_sync_cfg["sql"]["address_rows_by_request"],
                                 {"request_id": payload["requestId"]})
    assert len(addresses) == 2, f"计费地址应恰 2 行（发件/收件），实际 {addresses}"
    assert {a["type"] for a in addresses} == {100, 200}, f"地址 type 应为 100/200，实际 {addresses}"
    by_type = {a["type"]: a for a in addresses}
    assert str(by_type[100]["postcode"]) == md["warehouse_address"]["postcode"], (
        f"发件地址 postcode 应为仓库 postcode，实际 {by_type[100]}"
    )
    assert str(by_type[200]["postcode"]) == payload["shipTo"]["postcode"], (
        f"收件地址 postcode 应为派件 postcode，实际 {by_type[200]}"
    )

    pkg_cnt = task_count(scp_db, price_sync_cfg, "package_count_by_request",
                         {"request_id": payload["requestId"]})
    assert pkg_cnt == 1, f"请求 1 个包裹应落 1 行 lsp_quote_task_package，实际 {pkg_cnt}"
    sku_cnt = task_count(scp_db, price_sync_cfg, "package_sku_count_by_request",
                         {"request_id": payload["requestId"]})
    assert sku_cnt == 1, f"请求 1 条 SKU 明细应落 1 行 package_sku，实际 {sku_cnt}"
    log_cnt = task_count(scp_db, price_sync_cfg, "job_log_count_by_request",
                         {"request_id": payload["requestId"]})
    assert log_cnt >= 1, f"成功计费 job_log 至少 1 行，实际 {log_cnt}"


@pytest.mark.db
def test_zone_mapping_switch(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-004
    """TC-QPS-004 (P0) 两个目的 postcode 各自 zone→价卡段现算。覆盖 AC-20。
    dest_b 未回填时 skip（校准点3）。"""
    dest_b = price_sync_cfg["destinations"]["dest_b"]
    if not dest_b.get("postcode"):
        pytest.skip("校准点3: dest_b 未回填——请从 lsp_carrier_zone 实查与 2000 不同 zone 的 postcode")
    weight = 1.15
    for dest_key in ("dest_a", "dest_b"):
        dest = price_sync_cfg["destinations"][dest_key]
        payload = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"]), shipTo=dest)
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        rows = rows_for(body, md["carrier_pro_id"])
        assert len(rows) == 1, f"{dest_key}: 承运商应恰 1 行，实际 {rows}"
        assert_zone_rate_amount(scp_db, price_sync_cfg, rows[0], md["carrier_pro_id"],
                                dest["postcode"], weight)


@pytest.mark.smoke
@pytest.mark.db
def test_multi_package_sum(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-005
    """TC-QPS-005 (P0) 两包裹一票一件 Σ 现算；PRO 行 calcMode=1。覆盖 AC-17/29。"""
    carrier_id = md["carrier_pro_id"]
    packages = [base_package(30, 12, 10, 5, "SKU-P1"), base_package(60, 20, 15, 10, "SKU-P2")]
    payload = build_payload(
        carrierStrategyCode=vir(carrier_id),
        warehouse=one_warehouse(md["warehouse_code"], packages),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, carrier_id)
    assert len(rows) == 1, f"承运商应恰 1 行，实际 {len(rows)}"
    row = rows[0]
    assert row["calcMode"] == 1, f"多包裹逐个计费应为 calcMode=1（一票一件），实际 {row['calcMode']}"

    postcode = payload["shipTo"]["postcode"]
    expected_total = 0.0
    for pkg in packages:
        rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
            "carrier_id": carrier_id,
            "from_zone": price_sync_cfg["master_data"]["warehouse_zone"],
            "postcode": postcode,
            "weight": chargeable_kg(pkg["weight"]),
        })
        assert rate is not None, (
            f"包裹 {pkg['packageCode']} 未取到价卡段: {fail_ctx(carrier_id, postcode, pkg['weight'])}"
        )
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
def test_per_kg_above_5kg(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-006
    """TC-QPS-006 (P1) 5.1kg→6kg 续重现算（PRO 四段模型）。覆盖 AC-19。"""
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        warehouse=one_warehouse(md["warehouse_code"], [base_package(30, 20, 15, 5.1)]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    row = rows_for(body, md["carrier_pro_id"])[0]
    assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_pro_id"],
                            payload["shipTo"]["postcode"], 5.1)


def test_internal_optimal_two_modes(quote_client, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-007
    """TC-QPS-007 (P1) 非 PRO 承运商参与比价后内部择优。覆盖 AC-27。

    本用例只验证「其他承运商能正常参与并完成择优」，不做金额现算：
    两包一票只返回 1 行，且金额不高于两包分别单独计费之和（取低者）。
    """
    carrier_id = md["carrier_legacy_id"]
    packages = [base_package(30, 12, 10, 5, "SKU-P1"), base_package(60, 20, 15, 10, "SKU-P2")]
    payload = build_payload(
        carrierStrategyCode=vir(carrier_id),
        warehouse=one_warehouse(md["warehouse_code"], packages),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, carrier_id)
    assert len(rows) == 1, f"两层择优后承运商应仅 1 条内部最优行，实际 {len(rows)} 行: {rows}"
    assert rows[0]["canShipping"] is True, "两包均未超箱规，应可发"
    multi = float(rows[0]["shippingCost"])

    # calcMode=1 上界：两包分别单独计费之和
    singles = []
    for pkg in packages:
        single_payload = build_payload(
            carrierStrategyCode=vir(carrier_id),
            warehouse=one_warehouse(md["warehouse_code"], [copy.deepcopy(pkg)]),
        )
        single_body = assert_success_body(quote_client.price_sync(single_payload),
                                          single_payload["requestId"], single_payload["orderCode"])
        singles.append(float(rows_for(single_body, carrier_id)[0]["shippingCost"]))
    assert multi <= money(sum(singles)) + 0.001, (
        f"内部择优金额 {multi} 不应高于分包裹计费之和 {money(sum(singles))}（应取较低者）"
    )


@pytest.mark.db
@pytest.mark.parametrize("scenario,packages,charge_weight", [
    ("single_sku_fallback", [{
        # 包裹层全 0，SKU 层有值（SKU 尺寸/重量不可为 0，否则后端报 No Quote Rate Card）
        "packageCode": f"QTP{_suffix()}"[:32],
        "length": 0, "width": 0, "height": 0, "weight": 0,
        "items": [{"sku": "SKU-FALL", "qty": 1, "length": 15, "width": 10, "height": 8, "weight": 1.15}],
    }], 1.15),
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
    # case_id: TC-QPS-008
    """TC-QPS-008 (P1) 包裹层全 0 取 SKU；多 SKU 组包（qty=1，规避累加基数）。覆盖 AC-15/16。"""
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        warehouse=one_warehouse(md["warehouse_code"], copy.deepcopy(packages)),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    row = rows_for(body, md["carrier_pro_id"])[0]
    assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_pro_id"],
                            payload["shipTo"]["postcode"], charge_weight)


@pytest.mark.db
@pytest.mark.parametrize("scenario,dims,weight", [
    ("sum_125", (80, 25, 20), 5),        # 三边和 125：上界+5cm
    ("sum_120_01", (80, 25.01, 15), 5),  # 三边和 120.01：上界+0.01，边界点
    ("weight_22_01", (30, 20, 15), 22.01),  # 原始称重 22.01：上界+0.01，边界点
], ids=["sum-125", "sum-120.01", "weight-22.01"])
def test_oversized_carrier_filtered(quote_client, scp_db, price_sync_cfg, build_payload, md, rules,
                                    scenario, dims, weight):
    # case_id: TC-QPS-009
    """TC-QPS-009 (P1) 新增承运商超箱规被过滤，老承运商正常。覆盖 AC-22。"""
    length, width, height = dims
    assert (length + width + height > rules["max_sum_cm"]
            or weight > rules["max_weight_kg"]), f"{scenario} 未超过箱规上限"
    oversized = base_package(length, width, height, weight)
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"], md["carrier_base_id"]),
        warehouse=one_warehouse(md["warehouse_code"], [oversized]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert rows_for(body, md["carrier_pro_id"]) == [], (
        "超箱规新增承运商不应出现在 data（REQ §7：过滤新增承运商）"
    )
    assert rows_for(body, md["carrier_base_id"]), "未超箱规老承运商应正常返回报价行"


@pytest.mark.db
@pytest.mark.parametrize("scenario,dims,weight", [
    ("sum_equal_120", (119.9, 0.05, 0.05), 5),   # 三边和恰 120 → 可发（> 为不可发）
    ("weight_equal_22", (30, 20, 15), 22),        # 原始称重恰 22kg → 可发
], ids=["sum-120", "weight-22"])
def test_boundary_billable(quote_client, scp_db, price_sync_cfg, build_payload, md,
                           scenario, dims, weight):
    # case_id: TC-QPS-010
    """TC-QPS-010 (P2) 三边和恰 120、原始称重恰 22 可发。覆盖 AC-21。"""
    length, width, height = dims
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        warehouse=one_warehouse(md["warehouse_code"], [base_package(length, width, height, weight)]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    row = rows_for(body, md["carrier_pro_id"])[0]
    assert row["canShipping"] is True, f"边界值（{scenario}）应为可发，实际 {row['canShipping']}"
    assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_pro_id"],
                            payload["shipTo"]["postcode"], weight)


@pytest.mark.smoke
@pytest.mark.db
def test_no_rate_carrier_skipped(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-012
    """TC-QPS-012 (P0) 多承运商中无价卡被过滤，其余正常。覆盖 AC-30。"""
    no_rate = md["carrier_no_rate_id"]
    if not no_rate:
        pytest.skip("范围内（ubi/broers status=100）8 家均有价卡，无真实无价卡夹具；"
                    "VIR 强制指定无价卡承运商返回 0 元属特殊场景，不纳入本用例")
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"], no_rate))
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert rows_for(body, no_rate) == [], f"无价卡承运商 {no_rate} 不应出现在 data"
    assert rows_for(body, md["carrier_base_id"]), "有价卡承运商应正常返回"


# ════════════════════════════════════════════════════════════
# P2 负向与边界
# ════════════════════════════════════════════════════════════

@pytest.mark.db
@pytest.mark.parametrize("scenario", [
    "missing_owner_id",
    "missing_order_code",
    "missing_ship_to",
    "missing_warehouse",
    "carrier_strategy_empty",
    "order_code_over_limit",
    "request_id_at_limit_ok",
], ids=["no-ownerId", "no-orderCode", "no-shipTo", "no-warehouse",
        "empty-strategy", "orderCode-33", "requestId-64-ok"])
def test_request_validation(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-013
    """TC-QPS-013 (P2) 必填缺失/长度越界/策略空 → 500；requestId 64 正常。覆盖 AC-05/07/12。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"]))
    if scenario == "missing_owner_id":
        payload.pop("ownerId")
    elif scenario == "missing_order_code":
        payload.pop("orderCode")
    elif scenario == "missing_ship_to":
        payload.pop("shipTo")
    elif scenario == "missing_warehouse":
        payload.pop("warehouse")
    elif scenario == "carrier_strategy_empty":
        payload["carrierStrategyCode"] = ""
    elif scenario == "order_code_over_limit":
        payload["orderCode"] = "X" * 33  # DB varchar(32) 超界 1 字符
    elif scenario == "request_id_at_limit_ok":
        payload["requestId"] = "R" * 64  # 恰好上界（边界内不误拒）

    response = quote_client.price_sync(payload)
    if scenario == "request_id_at_limit_ok":
        body = assert_success_body(response, payload["requestId"], payload["orderCode"])
        row = rows_for(body, md["carrier_pro_id"])[0]
        assert_zone_rate_amount(scp_db, price_sync_cfg, row, md["carrier_pro_id"],
                                payload["shipTo"]["postcode"], 1.15)
        return

    assert_failure_body(response)
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": payload["requestId"]})
    assert cnt == 0, f"参数校验拒绝的请求不应落任务行: requestId={payload['requestId']} 落库 {cnt} 条"


@pytest.mark.db
@pytest.mark.parametrize("scenario", ["unknown_warehouse", "unknown_carrier"],
                         ids=["unknown-warehouse", "unknown-carrier"])
def test_master_data_missing(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-014
    """TC-QPS-014 (P2) 未知仓库→500 落 status=300；VIR 中 carrierId 不存在→500 不落行。
    覆盖 AC-32/39。

    已知缺陷：D-08（未知仓库仍计费成功）、D-09（不存在 carrierId 被忽略仍返回报价），
    本用例按需求断言，修复前应失败。
    """
    if scenario == "unknown_warehouse":
        payload = build_payload(
            carrierStrategyCode=vir(md["carrier_base_id"]),
            warehouse=one_warehouse("WH-NOT-EXIST-0000", [base_package(30, 20, 15, 2)]),
        )
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
        assert failed >= 1, f"未知仓库应落 status=300 失败行，实际 {failed} 行"
        success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                             {"request_id": payload["requestId"]})
        assert success == 0, f"未知仓库不应产生成功任务，实际 {success} 行"
    else:
        payload = build_payload(
            carrierStrategyCode=vir(md["carrier_base_id"], "CAR-NOT-EXIST-000000"),
        )
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                         {"request_id": payload["requestId"]})
        assert cnt == 0, f"VIR 中 carrierId 不存在应不落任务行，实际 {cnt} 条"


@pytest.mark.db
def test_volume_weight_not_billed(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-016
    """TC-QPS-016 (P1) 体积重>实重仍按称重段现算。覆盖 AC-14。"""
    carrier_id = md["carrier_pro_id"]
    pkg = base_package(60.5, 30, 15, 1.15, cube=0.027, cube_weight=6.806)
    payload = build_payload(
        carrierStrategyCode=vir(carrier_id),
        warehouse=one_warehouse(md["warehouse_code"], [pkg]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, carrier_id)
    assert len(rows) == 1, f"承运商应恰 1 行，实际 {len(rows)} 行"
    row = rows[0]
    postcode = payload["shipTo"]["postcode"]
    actual = assert_zone_rate_amount(scp_db, price_sync_cfg, row, carrier_id, postcode, 1.15)

    # 反向核对：体积重 6.806 → ceil=7kg 段金额不得与响应一致
    volume_kg = chargeable_kg(6.806)
    volume_rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
        "carrier_id": carrier_id,
        "from_zone": price_sync_cfg["master_data"]["warehouse_zone"],
        "postcode": postcode,
        "weight": volume_kg,
    })
    assert volume_rate is not None, f"未取到 {volume_kg}kg 段价卡，无法做体积重反向核对"
    volume_cost = expected_cost(volume_rate, volume_kg, price_sync_cfg["rules"]["basic_limit_kg"])
    assert abs(actual - volume_cost) > 0.0005, (
        f"金额 {actual} 与体积重 {volume_kg}kg 段现算 {volume_cost} 一致，说明体积重参与了计价"
    )


@pytest.mark.db
def test_box_rule_per_package(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-017
    """TC-QPS-017 (P2) 箱规按单包裹判定（两包各 21.5kg 可发）。覆盖 AC-21。"""
    carrier_id = md["carrier_pro_id"]
    packages = [base_package(30, 20, 15, 21.5, "SKU-B1"),
                base_package(30, 20, 15, 21.5, "SKU-B2")]
    payload = build_payload(
        carrierStrategyCode=vir(carrier_id),
        warehouse=one_warehouse(md["warehouse_code"], packages),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, carrier_id)
    assert len(rows) == 1, f"单包裹箱规均合法时应正常返回 1 行，实际 {len(rows)} 行: {rows}"
    row = rows[0]
    assert row["calcMode"] == 1, f"PRO 承运商仅支持一票一件，calcMode 应为 1，实际 {row['calcMode']}"

    postcode = payload["shipTo"]["postcode"]
    weight = 21.5
    rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
        "carrier_id": carrier_id,
        "from_zone": price_sync_cfg["master_data"]["warehouse_zone"],
        "postcode": postcode,
        "weight": chargeable_kg(weight),
    })
    assert rate is not None, f"未取到 {chargeable_kg(weight)}kg 段价卡: {fail_ctx(carrier_id, postcode, weight)}"
    per_pkg = expected_cost(rate, chargeable_kg(weight), price_sync_cfg["rules"]["basic_limit_kg"])
    expected_total = money(per_pkg + per_pkg)
    actual = float(row["shippingCost"])
    assert abs(actual - expected_total) <= 0.0005, (
        f"两包各按 22kg 段现算之和应为 {expected_total}，实际 {actual}"
    )


@pytest.mark.db
def test_invalid_push_result_to(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-019
    """TC-QPS-019 (P2) pushResultTo=100 非法→500 且不落行。覆盖 AC-08。"""
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_base_id"]),
        pushResultTo=100,
    )
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": payload["requestId"]})
    assert cnt == 0, f"非法枚举请求不应进入计费: requestId={payload['requestId']} 落库 {cnt} 条"


# ════════════════════════════════════════════════════════════
# P1 新口径：不幂等 / 参数/策略校验 / 失败契约
# ════════════════════════════════════════════════════════════

@pytest.mark.db
def test_no_idempotent_replay(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-020
    """TC-QPS-020 (P1) 相同 requestId+orderCode 连调两次→两次都成功，任务数+1（不幂等）。
    覆盖 AC-45。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    params = {"request_id": payload["requestId"], "order_code": payload["orderCode"]}
    first = assert_success_body(quote_client.price_sync(payload),
                                payload["requestId"], payload["orderCode"])
    count_before = task_count(scp_db, price_sync_cfg, "task_count_by_request_order", params)
    assert count_before == 1, f"首次调用应落 1 行任务，实际 {count_before}"

    second = assert_success_body(quote_client.price_sync(payload),
                                 payload["requestId"], payload["orderCode"])
    count_after = task_count(scp_db, price_sync_cfg, "task_count_by_request_order", params)
    assert count_after == count_before + 1, (
        f"不幂等：第二次调用应新增 1 行任务，调用前 {count_before}，调用后 {count_after}"
    )
    assert second["data"], "第二次调用应返回新报价结果"
    assert sorted((r["bookingCarrierId"], float(r["shippingCost"])) for r in first["data"]) == \
        sorted((r["bookingCarrierId"], float(r["shippingCost"])) for r in second["data"]), (
        "相同入参两次计算的报价应一致"
    )


@pytest.mark.db
@pytest.mark.parametrize("scenario", ["partial_zero", "duplicate_package_code"],
                         ids=["partial-zero", "duplicate-packageCode"])
def test_package_validation(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-021
    """TC-QPS-021 (P1) 包裹层部分为 0→500；packageCode 重复→500；均不落行。覆盖 AC-36/37。"""
    if scenario == "partial_zero":
        pkg = base_package(30, 10, 10, 1)
        pkg["width"] = 0  # length/height/weight 有效，仅 width=0 → 部分为 0
        packages = [pkg]
    else:
        pkg = base_package(30, 20, 15, 2)
        duplicate = copy.deepcopy(pkg)
        packages = [pkg, duplicate]

    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_base_id"]),
        warehouse=one_warehouse(md["warehouse_code"], packages),
    )
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": payload["requestId"]})
    assert cnt == 0, f"{scenario} 参数校验失败不应落任务行，实际 {cnt} 条"


@pytest.mark.db
@pytest.mark.parametrize("scenario", ["vir_malformed", "strategy_not_exist", "strategy_empty_refs"],
                         ids=["vir-malformed", "strategy-not-exist", "strategy-empty-refs"])
def test_strategy_validation(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-022
    """TC-QPS-022 (P2) VIR 段非法、策略编码不存在、策略绑定空集合→500。覆盖 AC-38/40。

    分层口径：VIR 非法/策略不存在属策略校验（不落任务行，实测 D-05 为超时不返回）；
    策略绑定空集合属「无可用承运商」计费失败，按 C-03 应落 status=300 行。
    """
    if scenario == "vir_malformed":
        strategy = "VIR|"  # 缺段
    elif scenario == "strategy_not_exist":
        strategy = "NO_SUCH_STRATEGY"
    else:
        strategy = md.get("strategy_empty_code") or ""
        if not strategy:
            pytest.skip("校准点7: strategy_empty_code 未回填——请从 lsp_carrier_strategy 实查绑定空承运商集合的策略编码")

    payload = build_payload(carrierStrategyCode=strategy)
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    if scenario == "strategy_empty_refs":
        failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
        assert failed >= 1, f"无可用承运商应落 status=300 失败行，实际 {failed} 行"
        success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                             {"request_id": payload["requestId"]})
        assert success == 0, f"无可用承运商不应产生成功任务，实际 {success} 行"
        return
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": payload["requestId"]})
    assert cnt == 0, f"{scenario} 策略校验失败不应落任务行，实际 {cnt} 条"


@pytest.mark.db
def test_only_new_carrier_oversized_fails(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-023
    """TC-QPS-023 (P1) 仅新增承运商参与且超箱规→500，落 status=300。覆盖 AC-23。"""
    pkg = base_package(80, 25, 20, 5)  # 三边和 125 > 120
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        warehouse=one_warehouse(md["warehouse_code"], [pkg]),
    )
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
    assert failed >= 1, f"仅新增承运商超箱规应落 status=300 失败行，实际 {failed} 行"
    success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                         {"request_id": payload["requestId"]})
    assert success == 0, f"该场景不应产生成功任务，实际 {success} 行"


@pytest.mark.db
def test_failure_contract(quote_client, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-024
    """TC-QPS-024 (P1) 失败统一契约：code="500" + msg 非空 + data=null + success=false
    （HTTP 不强制；响应不含 requestId/orderCode）。覆盖 AC-44。"""
    payload = build_payload(carrierStrategyCode=md["strategy_empty_code"])  # 空集合策略→确定性失败
    body = assert_failure_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    for key in ("code", "msg", "success", "data"):
        assert key in body, f"失败响应缺少字段 {key}，实际: {body}"


@pytest.mark.db
@pytest.mark.parametrize("scenario", ["single_no_rate", "all_no_rate"],
                         ids=["single-no-rate", "all-no-rate"])
def test_no_rate_failure(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-025
    """TC-QPS-025 (P1) 单承运商无价卡→500；全无价卡→500；均落 status=300。覆盖 AC-51/52。"""
    no_rate = md["carrier_no_rate_id"]
    if not no_rate:
        pytest.skip("范围内（ubi/broers status=100）8 家均有价卡，无真实无价卡夹具；"
                    "VIR 强制指定无价卡承运商返回 0 元属特殊场景，不纳入本用例")
    if scenario == "single_no_rate":
        carriers = [no_rate]
    else:
        no_rate_2 = md.get("carrier_no_rate_id_2") or ""
        if not no_rate_2:
            pytest.skip("校准点5: carrier_no_rate_id_2 未回填——请再实查一个无有效价卡承运商以覆盖 AC-52")
        carriers = [no_rate, no_rate_2]

    payload = build_payload(carrierStrategyCode=vir(*carriers))
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
    assert failed >= 1, f"无价卡计费失败应落 status=300 失败行，实际 {failed} 行"
    success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                         {"request_id": payload["requestId"]})
    assert success == 0, f"无价卡场景不应产生成功任务，实际 {success} 行"


@pytest.mark.db
def test_tie_break_order(quote_client, price_sync_cfg, build_payload):
    # case_id: TC-QPS-026
    """TC-QPS-026 (P1) 若 data 中存在金额并列，断言 isBest=1 是并列中排序第一条；
    无并列则 skip 并说明。覆盖 AC-48。"""
    body = assert_success_body(quote_client.price_sync(build_payload()))
    data = body["data"]
    costs = [float(r["shippingCost"]) for r in data]
    lowest = min(costs)
    tied_indexes = [i for i, c in enumerate(costs) if c == lowest]
    if len(tied_indexes) < 2:
        pytest.skip(f"本次主数据下未出现金额并列（costs={costs}），无法验证并列排序规则")

    assert data[0]["isBest"] == 1, f"并列场景 isBest=1 应排在第一名，实际: {data}"
    assert float(data[0]["shippingCost"]) == lowest, (
        f"并列场景 isBest=1 应为并列金额第一条，实际 {data[0]}，并列下标 {tied_indexes}"
    )
    assert sum(1 for r in data if r["isBest"] == 1) == 1, "isBest=1 应恰一行"


@pytest.mark.db
def test_failure_persistence(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-027
    """TC-QPS-027 (P1) 计算失败落 status=300、predict_price=0、carrier 空；参数校验不落行；
    job_log 软断言。覆盖 AC-50。"""
    no_rate = md["carrier_no_rate_id"]
    if not no_rate:
        pytest.skip("范围内（ubi/broers status=100）8 家均有价卡，无真实无价卡夹具；"
                    "无价卡计算失败分支暂无法构造")

    calc_payload = build_payload(carrierStrategyCode=vir(no_rate))
    assert_failure_body(quote_client.price_sync(calc_payload),
                        calc_payload["requestId"], calc_payload["orderCode"])
    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": calc_payload["requestId"]})
    assert len(tasks) == 1, f"计算失败应落 1 行任务，实际 {tasks}"
    task = tasks[0]
    assert task["status"] == 300, f"计算失败任务 status 应为 300，实际 {task}"
    assert float(task["predict_price"] or 0) == 0, f"计算失败 predict_price 应为 0，实际 {task}"
    assert not task["predict_carrier_code"], f"计算失败 predict_carrier_code 应为空，实际 {task}"

    log_cnt = task_count(scp_db, price_sync_cfg, "job_log_count_by_request",
                         {"request_id": calc_payload["requestId"]})
    if log_cnt == 0:
        warnings.warn(
            "AC-50: 计算失败场景未查到 lsp_quote_task_job_log 记录（软断言，待联调确认）",
            stacklevel=2,
        )

    # 参数校验拒绝：不落任何任务行
    invalid = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    invalid.pop("ownerId")
    assert_failure_body(quote_client.price_sync(invalid))
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request",
                     {"request_id": invalid["requestId"]})
    assert cnt == 0, f"参数校验拒绝不应落任务行，实际 {cnt} 条"


@pytest.mark.db
def test_strategy_code_billing(quote_client, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-028
    """TC-QPS-028 (P1) carrierStrategyCode=quote_price 计费；
    承运商范围按用户口径 carrier_agent_code in ('ubi','broers') AND status=100（8 家）校验，
    策略额外返回的 dfe/shippit 承运商不属于本次比价范围，仅告警不判失败。覆盖 AC-10。"""
    strategy = md.get("strategy_code") or ""
    if not strategy:
        pytest.skip("strategy_code 未配置——请在 config/lsp_quote/price_sync.yaml master_data 回填策略编码")
    refs = set(md.get("strategy_refs") or [])
    if not refs:
        pytest.skip("校准点6: strategy_refs 未回填——请按 ubi/broers 有效承运商回填")

    payload = build_payload(carrierStrategyCode=strategy)
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    actual_ids = {r["bookingCarrierId"] for r in body["data"]}
    in_scope = actual_ids & refs
    assert in_scope, (
        f"策略 {strategy} 未返回 ubi/broers 范围内的承运商报价（范围={sorted(refs)}，实际={actual_ids}）"
    )
    out_of_scope = actual_ids - refs
    if out_of_scope:
        warnings.warn(
            f"AC-10: 策略 {strategy} 额外返回范围外承运商 {sorted(out_of_scope)}"
            f"（dfe/shippit 不在 ubi/broers 范围，已从比价断言中排除）",
            stacklevel=2,
        )


# ════════════════════════════════════════════════════════════
# P2 地址与透传字段
# ════════════════════════════════════════════════════════════

@pytest.mark.db
@pytest.mark.parametrize("country,expect_ok", [
    ("AU", True),
    ("au", True),
    ("Australia", True),
    ("NZ", False),
], ids=["AU", "au", "Australia", "NZ"])
def test_country_and_state(quote_client, scp_db, price_sync_cfg, build_payload, md,
                           country, expect_ok):
    # case_id: TC-QPS-029
    """TC-QPS-029 (P2) country=AU/au/Australia 通过、NZ→500；state 全称通过且落库简称。
    覆盖 AC-41/42。"""
    dest = dict(price_sync_cfg["destinations"]["dest_a"])
    dest["country"] = country
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]), shipTo=dest)

    if not expect_ok:
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        return

    assert_success_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])

    if country != "AU":
        return

    # state 全称：接口通过，落库简称（AC-42）
    full_state = dict(dest)
    full_state["state"] = "New South Wales"
    state_payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]), shipTo=full_state)
    assert_success_body(quote_client.price_sync(state_payload),
                        state_payload["requestId"], state_payload["orderCode"])
    addresses = scp_db.query_all(price_sync_cfg["sql"]["address_rows_by_request"],
                                 {"request_id": state_payload["requestId"]})
    ship_to_rows = [a for a in addresses if a["type"] == 200]
    assert len(ship_to_rows) == 1, f"应恰 1 行收件地址（type=200），实际 {addresses}"
    assert ship_to_rows[0]["state"] == "NSW", (
        f"state 全称应落库为简称 NSW，实际 {ship_to_rows[0]['state']}"
    )


@pytest.mark.smoke
@pytest.mark.db
@pytest.mark.parametrize("scenario", ["shipping_arbitrary", "pobox_check_100", "pobox_check_200"],
                         ids=["shipping-arbitrary", "pobox-100", "pobox-200"])
def test_passthrough_fields(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-030
    """TC-QPS-030 (P2) shippingType/shipmentType 任意值不影响计费；closePoboxCheck 100/200
    均正常计费（PO Box 地址不拦截）。覆盖 AC-46/47。"""
    overrides = {}
    expected_pobox = 200
    dest = dict(price_sync_cfg["destinations"]["dest_a"])
    if scenario == "shipping_arbitrary":
        overrides.update(shippingType=300, shipmentType="ANY-STRING")
    else:
        dest["address1"] = "po box 1234"  # PO Box 形式地址
        expected_pobox = 100 if scenario == "pobox_check_100" else 200
        overrides["closePoboxCheck"] = expected_pobox

    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"], md["carrier_base_id"]),
        shipTo=dest,
        **overrides,
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert len(body["data"]) == 2, f"两个承运商均应正常计费，实际 {body['data']}"
    for carrier_id in (md["carrier_pro_id"], md["carrier_base_id"]):
        row = rows_for(body, carrier_id)[0]
        assert row["closePoboxCheck"] == expected_pobox, (
            f"closePoboxCheck 应回显 {expected_pobox}，实际 {row['closePoboxCheck']}"
        )
    assert_zone_rate_amount(scp_db, price_sync_cfg, rows_for(body, md["carrier_pro_id"])[0],
                            md["carrier_pro_id"], dest["postcode"], 1.15)


@pytest.mark.db
def test_carrier_ids_ignored(quote_client, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-031
    """TC-QPS-031 (P2) 同时传 carrierIds 与 VIR 策略，结果只覆盖策略承运商。覆盖 AC-43。

    已知缺陷 D-07：实测 carrierIds 仍优先生效（双向验证均以 carrierIds 为准），
    本用例按需求断言，修复前应失败。
    """
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        carrierIds=[md["carrier_base_id"]],  # deprecated 字段，不参与选承运商
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    actual_ids = {r["bookingCarrierId"] for r in body["data"]}
    assert actual_ids == {md["carrier_pro_id"]}, (
        f"同时传 carrierIds 时应只按 carrierStrategyCode 选承运商，实际 {actual_ids}"
    )


@pytest.mark.db
def test_missing_request_id(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-032
    """TC-QPS-032 (P2) 不传 requestId 仍正常计费（不做幂等）。覆盖 AC-06。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    payload.pop("requestId")
    body = assert_success_body(quote_client.price_sync(payload),
                               request_id=None, order_code=payload["orderCode"])
    assert rows_for(body, md["carrier_base_id"]), "不传 requestId 仍应返回报价行"
    success = task_count(scp_db, price_sync_cfg, "task_success_count_by_order",
                         {"order_code": payload["orderCode"]})
    assert success >= 1, f"不传 requestId 仍应落成功任务（按 orderCode 查），实际 {success} 行"


def test_carrier_timeout(quote_client, build_payload):
    # case_id: TC-QPS-033
    """TC-QPS-033 (P2) 承运商超时→500；无故障注入手段时 skip。覆盖 AC-31。"""
    pytest.skip("AC-31 需要承运商询价超时故障注入（Mock/网络延迟），当前环境无注入手段；"
                "待提供故障注入方案后按 HTTP 500 + code='500' + status=300 落库补齐")


def test_schema_upper_bound(quote_client, build_payload):
    # case_id: TC-QPS-034
    """TC-QPS-034 (P2) M-007 schema 上限用例：未闭环，skip 并说明。覆盖 AC-53。"""
    pytest.skip("AC-53 依赖 M-007（数组 maxItems / 数值上限 / 响应必填等 schema 约束）闭环；"
                "闭环前按需求约定不设计上限用例")
