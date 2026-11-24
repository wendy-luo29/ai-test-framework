# -*- coding: utf-8 -*-
"""REQ-002 承运商运费计算同步接口（POST /quote/price_sync）——36 条用例。

用例来源（以此 3 份 JSON 为唯一依据，Excel 由其导出）:
    testcases/REQ-002-quote_price/output/cases_batch_1.json  （契约层 9 条）
    testcases/REQ-002-quote_price/output/cases_batch_2.json  （箱规/价卡/仓区 14 条）
    testcases/REQ-002-quote_price/output/cases_batch_3.json  （策略/异常 13 条）

口径:
    1. 不做幂等：每次调用生成新计费任务；requestId 仅追踪、非必填。
    2. 接口层只认 carrierStrategyCode（策略编码或 VIR|id|id），carrierIds 仅兼容保留。
    3. 失败按响应体 code="500" + msg 非空 + data=null 断言（HTTP 视为传输层，不强制 500）；
       响应不返回 requestId/orderCode，需按入参查库；参数校验失败不落任务行。
    4. 金额一律用 lsp_scp 验证 SQL 现算现比（每步四舍五入保留三位）。
    5. 已知缺陷（D-01~D-09）相关用例标 xfail(strict=False)；缺夹具用例运行时 skip。

运行前提:
    - config/base.yaml + env.yaml 的 services.lsp_quote.<env> 指向被测环境；
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


# 本轮运行标识：批量按 order_code 前缀断言时隔离历次运行数据
RUN_ID = _suffix()
# 落库 order_code 会追加「-6 位序号」且列为 varchar(32)，批量前缀必须留出后缀空间
BATCH_ID = RUN_ID[-8:]
PASS_PREFIX = f"TESTSOPASS{BATCH_ID}-"   # 19 字符，+序号后仍 ≤32
BOX_PREFIX = f"TESTSOBOX{BATCH_ID}-"     # 18 字符，+序号后仍 ≤32


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


def _node(payload: dict, path: tuple):
    node = payload
    for key in path[:-1]:
        node = node[key]
    return node


def drop_field(payload: dict, path: tuple) -> None:
    """按路径删除字段（支持 list 下标）。"""
    _node(payload, path).pop(path[-1], None)


def set_field(payload: dict, path: tuple, value) -> None:
    """按路径覆盖字段（支持 list 下标）。"""
    _node(payload, path)[path[-1]] = value


# ────────────────────────────────────────────────────────────
# fixtures
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

    默认按 V1.6 口径使用 carrierStrategyCode=VIR|PRO|Aramex，并移除 deprecated 的 carrierIds。
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
    """L1 HTTP 200 + L2 包装层契约（§3.1）。响应不返回 requestId/orderCode。"""
    assert response.status_code == 200, (
        f"HTTP 状态码应为 200，实际 {response.status_code}，响应体: {response.text[:500]}"
    )
    body = response.json()
    for key in ("code", "msg", "tc", "tp", "hasMore", "success", "data"):
        assert key in body, f"包装层缺少字段 {key}，实际: {body}"
    assert body["success"] is True, f"success 应为 true，实际 {body['success']}，msg={body['msg']}"
    assert body["code"] == "200", f"code 应为 '200'，实际 {body['code']}"
    assert "requestId" not in body and "orderCode" not in body, (
        f"同步响应不应返回 requestId/orderCode（2026-11-23 业务方确认），实际: {body}"
    )
    assert isinstance(body["data"], list) and body["data"], (
        f"data 应为非空数组（requestId={request_id}, orderCode={order_code}）"
    )
    return body


def assert_failure_body(response, request_id: str | None = None,
                        order_code: str | None = None) -> dict:
    """失败统一契约（§6/AC-44）：code="500" + msg 非空 + data=null + success=false。

    口径（2026-11-23 用户确认）：HTTP 状态码视为传输层，不强制 500，失败以响应体 code 判定。
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
                            postcode: str, weight_kg: float,
                            from_zone: str | None = None) -> float:
    """L3 金额现算现比：zone→价卡段 SQL 实查 → 公式复算 → 与响应值比对。"""
    zone = from_zone or price_sync_cfg["master_data"]["warehouse_zone"]
    rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
        "carrier_id": carrier_id,
        "from_zone": zone,
        "postcode": postcode,
        "weight": chargeable_kg(weight_kg),
    })
    assert rate is not None, (
        f"验证 SQL 未取到价卡（请先校准 config/lsp_quote/price_sync.yaml sql.zone_rate 列名）: "
        f"from_zone={zone}, {fail_ctx(carrier_id, postcode, weight_kg)}"
    )
    expected = expected_cost(rate, chargeable_kg(weight_kg), price_sync_cfg["rules"]["basic_limit_kg"])
    actual = float(row["shippingCost"])
    assert abs(actual - expected) <= 0.0005, (
        f"运费与 SQL 现算不一致: 期望 {expected}，实际 {actual}；"
        f"价卡行 fee={rate['fee']} per_kg={rate.get('per_kilogram_fee')} fuel={rate['fuel_rate']}；"
        f"from_zone={zone}, {fail_ctx(carrier_id, postcode, weight_kg)}"
    )
    return actual


def task_count(scp_db, price_sync_cfg, sql_key: str, param: dict) -> int:
    cnt = scp_db.scalar(price_sync_cfg["sql"][sql_key], param)
    assert cnt is not None, f"计数 SQL 未返回结果: {sql_key} {param}（请校准 sql 模板）"
    return int(cnt)


def status_task_count(scp_db, price_sync_cfg, request_id: str, status: int) -> int:
    return task_count(scp_db, price_sync_cfg, "task_status_count_by_request",
                      {"request_id": request_id, "status": status})


def assert_no_task(scp_db, price_sync_cfg, request_id: str) -> None:
    cnt = task_count(scp_db, price_sync_cfg, "task_count_by_request", {"request_id": request_id})
    assert cnt == 0, f"该请求不应落任务行: requestId={request_id} 落库 {cnt} 条"


def base_package(length, width, height, weight, sku="SKU-TEST", cube=None, cube_weight=None,
                 package_code=None):
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
        "packageCode": package_code or f"QTP{_suffix()}"[:32],
        "length": length, "width": width, "height": height, "weight": weight,
        "items": [item],
    }


def one_warehouse(warehouse_code: str, packages: list[dict],
                  address: dict | None = None) -> list[dict]:
    wh = {
        "warehouseCode": warehouse_code,
        "shipmentCode": f"TS{_suffix()}"[:64],
        "country": "AU", "state": "VIC", "suburb": "Maidstone",
        "postcode": "3012", "address1": "C 35-77 Emu Road",
        "packages": packages,
    }
    if address:
        wh.update(address)
    return [wh]


def dest(postcode: str, state: str, suburb: str) -> dict:
    return {
        "country": "AU", "state": state, "suburb": suburb,
        "postcode": postcode, "address1": "1 Test Street", "address2": "",
    }


# ════════════════════════════════════════════════════════════
# 契约层（9 条）
# ════════════════════════════════════════════════════════════

REQUIRED_DROP = [
    ("ownerId", ("ownerId",)),
    ("orderCode", ("orderCode",)),
    ("shipTo", ("shipTo",)),
    ("warehouse", ("warehouse",)),
    ("warehouseCode", ("warehouse", 0, "warehouseCode")),
    ("shipmentCode", ("warehouse", 0, "shipmentCode")),
    ("packages", ("warehouse", 0, "packages")),
    ("packageCode", ("warehouse", 0, "packages", 0, "packageCode")),
    ("items", ("warehouse", 0, "packages", 0, "items")),
    ("sku", ("warehouse", 0, "packages", 0, "items", 0, "sku")),
    ("qty", ("warehouse", 0, "packages", 0, "items", 0, "qty")),
    ("length", ("warehouse", 0, "packages", 0, "items", 0, "length")),
    ("shipTo.country", ("shipTo", "country")),
    ("shipTo.state", ("shipTo", "state")),
    ("shipTo.suburb", ("shipTo", "suburb")),
    ("shipTo.postcode", ("shipTo", "postcode")),
    ("shipTo.address1", ("shipTo", "address1")),
]


@pytest.mark.xfail(strict=False, reason="D-01：必填缺失实测返回 code='400'（需求要求统一 '500'）")
@pytest.mark.db
@pytest.mark.parametrize("field,path", REQUIRED_DROP, ids=[c[0] for c in REQUIRED_DROP])
def test_required_fields_missing(quote_client, scp_db, price_sync_cfg, build_payload, md,
                                 field, path):
    # case_id: TC-QPS-013
    """TC-QPS-013 契约-必填校验：逐个移除 17 个必填字段 → code='500' 且不落任务行。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    drop_field(payload, path)
    assert_failure_body(quote_client.price_sync(payload),
                        payload.get("requestId"), payload.get("orderCode"))
    assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


ENUM_OK = [
    ("100_0_200", 100, 0, 200),
    ("200_301_100", 200, 301, 100),
    ("default", None, 200, None),
    ("200_300_200", 200, 300, 200),
    ("200_0_100", 200, 0, 100),
]


@pytest.mark.db
@pytest.mark.parametrize("is_push,push_to,pobox", [c[1:] for c in ENUM_OK],
                         ids=[c[0] for c in ENUM_OK])
def test_valid_enum_combinations(quote_client, scp_db, price_sync_cfg, build_payload, md,
                                 is_push, push_to, pobox):
    # case_id: TC-QPS-044
    """TC-QPS-044 契约-枚举校验：合法枚举与缺省 → 均正常计费（2 行）。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"], md["carrier_base_id"]),
                            pushResultTo=push_to)
    if is_push is None:
        payload.pop("isPushWms", None)
    else:
        payload["isPushWms"] = is_push
    if pobox is None:
        payload.pop("closePoboxCheck", None)
    else:
        payload["closePoboxCheck"] = pobox

    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert len(body["data"]) == 2, f"双承运商应返回 2 行，实际 {body['data']}"

    pro_row = rows_for(body, md["carrier_pro_id"])[0]
    assert_zone_rate_amount(scp_db, price_sync_cfg, pro_row, md["carrier_pro_id"],
                            payload["shipTo"]["postcode"], 1.15)

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": payload["requestId"]})
    assert len(tasks) == 1 and tasks[0]["status"] == 200, f"应落 1 条成功任务，实际 {tasks}"
    # 需求 §3.2/§9.3.1：predict_price = isBest 全局最优运费（PRO+Aramex 时取较低者）
    best = min(float(r["shippingCost"]) for r in body["data"])
    assert abs(float(tasks[0]["predict_price"]) - best) <= 0.0005, (
        f"落库 predict_price 应等于全局最优运费 {best}，实际 {tasks[0]['predict_price']}"
    )


ENUM_BAD = [
    ("isPushWms=300", "isPushWms", 300),
    ("pushResultTo=100", "pushResultTo", 100),
    ("closePoboxCheck=300", "closePoboxCheck", 300),
]


@pytest.mark.xfail(strict=False, reason="D-04：pushResultTo=100 非法枚举未被拒绝")
@pytest.mark.db
@pytest.mark.parametrize("field,value", [c[1:] for c in ENUM_BAD], ids=[c[0] for c in ENUM_BAD])
def test_invalid_enums(quote_client, scp_db, price_sync_cfg, build_payload, md, field, value):
    # case_id: TC-QPS-019
    """TC-QPS-019 契约-枚举校验：非法枚举（isPushWms/pushResultTo/closePoboxCheck）被拒绝。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    payload[field] = value
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


@pytest.mark.db
@pytest.mark.parametrize("country,expect_ok", [
    ("AU", True), ("au", True), ("Australia", True), ("NZ", False),
], ids=["AU", "au", "Australia", "NZ"])
def test_country_and_state(quote_client, scp_db, price_sync_cfg, build_payload, md,
                           country, expect_ok):
    # case_id: TC-QPS-029
    """TC-QPS-029 契约-枚举校验：country 仅 AU（兼容大小写/全称），state 全称落库简称。"""
    ship_to = dict(price_sync_cfg["destinations"]["dest_a"])
    ship_to["country"] = country
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]), shipTo=ship_to)

    if not expect_ok:
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        return

    assert_success_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    if country != "AU":
        return

    full_state = dict(price_sync_cfg["destinations"]["dest_a"])
    full_state["state"] = "New South Wales"
    state_payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]),
                                  shipTo=full_state)
    assert_success_body(quote_client.price_sync(state_payload),
                        state_payload["requestId"], state_payload["orderCode"])
    addresses = scp_db.query_all(price_sync_cfg["sql"]["address_rows_by_request"],
                                 {"request_id": state_payload["requestId"]})
    ship_rows = [a for a in addresses if a["type"] == 200]
    assert len(ship_rows) == 1, f"应恰 1 行收件地址（type=200），实际 {addresses}"
    assert ship_rows[0]["state"] == "NSW", (
        f"state 全称应落库为简称 NSW，实际 {ship_rows[0]['state']}"
    )


@pytest.mark.db
def test_passthrough_fields(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-030
    """TC-QPS-030 契约-枚举校验：shippingType/shipmentType 不校验，金额与参考组一致。"""
    reference = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"]),
                              orderCode=f"{PASS_PREFIX}0")
    reference.pop("shippingType", None)
    reference.pop("shipmentType", None)

    experiment = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"]),
                               orderCode=f"{PASS_PREFIX}1",
                               shippingType=999, shipmentType="任意中文串")

    ref_body = assert_success_body(quote_client.price_sync(reference),
                                   reference["requestId"], reference["orderCode"])
    exp_body = assert_success_body(quote_client.price_sync(experiment),
                                   experiment["requestId"], experiment["orderCode"])
    assert len(ref_body["data"]) == 1 and len(exp_body["data"]) == 1
    ref_cost = assert_zone_rate_amount(scp_db, price_sync_cfg,
                                       ref_body["data"][0], md["carrier_pro_id"], "2000", 1.15)
    exp_cost = float(exp_body["data"][0]["shippingCost"])
    assert abs(ref_cost - exp_cost) <= 0.0005, (
        f"透传字段不应影响计费：参考组 {ref_cost}，实验组 {exp_cost}"
    )

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_order_prefix"],
                             {"order_code_prefix": PASS_PREFIX})
    assert len(tasks) == 2, f"两个实例应各落 1 条任务，实际 {tasks}"
    for task in tasks:
        assert task["status"] == 200, f"透传字段实例应成功，实际 {task}"
        assert abs(float(task["predict_price"]) - 19.96) <= 0.0005, (
            f"PRO 单承运商 predict_price 应为 19.96，实际 {task['predict_price']}"
        )


# 长度上界只对自由文本字段可执行：warehouseCode 为仓库主数据引用、
# country/state/postcode 受合法值/zone 约束，取 32/50 字符必然触发业务校验失败；
# suburb 参与 lsp_carrier_zone 匹配，255 字符值不在 zone 表中，计费结果必然为“无价卡”。
# 以上字段无法与“正常计费”同时成立（用例 JSON 已注明该例外），不纳入本参数化。
LENGTH_AT_BOUND = [
    pytest.param("requestId", ("requestId",), 64, "A", id="requestId"),
    pytest.param("ownerId", ("ownerId",), 32, "B", id="ownerId"),
    pytest.param("orderCode", ("orderCode",), 32, "C", id="orderCode",
                 marks=pytest.mark.xfail(
                     strict=False,
                     reason="新增缺陷：orderCode=32 字符叠加落库「-6 位序号」后超 varchar(32)（需求上限与落库实现冲突）")),
    pytest.param("shipmentCode", ("warehouse", 0, "shipmentCode"), 64, "E", id="shipmentCode"),
    pytest.param("address1", ("shipTo", "address1"), 255, "G", id="address1"),
    pytest.param("sku", ("warehouse", 0, "packages", 0, "items", 0, "sku"), 40, "H", id="sku"),
    pytest.param("packageCode", ("warehouse", 0, "packages", 0, "packageCode"), 32, "I", id="packageCode"),
    pytest.param("shipmentType", ("shipmentType",), 32, "J", id="shipmentType"),
]


@pytest.mark.db
@pytest.mark.parametrize("field,path,size,char", LENGTH_AT_BOUND)
def test_length_at_upper_bound(quote_client, scp_db, price_sync_cfg, build_payload, md,
                               field, path, size, char):
    # case_id: TC-QPS-035
    """TC-QPS-035 契约-长度校验：各字段恰好上界 → 正常计费，不因长度误拒。

    说明：warehouseCode/country/state/postcode 的长度上界与主数据/合法值冲突，
    按用例 expected_result 的例外口径不纳入本参数化，仅保留其余自由文本字段。
    """
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    leading = {"requestId": "SAC", "orderCode": "TESTSO", "suburb": "Haymarket",
               "address1": "456 George Street"}.get(field, "T")
    text = (leading + _suffix() + char * size)[:size]
    set_field(payload, path, [text] if path == ("carrierIds",) else text)
    assert_success_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                         {"request_id": payload["requestId"]})
    assert success == 1, f"上界实例应落 1 条成功任务，实际 {success}"


LENGTH_OVER = [
    ("requestId", ("requestId",), 65, "A"),
    ("ownerId", ("ownerId",), 33, "B"),
    ("orderCode", ("orderCode",), 33, "C"),
    ("warehouseCode", ("warehouse", 0, "warehouseCode"), 51, "D"),
    ("shipmentCode", ("warehouse", 0, "shipmentCode"), 65, "E"),
    ("suburb", ("shipTo", "suburb"), 256, "F"),
    ("address1", ("shipTo", "address1"), 256, "G"),
    ("sku", ("warehouse", 0, "packages", 0, "items", 0, "sku"), 41, "H"),
    ("packageCode", ("warehouse", 0, "packages", 0, "packageCode"), 33, "I"),
    ("shipmentType", ("shipmentType",), 33, "J"),
    ("carrierIds", ("carrierIds",), 33, "K"),
    ("country", ("shipTo", "country"), 33, "AU"),
    ("state", ("shipTo", "state"), 33, "NSW"),
    ("postcode", ("shipTo", "postcode"), 33, "2000"),
]


@pytest.mark.xfail(strict=False, reason="D-01/D-07/D-08：超长字段未统一按 code='500' 拒绝且不落任务")
@pytest.mark.db
@pytest.mark.parametrize("field,path,size,prefix", LENGTH_OVER, ids=[c[0] for c in LENGTH_OVER])
def test_length_over_upper_bound(quote_client, scp_db, price_sync_cfg, build_payload, md,
                                 field, path, size, prefix):
    # case_id: TC-QPS-036
    """TC-QPS-036 契约-长度校验：各字段超上界 1 字符 → code='500' 且不落任务。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"]))
    if field in ("country", "state", "postcode"):
        text = (prefix + "X" * size)[:size]  # 保留合法前缀，仅用于制造超长
    else:
        leading = {"requestId": "SAC", "orderCode": "TESTSO"}.get(field, "T")
        text = (leading + _suffix() + "X" * size)[:size]
    set_field(payload, path, [text] if path == ("carrierIds",) else text)
    assert_failure_body(quote_client.price_sync(payload),
                        payload.get("requestId"), payload.get("orderCode"))
    assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


TYPE_CASES = [
    # qty<1 / qty 非整数、weight 小数当前业务未做参数拦截（小数重量按向上取整计费），
    # 按用户口径先不纳入本用例；仅保留数组传对象的类型错误。
    ("packages={}", ("warehouse", 0, "packages"), {}),
]


@pytest.mark.xfail(strict=False,
                   reason="D-01：参数校验失败返回 HTTP 400 默认错误体（无 code='500' 包装层）")
@pytest.mark.db
@pytest.mark.parametrize("path,value", [c[1:] for c in TYPE_CASES], ids=[c[0] for c in TYPE_CASES])
def test_type_and_numeric_validation(quote_client, scp_db, price_sync_cfg, build_payload, md,
                                     path, value):
    # case_id: TC-QPS-037
    """TC-QPS-037 契约-类型与数值校验：packages 传对象 → 拒绝且不落任务。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    set_field(payload, path, value)
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


@pytest.mark.xfail(strict=False, reason="D-02/D-03：包裹部分为 0 与 packageCode 重复当前仍计费")
@pytest.mark.db
@pytest.mark.parametrize("scenario", ["partial_zero", "duplicate_package_code"],
                         ids=["partial-zero", "duplicate-packageCode"])
def test_package_structure_validation(quote_client, scp_db, price_sync_cfg, build_payload, md,
                                      scenario):
    # case_id: TC-QPS-021
    """TC-QPS-021 契约-结构校验：包裹尺寸部分为 0 / packageCode 重复 → 拒绝且不落任务。"""
    if scenario == "partial_zero":
        pkg = base_package(30, 10, 10, 3)
        pkg["width"] = 0
        packages = [pkg]
    else:
        pkg = base_package(30, 20, 15, 2)
        packages = [pkg, copy.deepcopy(pkg)]

    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]),
                            warehouse=one_warehouse(md["warehouse_code"], packages))
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


# ════════════════════════════════════════════════════════════
# 功能-箱规计算（8 条）
# ════════════════════════════════════════════════════════════

@pytest.mark.smoke
@pytest.mark.db
def test_main_flow_two_carriers(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-001
    """TC-QPS-001 功能-箱规：PRO+Aramex 1.15kg 单包裹 → 2 行、PRO 19.96、Aramex 最优并落库。"""
    payload = build_payload()  # 默认 VIR|PRO|Aramex
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert len(body["data"]) == 2, f"双承运商应恰 2 行，实际 {body['data']}"

    pro_rows = rows_for(body, md["carrier_pro_id"])
    base_rows = rows_for(body, md["carrier_base_id"])
    for carrier_id, rows in ((md["carrier_pro_id"], pro_rows),
                             (md["carrier_base_id"], base_rows)):
        assert len(rows) == 1, f"承运商 {carrier_id} 应恰 1 行，实际 {rows}"
        assert_vo_schema(rows[0])
        assert float(rows[0]["shippingCost"]) > 0

    pro_cost = assert_zone_rate_amount(scp_db, price_sync_cfg, pro_rows[0],
                                       md["carrier_pro_id"], payload["shipTo"]["postcode"], 1.15)
    assert abs(pro_cost - 19.96) <= 0.0005, f"PRO 1.15kg 应为 19.96，实际 {pro_cost}"
    assert abs(float(base_rows[0]["shippingCost"]) - 5.724) <= 0.0005, (
        f"Aramex 1.15kg 应为 5.724，实际 {base_rows[0]['shippingCost']}"
    )

    best_indexes = [i for i, r in enumerate(body["data"]) if r["isBest"] == 1]
    assert len(best_indexes) == 1, f"isBest=1 应恰一行，实际 {best_indexes}"
    best = body["data"][best_indexes[0]]
    assert best["bookingCarrierId"] == md["carrier_base_id"], (
        f"最低价 Aramex 应为全局最优，实际 {best}"
    )
    assert float(best["shippingCost"]) == min(float(r["shippingCost"]) for r in body["data"])

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": payload["requestId"]})
    assert len(tasks) == 1, f"应恰落 1 行任务，实际 {tasks}"
    task = tasks[0]
    assert task["status"] == 200
    assert str(task["order_code"]).startswith(payload["orderCode"])
    assert task["predict_carrier_code"] == best["bookingCarrierCode"], (
        f"落库最优承运商编码应为 {best['bookingCarrierCode']}，实际 {task['predict_carrier_code']}"
    )
    assert abs(float(task["predict_price"]) - 5.724) <= 0.0005, (
        f"落库 predict_price 应等于全局最优 5.724，实际 {task['predict_price']}"
    )

    addresses = scp_db.query_all(price_sync_cfg["sql"]["address_rows_by_request"],
                                 {"request_id": payload["requestId"]})
    assert len(addresses) == 2 and {a["type"] for a in addresses} == {100, 200}, (
        f"地址快照应恰 2 行（100/200），实际 {addresses}"
    )
    pkg_cnt = task_count(scp_db, price_sync_cfg, "package_count_by_request",
                         {"request_id": payload["requestId"]})
    sku_cnt = task_count(scp_db, price_sync_cfg, "package_sku_count_by_request",
                         {"request_id": payload["requestId"]})
    log_cnt = task_count(scp_db, price_sync_cfg, "job_log_count_by_request",
                         {"request_id": payload["requestId"]})
    assert pkg_cnt == 1 and sku_cnt == 1, f"包裹/SKU 行数应为 1/1，实际 {pkg_cnt}/{sku_cnt}"
    assert log_cnt >= 1, f"成功计费 job_log 至少 1 行，实际 {log_cnt}"


@pytest.mark.smoke
@pytest.mark.db
def test_multi_package_sum(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-005
    """TC-QPS-005 功能-箱规：PRO 2 包裹（5kg+10kg）分别计费求和 62.415，calcMode=1。"""
    carrier_id = md["carrier_pro_id"]
    packages = [base_package(30, 12, 10, 5, "SKU-P1"),
                base_package(60, 20, 15, 10, "SKU-P2")]
    payload = build_payload(carrierStrategyCode=vir(carrier_id),
                            warehouse=one_warehouse(md["warehouse_code"], packages))
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    rows = rows_for(body, carrier_id)
    assert len(rows) == 1, f"承运商应恰 1 行，实际 {rows}"
    row = rows[0]
    assert row["calcMode"] == 1, f"多包裹逐包计费应 calcMode=1，实际 {row['calcMode']}"

    postcode = payload["shipTo"]["postcode"]
    total = 0.0
    for pkg in packages:
        rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
            "carrier_id": carrier_id,
            "from_zone": price_sync_cfg["master_data"]["warehouse_zone"],
            "postcode": postcode,
            "weight": chargeable_kg(pkg["weight"]),
        })
        assert rate is not None, f"未取到 {pkg['weight']}kg 价卡段"
        total += expected_cost(rate, chargeable_kg(pkg["weight"]),
                               price_sync_cfg["rules"]["basic_limit_kg"])
    total = money(total)
    assert abs(total - 62.415) <= 0.0005, f"两包现算之和应为 62.415，实际 {total}"
    assert abs(float(row["shippingCost"]) - total) <= 0.0005, (
        f"响应金额应等于逐包现算之和 {total}，实际 {row['shippingCost']}"
    )

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": payload["requestId"]})
    assert len(tasks) == 1 and tasks[0]["status"] == 200, f"应落 1 条成功任务，实际 {tasks}"
    assert abs(float(tasks[0]["predict_price"]) - 62.415) <= 0.0005, (
        f"predict_price 应为 62.415，实际 {tasks[0]['predict_price']}"
    )
    pkg_cnt = task_count(scp_db, price_sync_cfg, "package_count_by_request",
                         {"request_id": payload["requestId"]})
    assert pkg_cnt == 2, f"请求 2 个包裹应落 2 行，实际 {pkg_cnt}"


@pytest.mark.db
def test_package_dims_zero_fallback(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-008
    """TC-QPS-008 功能-箱规：包裹层全 0 → 单 SKU 回退 19.96；双 SKU 组包 5kg → 30.018。"""
    carrier_id = md["carrier_pro_id"]
    postcode = "2000"

    fallback_pkg = {
        "packageCode": f"QTP{_suffix()}"[:32],
        "length": 0, "width": 0, "height": 0, "weight": 0,
        "items": [{"sku": "SKU-FALL", "qty": 1, "length": 30, "width": 20,
                   "height": 15, "weight": 1.15}],
    }
    fallback_payload = build_payload(
        carrierStrategyCode=vir(carrier_id),
        warehouse=one_warehouse(md["warehouse_code"], [fallback_pkg]),
    )
    fallback_body = assert_success_body(quote_client.price_sync(fallback_payload),
                                        fallback_payload["requestId"],
                                        fallback_payload["orderCode"])
    fallback_cost = assert_zone_rate_amount(
        scp_db, price_sync_cfg, rows_for(fallback_body, carrier_id)[0],
        carrier_id, postcode, 1.15)
    assert abs(fallback_cost - 19.96) <= 0.0005, f"回退 SKU 层应为 19.96，实际 {fallback_cost}"

    compose_pkg = {
        "packageCode": f"QTP{_suffix()}"[:32],
        "length": 0, "width": 0, "height": 0, "weight": 0,
        "items": [
            {"sku": "SKU-C1", "qty": 1, "length": 40, "width": 25, "height": 10, "weight": 3},
            {"sku": "SKU-C2", "qty": 1, "length": 20, "width": 15, "height": 20, "weight": 2},
        ],
    }
    compose_payload = build_payload(
        carrierStrategyCode=vir(carrier_id),
        warehouse=one_warehouse(md["warehouse_code"], [compose_pkg]),
    )
    compose_body = assert_success_body(quote_client.price_sync(compose_payload),
                                       compose_payload["requestId"],
                                       compose_payload["orderCode"])
    compose_cost = assert_zone_rate_amount(
        scp_db, price_sync_cfg, rows_for(compose_body, carrier_id)[0],
        carrier_id, postcode, 5)
    assert abs(compose_cost - 30.018) <= 0.0005, f"组包 5kg 应为 30.018，实际 {compose_cost}"

    pkg_cnt = task_count(scp_db, price_sync_cfg, "package_count_by_request",
                         {"request_id": compose_payload["requestId"]})
    sku_cnt = task_count(scp_db, price_sync_cfg, "package_sku_count_by_request",
                         {"request_id": compose_payload["requestId"]})
    assert (pkg_cnt, sku_cnt) == (1, 2), f"组包实例应为 1 包裹 2 SKU，实际 {pkg_cnt}/{sku_cnt}"


@pytest.mark.db
def test_group_package_qty_expanded(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-038
    """TC-QPS-038 功能-箱规：单 SKU qty=3 展开为 30×20×15/6kg → 30.493。"""
    carrier_id = md["carrier_pro_id"]
    pkg = {
        "packageCode": f"QTP{_suffix()}"[:32],
        "length": 0, "width": 0, "height": 0, "weight": 0,
        "items": [{"sku": "SKU-QTY3", "qty": 3,
                   "length": 30, "width": 20, "height": 5, "weight": 2}],
    }
    payload = build_payload(carrierStrategyCode=vir(carrier_id),
                            warehouse=one_warehouse(md["warehouse_code"], [pkg]))
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    cost = assert_zone_rate_amount(scp_db, price_sync_cfg,
                                   rows_for(body, carrier_id)[0],
                                   carrier_id, payload["shipTo"]["postcode"], 6)
    assert abs(cost - 30.493) <= 0.0005, f"qty 展开 6kg 应为 30.493，实际 {cost}"

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": payload["requestId"]})
    assert len(tasks) == 1 and tasks[0]["status"] == 200
    assert abs(float(tasks[0]["predict_price"]) - 30.493) <= 0.0005
    sku_rows = scp_db.query_all(price_sync_cfg["sql"]["sku_rows_by_request"],
                                {"request_id": payload["requestId"]})
    assert len(sku_rows) == 1, f"应落 1 行 SKU 明细，实际 {sku_rows}"
    assert int(sku_rows[0]["qty"]) == 3, f"SKU qty 应落库 3，实际 {sku_rows[0]['qty']}"


@pytest.mark.db
def test_volume_weight_not_billed(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-016
    """TC-QPS-016 功能-箱规：体积重 6.806kg > 称重 1.15kg → 仍按 2kg 段 19.96。"""
    carrier_id = md["carrier_pro_id"]
    pkg = base_package(60.5, 30, 15, 1.15, cube=0.027, cube_weight=6.806)
    payload = build_payload(carrierStrategyCode=vir(carrier_id),
                            warehouse=one_warehouse(md["warehouse_code"], [pkg]))
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    postcode = payload["shipTo"]["postcode"]
    actual = assert_zone_rate_amount(scp_db, price_sync_cfg,
                                     rows_for(body, carrier_id)[0],
                                     carrier_id, postcode, 1.15)
    assert abs(actual - 19.96) <= 0.0005, f"体积重不应参与计价，期望 19.96，实际 {actual}"

    volume_kg = chargeable_kg(6.806)
    volume_rate = scp_db.query_one(price_sync_cfg["sql"]["zone_rate"], {
        "carrier_id": carrier_id,
        "from_zone": price_sync_cfg["master_data"]["warehouse_zone"],
        "postcode": postcode,
        "weight": volume_kg,
    })
    assert volume_rate is not None
    volume_cost = expected_cost(volume_rate, volume_kg,
                                price_sync_cfg["rules"]["basic_limit_kg"])
    assert abs(actual - volume_cost) > 0.0005, (
        f"金额 {actual} 与体积重 {volume_kg}kg 段 {volume_cost} 一致，说明体积重参与计价"
    )


@pytest.mark.db
def test_box_rule_boundary(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-010
    """TC-QPS-010 功能-箱规：三边和恰 120 / 称重恰 22kg / 两包各 21.5kg → 均可发。"""
    carrier_id = md["carrier_pro_id"]
    postcode = "2000"
    cases = [
        ("sum-120", [base_package(119.9, 0.05, 0.05, 5)], 5, 30.018),
        ("weight-22", [base_package(30, 20, 15, 22)], 22, 38.107),
        ("two-21.5", [base_package(30, 20, 15, 21.5, "SKU-B1"),
                      base_package(30, 20, 15, 21.5, "SKU-B2")], None, 76.214),
    ]
    requests = []
    for idx, (name, packages, weight, expected) in enumerate(cases):
        payload = build_payload(
            carrierStrategyCode=vir(carrier_id),
            orderCode=f"{BOX_PREFIX}{idx}",
            warehouse=one_warehouse(md["warehouse_code"], packages),
        )
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        row = rows_for(body, carrier_id)[0]
        assert row["canShipping"] is True, f"{name} 边界值应可发，实际 {row}"
        actual = float(row["shippingCost"])
        assert abs(actual - expected) <= 0.0005, f"{name} 期望 {expected}，实际 {actual}"
        if weight is not None:
            sql_cost = assert_zone_rate_amount(scp_db, price_sync_cfg, row,
                                               carrier_id, postcode, weight)
            assert abs(sql_cost - expected) <= 0.0005
        requests.append(payload)

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_order_prefix"],
                             {"order_code_prefix": BOX_PREFIX})
    assert len(tasks) == 3 and all(t["status"] == 200 for t in tasks), (
        f"3 个实例均应落成功任务，实际 {tasks}"
    )
    pkg_cnt = task_count(scp_db, price_sync_cfg, "package_count_by_request",
                         {"request_id": requests[2]["requestId"]})
    assert pkg_cnt == 2, f"两包实例应落 2 行包裹，实际 {pkg_cnt}"


@pytest.mark.db
@pytest.mark.parametrize("scenario,dims,weight", [
    ("sum_125", (80, 25, 20), 5),
    ("sum_120_01", (80, 25.01, 15), 5),
    ("weight_22_01", (30, 20, 15), 22.01),
], ids=["sum-125", "sum-120.01", "weight-22.01"])
def test_oversized_carrier_filtered(quote_client, scp_db, price_sync_cfg, build_payload,
                                    md, rules, scenario, dims, weight):
    # case_id: TC-QPS-009
    """TC-QPS-009 功能-箱规：超箱规 PRO 被过滤，Aramex 仍正常返回。"""
    length, width, height = dims
    assert (length + width + height > rules["max_sum_cm"]
            or weight > rules["max_weight_kg"]), f"{scenario} 未超过箱规上限"
    pkg = base_package(length, width, height, weight)
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"], md["carrier_base_id"]),
        warehouse=one_warehouse(md["warehouse_code"], [pkg]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert rows_for(body, md["carrier_pro_id"]) == [], (
        "超箱规新增承运商不应出现在 data（REQ §7）"
    )
    base_rows = rows_for(body, md["carrier_base_id"])
    assert len(base_rows) == 1 and float(base_rows[0]["shippingCost"]) > 0


@pytest.mark.db
def test_only_new_carrier_oversized_fails(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-023
    """TC-QPS-023 功能-箱规：仅 PRO 参与且三边和 125cm → code='500' 且落 status=300。"""
    pkg = base_package(80, 25, 20, 5)
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        warehouse=one_warehouse(md["warehouse_code"], [pkg]),
    )
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
    assert failed >= 1, f"唯一承运商被过滤应落 status=300，实际 {failed}"
    success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                         {"request_id": payload["requestId"]})
    assert success == 0, f"不应产生成功任务，实际 {success}"


# ════════════════════════════════════════════════════════════
# 功能-价卡阶段与仓库地区（6 条）
# ════════════════════════════════════════════════════════════

def _assert_segment(quote_client, scp_db, price_sync_cfg, build_payload, md,
                    weights, expected):
    """两个重量实例命中同一价卡段，逐实例断言金额等于期望值且与 SQL 现算一致。"""
    carrier_id = md["carrier_pro_id"]
    for weight in weights:
        pkg = base_package(30, 20, 15, weight)
        payload = build_payload(carrierStrategyCode=vir(carrier_id),
                                warehouse=one_warehouse(md["warehouse_code"], [pkg]))
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        row = rows_for(body, carrier_id)[0]
        actual = assert_zone_rate_amount(scp_db, price_sync_cfg, row, carrier_id,
                                         payload["shipTo"]["postcode"], weight)
        assert abs(actual - expected) <= 0.0005, (
            f"{weight}kg 期望 {expected}，实际 {actual}"
        )


@pytest.mark.db
def test_segment_1(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-039
    """TC-QPS-039 功能-价卡阶段：0.5/1.0kg → 均取整 1kg，命中 0.001~1 段 16.423。"""
    _assert_segment(quote_client, scp_db, price_sync_cfg, build_payload, md,
                    (0.5, 1.0), 16.423)


@pytest.mark.db
def test_segment_2(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-040
    """TC-QPS-040 功能-价卡阶段：1.01/3.0kg → 命中 1.001~3 段 19.96。"""
    _assert_segment(quote_client, scp_db, price_sync_cfg, build_payload, md,
                    (1.01, 3.0), 19.96)


@pytest.mark.db
def test_segment_3(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-041
    """TC-QPS-041 功能-价卡阶段：3.01/5.0kg → 命中 3.001~5 段 30.018。"""
    _assert_segment(quote_client, scp_db, price_sync_cfg, build_payload, md,
                    (3.01, 5.0), 30.018)


@pytest.mark.db
def test_segment_4(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-006
    """TC-QPS-006 功能-价卡阶段：5.01/6/10/22kg → 5.001+ 续重段逐点现算。"""
    cases = [(5.01, 30.493), (6.0, 30.493), (10.0, 32.397), (22.0, 38.107)]
    for weight, expected in cases:
        pkg = base_package(30, 20, 15, weight)
        payload = build_payload(carrierStrategyCode=vir(md["carrier_pro_id"]),
                                warehouse=one_warehouse(md["warehouse_code"], [pkg]))
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        actual = assert_zone_rate_amount(scp_db, price_sync_cfg,
                                         rows_for(body, md["carrier_pro_id"])[0],
                                         md["carrier_pro_id"],
                                         payload["shipTo"]["postcode"], weight)
        assert abs(actual - expected) <= 0.0005, f"{weight}kg 期望 {expected}，实际 {actual}"


@pytest.mark.db
def test_warehouse_zone_switch(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-042
    """TC-QPS-042 功能-仓库与地区：同收件 2000/1.15kg，BG03(MEL)=19.96、BGS1(SYD)=16.655。"""
    carrier_id = md["carrier_pro_id"]
    expected = {"BG03": 19.96, "BGS1": 16.655}
    warehouse_addr = {
        "BG03": {"country": "AU", "state": "VIC", "suburb": "Maidstone",
                 "postcode": "3012", "address1": "C 35-77 Emu Road"},
        "BGS1": {"country": "AU", "state": "NSW", "suburb": "Arndell Park",
                 "postcode": "2148", "address1": "1/3 Lidco Street"},
    }
    for warehouse_code, cost in expected.items():
        zone = scp_db.query_one(price_sync_cfg["sql"]["warehouse_from_zone"],
                                {"code": warehouse_code})
        assert zone is not None, f"lsp_warehouse 未查到仓库 {warehouse_code}"
        pkg = base_package(30, 20, 15, 1.15)
        payload = build_payload(
            carrierStrategyCode=vir(carrier_id),
            warehouse=one_warehouse(warehouse_code, [pkg], warehouse_addr[warehouse_code]),
        )
        body = assert_success_body(quote_client.price_sync(payload),
                                   payload["requestId"], payload["orderCode"])
        actual = assert_zone_rate_amount(
            scp_db, price_sync_cfg, rows_for(body, carrier_id)[0], carrier_id,
            payload["shipTo"]["postcode"], 1.15, from_zone=zone["from_facility"])
        assert abs(actual - cost) <= 0.0005, (
            f"{warehouse_code}({zone['from_facility']}→SYD) 期望 {cost}，实际 {actual}"
        )


ZONE_CASES = [
    ("2000", "NSW", "Haymarket"),
    ("3000", "VIC", "Melbourne"),
    ("4000", "QLD", "Brisbane"),
    ("5000", "SA", "Adelaide"),
    ("6000", "WA", "Perth"),
]


@pytest.mark.db
@pytest.mark.parametrize("postcode,state,suburb", ZONE_CASES, ids=[c[0] for c in ZONE_CASES])
def test_zone_mapping_switch(quote_client, scp_db, price_sync_cfg, build_payload, md,
                             postcode, state, suburb):
    # case_id: TC-QPS-004
    """TC-QPS-004 功能-仓库与地区：同 2.3kg 派送不同 postcode → 命中各自 zone 价卡。"""
    if postcode == "4000":
        pytest.skip("PRO 无 MEL→BRS 价卡（lsp_carrier_rate 主数据缺失），属夹具缺失；补齐后重跑")
    pkg = base_package(30, 20, 15, 2.3)
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        orderCode=f"TESTSOZ{BATCH_ID}{postcode}",
        shipTo=dest(postcode, state, suburb),
        warehouse=one_warehouse(md["warehouse_code"], [pkg]),
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert_zone_rate_amount(scp_db, price_sync_cfg,
                            rows_for(body, md["carrier_pro_id"])[0],
                            md["carrier_pro_id"], postcode, 2.3)
    addresses = scp_db.query_all(price_sync_cfg["sql"]["address_rows_by_request"],
                                 {"request_id": payload["requestId"]})
    ship_rows = [a for a in addresses if a["type"] == 200]
    assert len(ship_rows) == 1, f"应恰 1 行收件地址，实际 {addresses}"
    assert str(ship_rows[0]["postcode"]) == postcode


# ════════════════════════════════════════════════════════════
# 功能-承运商范围与比价（7 条）
# ════════════════════════════════════════════════════════════

@pytest.mark.smoke
@pytest.mark.db
def test_three_carriers_isbest(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-043
    """TC-QPS-043 功能-比价：VIR 指定 PRO+Aramex+IPEC → 3 行、isBest 唯一且为 Aramex。"""
    carrier_ids = (md["carrier_pro_id"], md["carrier_base_id"], md["carrier_legacy_id"])
    payload = build_payload(carrierStrategyCode=vir(*carrier_ids))
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert len(body["data"]) == 3, f"3 家承运商应返回 3 行，实际 {body['data']}"
    for carrier_id in carrier_ids:
        assert len(rows_for(body, carrier_id)) == 1, f"{carrier_id} 应恰 1 行"

    expected = {
        md["carrier_pro_id"]: 19.96,
        md["carrier_base_id"]: 5.724,
        md["carrier_legacy_id"]: 19.074,
    }
    for carrier_id, cost in expected.items():
        actual = float(rows_for(body, carrier_id)[0]["shippingCost"])
        assert abs(actual - cost) <= 0.0005, f"{carrier_id} 期望 {cost}，实际 {actual}"
    assert_zone_rate_amount(scp_db, price_sync_cfg,
                            rows_for(body, md["carrier_pro_id"])[0],
                            md["carrier_pro_id"], payload["shipTo"]["postcode"], 1.15)

    best_rows = [r for r in body["data"] if r["isBest"] == 1]
    assert len(best_rows) == 1, f"isBest=1 应恰 1 行，实际 {best_rows}"
    assert best_rows[0]["bookingCarrierId"] == md["carrier_base_id"], (
        f"最低价 Aramex 应为全局最优，实际 {best_rows[0]}"
    )
    assert abs(float(best_rows[0]["shippingCost"]) - 5.724) <= 0.0005

    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": payload["requestId"]})
    assert len(tasks) == 1 and tasks[0]["status"] == 200, f"应落 1 条成功任务，实际 {tasks}"
    assert tasks[0]["predict_carrier_code"] == best_rows[0]["bookingCarrierCode"], (
        f"落库最优承运商编码应为 {best_rows[0]['bookingCarrierCode']}，"
        f"实际 {tasks[0]['predict_carrier_code']}"
    )


@pytest.mark.db
def test_strategy_code_scope(quote_client, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-028
    """TC-QPS-028 功能-比价：carrierStrategyCode=quote_price → 与 ubi/broers 8 家范围有交集。"""
    strategy = md.get("strategy_code") or ""
    if not strategy:
        pytest.skip("strategy_code 未配置——请在 config/lsp_quote/price_sync.yaml 回填策略编码")
    refs = set(md.get("strategy_refs") or [])
    if not refs:
        pytest.skip("strategy_refs 未回填——请按 ubi/broers 有效承运商回填")

    payload = build_payload(carrierStrategyCode=strategy)
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    actual_ids = {r["bookingCarrierId"] for r in body["data"]}
    assert actual_ids & refs, (
        f"策略 {strategy} 未返回范围内承运商（范围={sorted(refs)}，实际={actual_ids}）"
    )
    out_of_scope = actual_ids - refs
    if out_of_scope:
        warnings.warn(f"AC-10: 策略 {strategy} 额外返回范围外承运商 {sorted(out_of_scope)}",
                      stacklevel=2)


@pytest.mark.db
def test_no_rate_carrier_skipped(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-012
    """TC-QPS-012 功能-比价：无价卡承运商被跳过，其余正常（夹具缺失时 skip）。"""
    no_rate = md.get("carrier_no_rate_id") or ""
    if not no_rate:
        pytest.skip("范围内（ubi/broers status=100）8 家均有价卡，无真实无价卡夹具；"
                    "请回填 master_data.carrier_no_rate_id 后重跑")
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"], no_rate))
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    assert rows_for(body, no_rate) == [], f"无价卡承运商 {no_rate} 不应出现在 data"
    assert rows_for(body, md["carrier_base_id"]), "有价卡承运商应正常返回"


@pytest.mark.db
def test_no_rate_failure(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-025
    """TC-QPS-025 功能-比价：单承运商/全部承运商无价卡 → code='500' 且落 status=300（夹具缺失时 skip）。"""
    no_rate = md.get("carrier_no_rate_id") or ""
    no_rate_2 = md.get("carrier_no_rate_id_2") or ""
    if not no_rate:
        pytest.skip("范围内（ubi/broers status=100）8 家均有价卡，无真实无价卡夹具；"
                    "请回填 master_data.carrier_no_rate_id 后重跑")
    scenarios = [[no_rate]]
    if no_rate_2:
        scenarios.append([no_rate, no_rate_2])
    else:
        warnings.warn("carrier_no_rate_id_2 未回填，跳过‘全部无价卡’分支（AC-52）", stacklevel=2)

    for carriers in scenarios:
        payload = build_payload(carrierStrategyCode=vir(*carriers))
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
        assert failed >= 1, f"无价卡应落 status=300，实际 {failed}"
        success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                             {"request_id": payload["requestId"]})
        assert success == 0, f"无价卡不应产生成功任务，实际 {success}"


def test_tie_break_order(quote_client, build_payload):
    # case_id: TC-QPS-026
    """TC-QPS-026 功能-比价：金额并列时 isBest=1 取排序第一条（当前无并列，运行时 skip）。"""
    body = assert_success_body(quote_client.price_sync(build_payload()))
    costs = [float(r["shippingCost"]) for r in body["data"]]
    lowest = min(costs)
    if costs.count(lowest) < 2:
        pytest.skip(f"当前主数据下未出现金额并列（costs={costs}），无法验证并列排序规则")
    assert body["data"][0]["isBest"] == 1
    assert float(body["data"][0]["shippingCost"]) == lowest
    assert sum(1 for r in body["data"] if r["isBest"] == 1) == 1


@pytest.mark.xfail(strict=False, reason="D-07：同时传 carrierIds 时 carrierIds 仍优先生效")
def test_carrier_ids_ignored(quote_client, build_payload, md):
    # case_id: TC-QPS-031
    """TC-QPS-031 功能-比价：同时传 carrierIds 与 VIR|PRO → 只按策略返回 PRO。"""
    payload = build_payload(
        carrierStrategyCode=vir(md["carrier_pro_id"]),
        carrierIds=[md["carrier_base_id"]],
    )
    body = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    actual_ids = {r["bookingCarrierId"] for r in body["data"]}
    assert actual_ids == {md["carrier_pro_id"]}, (
        f"同时传 carrierIds 时应只按 carrierStrategyCode 选承运商，实际 {actual_ids}"
    )


@pytest.mark.xfail(strict=False, reason="D-05：VIR 段非法/策略不存在请求超时且任务停留 status=100")
@pytest.mark.db
@pytest.mark.parametrize("scenario", ["vir_malformed", "strategy_not_exist", "strategy_empty_refs"],
                         ids=["vir-malformed", "strategy-not-exist", "strategy-empty-refs"])
def test_strategy_validation(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-022
    """TC-QPS-022 功能-比价：VIR 非法/策略不存在/绑定空集合 → code='500'；eiz 落 status=300。"""
    if scenario == "vir_malformed":
        strategy = "VIR|"
    elif scenario == "strategy_not_exist":
        strategy = "NO_SUCH_STRATEGY"
    else:
        strategy = md.get("strategy_empty_code") or ""
        if not strategy:
            pytest.skip("strategy_empty_code 未回填——请从 lsp_carrier_strategy 实查空集合策略编码")

    payload = build_payload(carrierStrategyCode=strategy)
    assert_failure_body(quote_client.price_sync(payload),
                        payload["requestId"], payload["orderCode"])
    if scenario == "strategy_empty_refs":
        failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
        assert failed >= 1, f"无可用承运商应落 status=300，实际 {failed}"
        success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                             {"request_id": payload["requestId"]})
        assert success == 0, f"不应产生成功任务，实际 {success}"
        return
    assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


# ════════════════════════════════════════════════════════════
# 异常与落库（6 条）
# ════════════════════════════════════════════════════════════

@pytest.mark.db
def test_missing_request_id(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-032
    """TC-QPS-032 异常与落库：不传 requestId → 正常计费，按 orderCode 前缀查到成功任务。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    payload.pop("requestId", None)
    assert_success_body(quote_client.price_sync(payload),
                        None, payload["orderCode"])
    success = task_count(scp_db, price_sync_cfg, "task_success_count_by_order",
                         {"order_code": payload["orderCode"]})
    assert success >= 1, f"不传 requestId 应落成功任务（按 orderCode 前缀），实际 {success}"
    rows = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_order_prefix"],
                            {"order_code_prefix": payload["orderCode"]})
    assert rows and all(not row["request_id"] for row in rows), (
        f"不传 requestId 时落库 request_id 应为空，实际 {rows}"
    )


@pytest.mark.db
def test_no_idempotent_replay(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-020
    """TC-QPS-020 异常与落库：相同 requestId+orderCode 连续两次 → 两次成功，任务 1→2。"""
    payload = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    params = {"request_id": payload["requestId"], "order_code": payload["orderCode"]}
    first = assert_success_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    before = task_count(scp_db, price_sync_cfg, "task_count_by_request_order", params)
    assert before == 1, f"首次调用应落 1 行，实际 {before}"

    second = assert_success_body(quote_client.price_sync(payload),
                                 payload["requestId"], payload["orderCode"])
    after = task_count(scp_db, price_sync_cfg, "task_count_by_request_order", params)
    assert after == before + 1, f"不幂等：第二次应新增 1 行，前 {before} 后 {after}"
    assert sorted((r["bookingCarrierId"], float(r["shippingCost"])) for r in first["data"]) == \
        sorted((r["bookingCarrierId"], float(r["shippingCost"])) for r in second["data"])


@pytest.mark.xfail(strict=False, reason="D-08/D-09：未知仓库仍计费、不存在 carrierId 被静默忽略")
@pytest.mark.db
@pytest.mark.parametrize("scenario", ["unknown_warehouse", "unknown_carrier"],
                         ids=["unknown-warehouse", "unknown-carrier"])
def test_master_data_missing(quote_client, scp_db, price_sync_cfg, build_payload, md, scenario):
    # case_id: TC-QPS-014
    """TC-QPS-014 异常与落库：未知仓库→500 且落 status=300；VIR 中不存在 carrierId→500 且不落行。"""
    if scenario == "unknown_warehouse":
        payload = build_payload(
            carrierStrategyCode=vir(md["carrier_base_id"]),
            warehouse=one_warehouse("WH-NOT-EXIST-0000", [base_package(30, 20, 15, 2)]),
        )
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        failed = status_task_count(scp_db, price_sync_cfg, payload["requestId"], 300)
        assert failed >= 1, f"未知仓库应落 status=300，实际 {failed}"
        success = task_count(scp_db, price_sync_cfg, "task_success_count_by_request",
                             {"request_id": payload["requestId"]})
        assert success == 0
    else:
        payload = build_payload(
            carrierStrategyCode=vir(md["carrier_base_id"], "CAR-NOT-EXIST-000000"))
        assert_failure_body(quote_client.price_sync(payload),
                            payload["requestId"], payload["orderCode"])
        assert_no_task(scp_db, price_sync_cfg, payload["requestId"])


@pytest.mark.db
def test_failure_contract(quote_client, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-024
    """TC-QPS-024 异常与落库：eiz 确定性失败 → code='500'、msg 非空、data=null、success=false。"""
    payload = build_payload(carrierStrategyCode=md["strategy_empty_code"])
    body = assert_failure_body(quote_client.price_sync(payload),
                               payload["requestId"], payload["orderCode"])
    for key in ("code", "msg", "success", "data"):
        assert key in body, f"失败响应缺少字段 {key}，实际: {body}"


@pytest.mark.xfail(strict=False, reason="D-01：参数校验失败返回 code='400'（计算失败落库段按需求通过）")
@pytest.mark.db
def test_failure_persistence(quote_client, scp_db, price_sync_cfg, build_payload, md):
    # case_id: TC-QPS-027
    """TC-QPS-027 异常与落库：计算失败落 status=300/金额 0/承运商空；参数校验失败不落行。"""
    calc_payload = build_payload(carrierStrategyCode=md["strategy_empty_code"])
    assert_failure_body(quote_client.price_sync(calc_payload),
                        calc_payload["requestId"], calc_payload["orderCode"])
    tasks = scp_db.query_all(price_sync_cfg["sql"]["task_rows_by_request"],
                             {"request_id": calc_payload["requestId"]})
    assert len(tasks) == 1, f"计算失败应落 1 行任务，实际 {tasks}"
    task = tasks[0]
    assert task["status"] == 300, f"计算失败 status 应为 300，实际 {task}"
    assert float(task["predict_price"] or 0) == 0
    assert not task["predict_carrier_code"]
    log_cnt = task_count(scp_db, price_sync_cfg, "job_log_count_by_request",
                         {"request_id": calc_payload["requestId"]})
    if log_cnt == 0:
        warnings.warn("AC-50: 计算失败场景未查到 job_log 记录（软断言）", stacklevel=2)

    invalid = build_payload(carrierStrategyCode=vir(md["carrier_base_id"]))
    invalid.pop("ownerId", None)
    assert_failure_body(quote_client.price_sync(invalid),
                        invalid["requestId"], invalid["orderCode"])
    assert_no_task(scp_db, price_sync_cfg, invalid["requestId"])


def test_carrier_timeout(quote_client, build_payload):
    # case_id: TC-QPS-033
    """TC-QPS-033 异常与落库：承运商询价超时 → 500 且落 status=300（无注入手段，运行时 skip）。"""
    pytest.skip("AC-31 需要承运商询价超时故障注入（Mock/网络延迟），当前环境无注入手段；"
                "待提供注入方案后按 code='500' + status=300 补齐")
