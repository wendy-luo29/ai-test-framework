
# REQ-001 | TC-ADDR-001 | AC-01 | API v1.0.0
import pytest
import requests

# 1. 引入配置读取器和日志工具
from utils.config_reader import load_config
from utils.logger import get_logger

# 2. 初始化配置和日志
config = load_config("base_url.yaml")
logger = get_logger(__name__)

# 3. 提取基础URL
BASE_URL = config["base_url"]

# 检查 CI 环境，如果是 CI 则跳过（对应我们之前的逻辑）
ci_skipif = pytest.mark.skipif(
    pytest.importorskip("os").getenv("CI", "false") == "true",
    reason="CI环境下跳过真实接口调用"
)

@pytest.fixture(scope="session")
def address_api_session():
    # 创建一个全局的 Session，自动复用 HTTP 连接
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json"
    })
    logger.info(f"全局 HTTP Session 初始化完成，目标服务器: {BASE_URL}")
    yield session
    session.close()
    logger.info("全局 HTTP Session 已关闭")

"""API tests for POST /address/validate (module 06_地址校验).

Case IDs map to 06_地址校验/测试用例.md.
Every expectation is read from config/env.yaml -> address_validation, so the
code table can change without touching this file.

环境区分说明（方法2 / 区分环境）：
本文件是"契约测试"，所有断言都依赖真实接口返回的结构与业务值（有效地址
success=true、PO Box 识别、邮编/州不匹配处理等），无法用固定假数据代替。
在无法访问内网测试服务的环境（GitHub Actions 会注入环境变量 CI=true）中，
真实请求必然 ConnectTimeout，因此整模块自动跳过；本地开发环境（无 CI 变量）
照常执行真实用例。若将来要让 CI 也校验逻辑，应改为录制/回放真实响应或引入
契约测试（如 Pact），而不是逐函数 mock。
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

# 仅在本地（能访问内网地址服务）执行真实接口契约测试；CI 环境自动跳过。
_RUN_REAL_API = os.getenv('CI', '').strip().lower() not in ('true', '1', 'yes')

pytestmark = pytest.mark.skipif(
    not _RUN_REAL_API,
    reason='CI 环境无法访问内网地址服务，跳过真实接口契约测试（本地照常执行）',
)

ENVELOPE_FIELDS = {"code", "msg", "success", "data", "hasMore", "tc", "tp"}
DATA_FIELDS = {
    "address", "address2", "adviceAddress", "country", "countryCode",
    "fullAddress", "isPoBox", "orderId", "postcode", "reason", "state",
    "stateCode", "suburb", "suburbCode", "success",
}
DATA_STRING_FIELDS = DATA_FIELDS - {"isPoBox", "success"}

STATE_CODES = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"]


def _body(response):
    try:
        return response.json()
    except ValueError:
        return None


def _message(response, text):
    body = _body(response)
    rendered = json.dumps(body, ensure_ascii=False) if body is not None else response.text
    return f"{text}\nHTTP {response.status_code}\n响应体: {rendered}"


def assert_envelope(body, response):
    assert isinstance(body, dict), _message(response, "响应体不是 JSON 对象")
    missing = ENVELOPE_FIELDS - set(body)
    assert not missing, _message(response, f"包装层缺少字段: {sorted(missing)}")
    assert isinstance(body["code"], str), _message(response, "code 应为 string")
    assert isinstance(body["msg"], str), _message(response, "msg 应为 string")
    assert isinstance(body["success"], bool), _message(response, "success 应为 boolean")
    for field in ("hasMore", "tc", "tp"):
        value = body[field]
        assert isinstance(value, int) and not isinstance(value, bool), _message(
            response, f"{field} 应为整数"
        )


def assert_data_schema(data, response):
    assert isinstance(data, dict), _message(response, "data 不是 JSON 对象")
    missing = DATA_FIELDS - set(data)
    assert not missing, _message(response, f"data 缺少字段: {sorted(missing)}")
    assert isinstance(data["isPoBox"], bool), _message(response, "isPoBox 应为 boolean")
    assert isinstance(data["success"], bool), _message(response, "data.success 应为 boolean")
    for field in DATA_STRING_FIELDS:
        value = data[field]
        assert value is None or isinstance(value, str), _message(
            response, f"data.{field} 应为 string 或 null，实际 {type(value).__name__}"
        )


def assert_ok(response, expected):
    """Layer 1 + 2 + envelope-level layer 3 for a successful call."""
    assert response.status_code == expected["http_status"]["ok"], _message(
        response, f"HTTP 状态码应为 {expected['http_status']['ok']}"
    )
    body = _body(response)
    assert body is not None, _message(response, "响应体不是合法 JSON")
    assert_envelope(body, response)
    assert body["code"] == expected["code"]["success"], _message(
        response, f"包装 code 应为 {expected['code']['success']}"
    )
    assert body["msg"] == expected["msg"]["success"], _message(
        response, f"包装 msg 应为 {expected['msg']['success']}"
    )
    assert body["success"] is True, _message(response, "包装 success 应为 true")
    assert_data_schema(body["data"], response)
    return body["data"]


def assert_not_accepted(response, expected):
    """Request is rejected, either as HTTP 400 or inside the envelope."""
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(
        response, f"状态码应属于 {sorted(allowed)}"
    )
    if response.status_code == expected["http_status"]["client_error"]:
        return
    body = _body(response)
    assert body is not None, _message(response, "拒绝响应不是合法 JSON")
    assert_envelope(body, response)
    rejected = body["code"] == expected["code"]["param_error"]
    data = body["data"]
    if isinstance(data, dict):
        assert_data_schema(data, response)
        rejected = rejected or data["success"] is False
    assert rejected, _message(response, "既不是参数错误码，也不是 data.success=false")


def assert_mismatch_handled(data):
    """Address data conflicts must surface as a reason, or as an advice address."""
    if data["success"]:
        assert data["adviceAddress"], "success=true 时必须返回 adviceAddress 建议地址"
    else:
        assert data["reason"], "success=false 时必须返回 reason 拦截原因"


def merged(base: dict, **overrides) -> dict:
    payload = dict(base)
    payload.update(overrides)
    return payload


def without(base: dict, *keys) -> dict:
    payload = dict(base)
    for key in keys:
        payload.pop(key, None)
    return payload


@pytest.fixture
def base_payload(load_json):
    return dict(load_json("address_validate.json")["base"])


@pytest.fixture
def states_by_code(load_json):
    return {row["state"]: row for row in load_json("address_validate.json")["states"]}


# ---------------------------------------------------------------------------
# Core flow
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.smoke
def test_validate_valid_address(address_client, base_payload, address_config):
    # case_id: ADDR-C-001
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(base_payload), expected)
    assert data["success"] is True, "有效地址应验证通过"
    assert data["country"] == "Australia"
    assert data["countryCode"] == "AU"
    assert data["stateCode"] == base_payload["state"]
    assert data["postcode"] == base_payload["postcode"]
    assert data["suburbCode"], "区域编码不应为空"
    assert base_payload["address"] in data["fullAddress"]
    assert data["isPoBox"] is False
    assert data["orderId"] == base_payload["order_id"]
    assert data["reason"] in ("", None), "验证通过时不应返回拦截原因"


@pytest.mark.api
@pytest.mark.smoke
def test_validate_default_country(address_client, base_payload, address_config):
    # case_id: ADDR-P-007
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(without(base_payload, "country")), expected)
    assert data["success"] is True
    assert data["country"] == address_config["default_country"]
    assert data["countryCode"] == "AU"


@pytest.mark.api
def test_validate_empty_country_uses_default(address_client, base_payload, address_config):
    # case_id: ADDR-P-008
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(merged(base_payload, country="")), expected)
    assert data["country"] == address_config["default_country"]
    assert data["countryCode"] == "AU"


@pytest.mark.api
@pytest.mark.smoke
def test_validate_is_return_true(address_client, base_payload, address_config):
    # case_id: ADDR-C-002
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(merged(base_payload, is_return=True)), expected)
    assert data["success"] is True
    assert data["adviceAddress"], "is_return=true 时应返回建议地址"


@pytest.mark.api
def test_validate_is_return_missing(address_client, base_payload, address_config):
    # case_id: ADDR-P-009
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(without(base_payload, "is_return")), expected)
    assert data["adviceAddress"] in ("", None), "is_return 缺省时不应返回建议地址"


@pytest.mark.api
@pytest.mark.smoke
def test_pobox_is_detected(address_client, base_payload, address_config):
    # case_id: ADDR-C-003
    expected = address_config["expected"]
    data = assert_ok(
        address_client.validate(merged(base_payload, address="PO Box 123")), expected
    )
    assert data["isPoBox"] is True, "PO Box 地址应识别为信箱"
    if not data["success"]:
        assert data["reason"], "判定拦截时必须给出原因"


@pytest.mark.api
@pytest.mark.smoke
def test_unknown_street_is_rejected(address_client, base_payload, address_config):
    # case_id: ADDR-C-004
    expected = address_config["expected"]
    data = assert_ok(
        address_client.validate(merged(base_payload, address="9999 Unknown Road")), expected
    )
    assert data["success"] is False
    assert data["reason"], "验证不通过时必须返回拦截原因"
    assert data["isPoBox"] is False


@pytest.mark.api
def test_postcode_state_mismatch(address_client, base_payload, address_config):
    # case_id: ADDR-C-005
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(merged(base_payload, postcode="2000")), expected)
    assert_mismatch_handled(data)


@pytest.mark.api
def test_suburb_postcode_mismatch(address_client, base_payload, address_config):
    # case_id: ADDR-C-006
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(merged(base_payload, suburb="Sydney")), expected)
    assert_mismatch_handled(data)


@pytest.mark.api
def test_misspelled_street_returns_advice(address_client, base_payload, address_config):
    # case_id: ADDR-C-012
    expected = address_config["expected"]
    payload = merged(base_payload, address="Level 1, 123 Collns Street", is_return=True)
    data = assert_ok(address_client.validate(payload), expected)
    if data["success"]:
        assert data["adviceAddress"], "验证通过时应给出标准化建议地址"
    else:
        assert data["reason"], "验证不通过时必须给出拦截原因"
        if data["adviceAddress"] is not None:
            assert data["adviceAddress"] != payload["address"], "建议地址应与原地址不同"


@pytest.mark.api
def test_full_address_contains_address2(address_client, base_payload, address_config):
    # case_id: ADDR-C-011
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(base_payload), expected)
    assert base_payload["address2"] in data["fullAddress"]
    assert data["address"] == base_payload["address"]
    assert data["address2"] == base_payload["address2"]


@pytest.mark.api
def test_rejected_address_still_returns_standard_fields(
    address_client, base_payload, address_config
):
    # case_id: ADDR-C-014
    expected = address_config["expected"]
    data = assert_ok(
        address_client.validate(merged(base_payload, address="9999 Unknown Road")), expected
    )
    assert data["success"] is False
    assert data["fullAddress"] or data["address"], "不通过时仍应回填地址信息"


# ---------------------------------------------------------------------------
# order_id propagation / state code table
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.parametrize("order_id", ["ORD-ADDR-0001", "Ord-2026-ABC_x-01"])
def test_order_id_roundtrip(address_client, base_payload, address_config, order_id):
    # case_id: ADDR-C-007
    expected = address_config["expected"]
    data = assert_ok(
        address_client.validate(merged(base_payload, order_id=order_id)), expected
    )
    assert data["orderId"] == order_id, "orderId 必须与请求 order_id 逐字符一致"


@pytest.mark.api
def test_order_id_with_unicode_roundtrip(address_client, base_payload, address_config):
    # case_id: ADDR-C-008
    expected = address_config["expected"]
    order_id = "订单-#001/测试"
    data = assert_ok(
        address_client.validate(merged(base_payload, order_id=order_id)), expected
    )
    assert data["orderId"] == order_id, "中文与特殊字符应原样回传，不得乱码"


@pytest.mark.api
@pytest.mark.smoke
@pytest.mark.parametrize("state_code", STATE_CODES)
def test_state_code_mapping(
    address_client, base_payload, states_by_code, address_config, state_code
):
    # case_id: ADDR-C-010
    expected = address_config["expected"]
    row = states_by_code[state_code]
    payload = merged(
        base_payload,
        state=row["state"],
        postcode=row["postcode"],
        suburb=row["suburb"],
        order_id=f"ORD-STATE-{state_code}",
    )
    data = assert_ok(address_client.validate(payload), expected)
    assert data["success"] is True, f"{state_code} 的代表性地址应验证通过"
    assert data["stateCode"] == state_code
    assert data["postcode"] == row["postcode"]
    assert data["orderId"] == payload["order_id"]


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.parametrize("field", ["address", "postcode", "state", "suburb"])
def test_missing_required_field(address_client, base_payload, address_config, field):
    # case_id: ADDR-P-002
    expected = address_config["expected"]
    response = address_client.validate(without(base_payload, field))
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_address2_is_optional(address_client, base_payload, address_config):
    # case_id: ADDR-P-006
    expected = address_config["expected"]
    response = address_client.validate(without(base_payload, "address2"))
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(response, "address2 缺失时状态码异常")
    if response.status_code == expected["http_status"]["client_error"]:
        return
    body = _body(response)
    assert_envelope(body, response)
    if body["code"] == expected["code"]["success"]:
        assert_data_schema(body["data"], response)
        assert body["data"]["success"] is True, "address2 可选时应正常验证通过"


@pytest.mark.api
def test_empty_body_is_rejected(address_client, address_config):
    # case_id: ADDR-P-001
    expected = address_config["expected"]
    response = address_client.validate({})
    assert_not_accepted(response, expected)


@pytest.mark.api
@pytest.mark.parametrize(
    "overrides",
    [
        {"is_return": "true"},
        {"address": 123},
        {"postcode": 3000},
    ],
)
def test_field_type_mismatch(address_client, base_payload, address_config, overrides):
    # case_id: ADDR-P-010
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, **overrides))
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_invalid_state_code(address_client, base_payload, address_config):
    # case_id: ADDR-P-013
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, state="XX"))
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_state_full_name(address_client, base_payload, address_config):
    # case_id: ADDR-P-014
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, state="Victoria"))
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(response, "全称州名处理异常")
    if response.status_code == expected["http_status"]["client_error"]:
        return
    body = _body(response)
    assert_envelope(body, response)
    data = body["data"]
    assert_data_schema(data, response)
    if data["success"]:
        assert data["stateCode"] == "VIC", "支持全称时应归一为 VIC"


@pytest.mark.api
@pytest.mark.parametrize("country", ["australia", "New Zealand"])
def test_country_variants(address_client, base_payload, address_config, country):
    # case_id: ADDR-P-015
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, country=country))
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(response, "国家取值处理异常")
    if response.status_code == expected["http_status"]["client_error"]:
        return
    body = _body(response)
    assert_envelope(body, response)
    data = body["data"]
    assert_data_schema(data, response)
    if data["success"]:
        assert data["countryCode"], "验证通过时 countryCode 不应为空"


@pytest.mark.api
@pytest.mark.parametrize("postcode", ["300", "30A0", "30000"])
def test_invalid_postcode_format(address_client, base_payload, address_config, postcode):
    # case_id: ADDR-P-017
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, postcode=postcode))
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_unknown_field_is_ignored(address_client, base_payload, address_config):
    # case_id: ADDR-P-020
    expected = address_config["expected"]
    data = assert_ok(
        address_client.validate(merged(base_payload, extraField="x")), expected
    )
    assert data["success"] is True


@pytest.mark.api
def test_null_address(address_client, base_payload, address_config):
    # case_id: ADDR-P-021
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, address=None))
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_special_characters_in_address(address_client, base_payload, address_config):
    # case_id: ADDR-P-022
    expected = address_config["expected"]
    address = "Level 1, 123 Collins St!@#$%^&*() 墨尔本"
    response = address_client.validate(merged(base_payload, address=address))
    assert response.status_code == expected["http_status"]["ok"], _message(
        response, "特殊字符不应导致 5xx"
    )
    body = _body(response)
    assert_envelope(body, response)
    data = body["data"]
    assert_data_schema(data, response)
    assert data["success"] is False, "不存在的地址不应判定为通过"
    assert data["reason"]
    if data["address"] is not None:
        assert data["address"] == address, "回显地址不得乱码或截断"


@pytest.mark.api
def test_whitespace_only_fields(address_client, base_payload, address_config):
    # case_id: ADDR-P-023
    expected = address_config["expected"]
    response = address_client.validate(
        merged(base_payload, address="   ", suburb="   ")
    )
    assert_not_accepted(response, expected)


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_min_length_address(address_client, base_payload, address_config):
    # case_id: ADDR-B-001
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, address="A"))
    assert_not_accepted(response, expected)


@pytest.mark.api
@pytest.mark.parametrize("length", [255, 256])
def test_address_length_boundary(address_client, base_payload, address_config, length):
    # case_id: ADDR-B-002
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, address="A" * length))
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(
        response, f"地址长度 {length} 时出现异常状态码"
    )
    if response.status_code == expected["http_status"]["client_error"]:
        return
    body = _body(response)
    assert_envelope(body, response)
    data = body["data"]
    assert_data_schema(data, response)
    if data["address"] is not None:
        assert len(data["address"]) == length, "响应地址不得截断"


@pytest.mark.api
@pytest.mark.parametrize("postcode", ["0000", "9999"])
def test_postcode_boundary(address_client, base_payload, address_config, postcode):
    # case_id: ADDR-B-004
    expected = address_config["expected"]
    data = assert_ok(
        address_client.validate(merged(base_payload, postcode=postcode)), expected
    )
    assert data["success"] is False, "格式合法但地址不存在的邮编不应验证通过"
    assert data["reason"]


@pytest.mark.api
def test_empty_order_id(address_client, base_payload, address_config):
    # case_id: ADDR-B-006
    expected = address_config["expected"]
    data = assert_ok(address_client.validate(merged(base_payload, order_id="")), expected)
    assert data["orderId"] in ("", None)
    assert data["success"] is True


@pytest.mark.api
def test_long_order_id(address_client, base_payload, address_config):
    # case_id: ADDR-B-007
    expected = address_config["expected"]
    order_id = "O" * 255
    data = assert_ok(
        address_client.validate(merged(base_payload, order_id=order_id)), expected
    )
    assert data["orderId"] == order_id, "order_id 不得截断"


@pytest.mark.api
@pytest.mark.parametrize("suburb", ["melbourne", "MELBOURNE"])
def test_suburb_case_insensitive(address_client, base_payload, address_config, suburb):
    # case_id: ADDR-B-008
    expected = address_config["expected"]
    response = address_client.validate(merged(base_payload, suburb=suburb))
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(response, "区域大小写处理异常")
    if response.status_code == expected["http_status"]["client_error"]:
        return
    body = _body(response)
    assert_envelope(body, response)
    data = body["data"]
    assert_data_schema(data, response)
    if not data["success"]:
        assert data["reason"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_invalid_json_body(address_client, address_config):
    # case_id: ADDR-E-001
    expected = address_config["expected"]
    response = address_client.post(
        address_client.path,
        data="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_json_array_body(address_client, address_config):
    # case_id: ADDR-E-002
    expected = address_config["expected"]
    response = address_client.validate([])
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_empty_request_body(address_client, address_config):
    # case_id: ADDR-E-008
    expected = address_config["expected"]
    response = address_client.post(address_client.path, data="")
    assert_not_accepted(response, expected)


@pytest.mark.api
def test_unknown_path_returns_404(address_client, base_payload, address_config):
    # case_id: ADDR-E-004
    expected = address_config["expected"]
    response = address_client.post(address_client.path + "/invalid", json=base_payload)
    assert response.status_code == expected["http_status"]["not_found"], _message(
        response, "不存在的路径应返回 404"
    )
    body = _body(response)
    assert isinstance(body, dict), _message(response, "404 响应体应为 JSON 对象")
    assert "data" not in body, "404 不应返回业务 data"


@pytest.mark.api
def test_get_method_not_supported(address_client, address_config):
    # case_id: ADDR-E-005
    response = address_client.get(address_client.path)
    assert response.status_code in (404, 405), _message(
        response, "GET 不应返回 200"
    )
    body = _body(response)
    assert not (isinstance(body, dict) and body.get("data")), "GET 不应返回业务数据"


@pytest.mark.api
def test_content_type_text_plain(address_client, base_payload, address_config):
    # case_id: ADDR-E-003
    expected = address_config["expected"]
    response = address_client.post(
        address_client.path,
        data=json.dumps(base_payload),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code in (200, 400, 415), _message(
        response, "非 JSON Content-Type 处理异常"
    )
    if response.status_code == 200:
        body = _body(response)
        assert_envelope(body, response)
        assert body["code"] in (
            expected["code"]["success"],
            expected["code"]["param_error"],
        )


@pytest.mark.api
@pytest.mark.skip(reason="需要故障注入使下游地址服务不可用，当前环境未提供")
def test_downstream_service_unavailable(address_client, base_payload, address_config):
    # case_id: ADDR-E-006
    expected = address_config["expected"]
    body = _body(address_client.validate(base_payload))
    assert body["code"] == expected["code"]["system_error"]


@pytest.mark.api
@pytest.mark.skip(reason="需要故障注入使下游延迟超过 api_timeout，当前环境未提供")
def test_request_timeout(address_client, base_payload):
    # case_id: ADDR-E-007
    address_client.validate(base_payload)


@pytest.mark.api
@pytest.mark.regression
def test_oversized_body(address_client, base_payload, address_config):
    # case_id: ADDR-E-009
    expected = address_config["expected"]
    response = address_client.validate(
        merged(base_payload, address="A" * (1024 * 1024))
    )
    assert response.status_code in (200, 400, 413), _message(
        response, "超大请求体处理异常"
    )
    if response.status_code == 200:
        body = _body(response)
        assert_envelope(body, response)
        if isinstance(body["data"], dict):
            assert body["data"]["success"] is False


# ---------------------------------------------------------------------------
# Idempotency / concurrency
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_repeated_calls_are_consistent(address_client, base_payload, address_config):
    # case_id: ADDR-E-010
    expected = address_config["expected"]
    payload = merged(base_payload, order_id="ORD-IDEM-001")
    outcomes = []
    for _ in range(5):
        data = assert_ok(address_client.validate(payload), expected)
        assert data["orderId"] == "ORD-IDEM-001"
        outcomes.append((data["success"], data["reason"], data["isPoBox"]))
    assert len(set(outcomes)) == 1, f"重复调用结果不一致: {outcomes}"


@pytest.mark.api
def test_concurrent_calls_keep_order_ids(address_client, base_payload, address_config):
    # case_id: ADDR-E-011
    expected = address_config["expected"]
    order_ids = [f"ORD-CONC-{index:03d}" for index in range(10)]

    def send(order_id):
        payload = merged(base_payload, order_id=order_id)
        return order_id, address_client.validate(payload)

    with ThreadPoolExecutor(max_workers=len(order_ids)) as pool:
        results = list(pool.map(send, order_ids))

    for order_id, response in results:
        data = assert_ok(response, expected)
        assert data["orderId"] == order_id, "并发响应出现 orderId 串号"
        assert data["success"] is True