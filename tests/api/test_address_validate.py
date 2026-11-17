# REQ-001 | 地址验证接口自动化用例 | v2.1
"""POST /address/validate 接口自动化。

用例来源：.claude/skills/design-testcases/output/REQ-001-TC-design-v2.md
每条用例函数体首行 # case_id 与用例清单逐字符一致。
环境地址、超时、默认国家、not found 文案均来自 config/env.yaml。
"""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from config.config_loader import get_value
from utils.api_assertions import (
    assert_business_failure,
    assert_data_schema,
    assert_envelope,
    assert_not_found,
    assert_ok,
    assert_rejected,
    assert_validation_error,
    parse_json,
    merged,
    without,
)

def assert_address_exists(db, data):
    """success=true 时校验主键命中地址总表，suburb 大小写不敏感。"""
    row = db.fetch_one(
        "SELECT 1 AS hit FROM lsp_address_suburb_postcode "
        "WHERE state_code = %s AND postcode = %s "
        "AND UPPER(suburb_name) = UPPER(%s) LIMIT 1",
        (data["stateCode"], data["postcode"], data["suburb"]),
    )
    assert row is not None, "地址总表未命中：state_code=%r postcode=%r suburb=%r" % (
        data["stateCode"],
        data["postcode"],
        data["suburb"],
    )


_REASONS = []
_RUN_IN_CI = os.getenv("ADDRESS_API_ALLOW_CI", "").strip().lower() in ("true", "1", "yes")
if os.getenv("CI", "").strip().lower() in ("true", "1", "yes") and not _RUN_IN_CI:
    _REASONS.append("CI 环境无法访问内网地址服务（设置 ADDRESS_API_ALLOW_CI=1 可强制执行）")
if not get_value("api_base_url", ""):
    _REASONS.append("api_base_url 为空，本地 demo server 未实现 /address/validate")

pytestmark = pytest.mark.skipif(
    bool(_REASONS), reason="；".join(_REASONS)
)


# ---------------------------------------------------------------------------
# AC-01 existence hit
# ---------------------------------------------------------------------------



@pytest.mark.api
def test_arbitrary_street_text_still_valid(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-004
    payload = merged(base_payload, address=addr_data["arbitrary_address"])
    data = assert_ok(address_client.validate(payload), expected)
    assert data["success"] is True
    assert data["isPoBox"] is False
    assert data["stateCode"] == base_payload["state"]
    assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-02 address not found
# ---------------------------------------------------------------------------












@pytest.mark.api
@pytest.mark.skip(reason="待确认：DB 对 state/suburb 的大小写与前后空格是否敏感")
def test_key_case_and_whitespace(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-008
    for overrides in addr_data["key_case_whitespace"]:
        payload = merged(base_payload, **overrides)
        assert_not_found(address_client.validate(payload), address_config)


@pytest.mark.api
def test_null_or_empty_key_fields(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-009
    empty_reason = {"state": "state not found"}
    for overrides in addr_data["key_null_empty"]:
        payload = merged(base_payload, **overrides)
        field, value = next(iter(overrides.items()))
        response = address_client.validate(payload)
        if value is None:
            assert_validation_error(response, expected)
            continue
        body = parse_json(response)
        assert_envelope(body, response)
        data = body["data"]
        assert data["success"] is False, "%s 为空时应返回业务失败" % field
        reason = (data.get("reason") or "").lower()
        assert reason, "%s 为空时必须返回明确 reason" % field
        if field in empty_reason:
            want = empty_reason[field]
            assert want in reason, "%s 为空时 reason 应为 %r，实际 %r" % (
                field,
                want,
                data.get("reason"),
            )


@pytest.mark.api
def test_postcode_leading_zero(
    address_client, base_payload, addr_data, expected, address_config, db
):
    # case_id: TC-ADDR-010
    row = addr_data["postcode_leading_zero"]
    data = assert_ok(address_client.validate(merged(base_payload, **row["ok"])), expected)
    assert data["postcode"] == row["ok"]["postcode"]
    assert_address_exists(db, data)
    assert_not_found(
        address_client.validate(merged(base_payload, **row["bad"])), address_config
    )


# ---------------------------------------------------------------------------
# AC-03 country scope
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_non_australia_country_rejected(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-003
    body = assert_rejected(
        address_client.validate(
            merged(base_payload, country=addr_data["unsupported_country"])
        ),
        expected,
    )
    if body is None:
        return
    if "data" in body:  # 参数校验错误：data=null，原因在 msg
        assert body["msg"]
        return
    assert body["success"] is False
    assert body["reason"]
    assert body["countryCode"] != "AU"


@pytest.mark.api
def test_country_variants(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-011
    for country in ("AU", "Australia"):
        data = assert_ok(
            address_client.validate(merged(base_payload, country=country)), expected
        )
        assert data["countryCode"] == "AU"
        assert_address_exists(db, data)
    for country in ("au", "australia"):
        response = address_client.validate(merged(base_payload, country=country))
        assert response.status_code in (
            expected["http_status"]["ok"],
            expected["http_status"]["client_error"],
        )
        if response.status_code == expected["http_status"]["client_error"]:
            continue
        body = parse_json(response)
        assert_envelope(body, response)
        data = body["data"]
        if data is None:
            assert body["success"] is False
            assert body["msg"]
            continue
        assert_data_schema(data, response)
        if data["success"]:
            assert data["countryCode"] == "AU"
            assert_address_exists(db, data)
        else:
            assert data["reason"] or body["msg"]


@pytest.mark.api
@pytest.mark.skip(reason="待确认：country 为空字符串或 null 是否等同默认 Australia")
def test_country_empty_or_null(address_client, base_payload, expected, address_config):
    # case_id: TC-ADDR-012
    for country in ("", None):
        data = assert_ok(
            address_client.validate(merged(base_payload, country=country)), expected
        )
        assert data["countryCode"] == "AU"


# ---------------------------------------------------------------------------
# AC-04 order_id
# ---------------------------------------------------------------------------



@pytest.mark.api
def test_order_id_missing(address_client, base_payload, expected, db):
    # case_id: TC-ADDR-014
    data = assert_ok(address_client.validate(without(base_payload, "order_id")), expected)
    assert data["orderId"] in (None, "")
    assert_address_exists(db, data)


@pytest.mark.api
def test_order_id_edge_values(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-015
    for order_id in addr_data["order_id_edge"]:
        response = address_client.validate(merged(base_payload, order_id=order_id))
        assert response.status_code in (
            expected["http_status"]["ok"],
            expected["http_status"]["client_error"],
        )
        if response.status_code == expected["http_status"]["client_error"]:
            continue
        body = parse_json(response)
        assert_envelope(body, response)
        data = body["data"]
        if data is None:
            assert body["success"] is False
            assert body["msg"]
            continue
        assert_data_schema(data, response)
        if data["success"]:
            assert data["orderId"] == order_id
            assert_address_exists(db, data)
        else:
            assert data["reason"] or body["msg"]


# ---------------------------------------------------------------------------
# AC-05 is_return (pending rules)
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.skip(reason="待确认：is_return=true 时 adviceAddress 的生成规则")
def test_is_return_true(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-016
    data = assert_ok(
        address_client.validate(merged(base_payload, **addr_data["is_return"]["true"])),
        expected,
    )
    assert data["adviceAddress"]


@pytest.mark.api
@pytest.mark.skip(reason="待确认：is_return=false 时是否仍返回 adviceAddress")
def test_is_return_false(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-017
    data = assert_ok(
        address_client.validate(merged(base_payload, **addr_data["is_return"]["false"])),
        expected,
    )
    assert data["adviceAddress"] in ("", None)


@pytest.mark.api
@pytest.mark.skip(reason="待确认：is_return 非布尔值的反序列化策略")
def test_is_return_non_boolean(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-018
    response = address_client.validate(
        merged(base_payload, **addr_data["is_return"]["non_boolean"])
    )
    assert_rejected(response, expected)


# ---------------------------------------------------------------------------
# AC-06 PO Box detection
# ---------------------------------------------------------------------------









@pytest.mark.api
def test_pobox_positive_variants(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-022
    for pattern in addr_data["pobox_positive"]:
        payload = merged(base_payload, address=pattern, address2="")
        data = assert_ok(address_client.validate(payload), expected)
        assert data["isPoBox"] is True, "未识别 PO Box 写法: %r" % pattern
        assert_address_exists(db, data)


@pytest.mark.api
def test_pobox_negative_variants(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-023
    for pattern in addr_data["pobox_negative"]:
        payload = merged(base_payload, address=pattern, address2="")
        data = assert_ok(address_client.validate(payload), expected)
        assert data["isPoBox"] is False, "误判为 PO Box: %r" % pattern
        assert_address_exists(db, data)


@pytest.mark.api
@pytest.mark.xfail(reason="待确认：PO Box 正则是否大小写不敏感", strict=False)
def test_pobox_case_variants(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-024
    for pattern in addr_data["pobox_case"]:
        payload = merged(base_payload, address=pattern, address2="")
        data = assert_ok(address_client.validate(payload), expected)
        assert data["isPoBox"] is True, "大小写变体未识别: %r" % pattern
        assert_address_exists(db, data)


@pytest.mark.api
def test_not_found_short_circuits_pobox(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-025
    payload = merged(base_payload, **addr_data["pobox_short_circuit"])
    assert_not_found(address_client.validate(payload), address_config)


@pytest.mark.api
def test_pobox_with_null_address(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-026
    payload = merged(base_payload, address=None, address2=addr_data["pobox_address2"]["address2"])
    data = assert_ok(address_client.validate(payload), expected)
    assert data["isPoBox"] is True
    assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-07 key fields
# ---------------------------------------------------------------------------



@pytest.mark.api
def test_invalid_postcode_format(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-028
    for postcode in addr_data["postcode_invalid"]:
        body = assert_rejected(
            address_client.validate(merged(base_payload, postcode=postcode)), expected
        )
        if body is None:
            continue
        if "data" in body:  # 参数校验错误：data=null，原因在 msg
            assert body["msg"]
            continue
        text = (body.get("reason") or "").lower()
        assert body["success"] is False
        assert any(
            token in text for token in ("address not found", "postcode", "邮编")
        ), "失败原因不明确: %r" % text


@pytest.mark.api
def test_suburb_special_or_long(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-029
    for suburb in addr_data["suburb_special"]:
        assert_not_found(
            address_client.validate(merged(base_payload, suburb=suburb)), address_config
        )


@pytest.mark.api
def test_state_full_name(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-030
    row = addr_data["valid_states"][0]
    for state in (row["state"], row["state_full"]):
        payload = merged(
            base_payload, state=state, postcode=row["postcode"], suburb=row["suburb"]
        )
        data = assert_ok(address_client.validate(payload), expected)
        assert data["stateCode"] == row["state"]
        assert_address_exists(db, data)


@pytest.mark.api
@pytest.mark.skip(reason="待确认：postcode 传数字类型时的反序列化策略")
def test_postcode_numeric_type(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-031
    response = address_client.validate(
        merged(base_payload, postcode=addr_data["postcode_numeric"])
    )
    assert_rejected(response, expected)


# ---------------------------------------------------------------------------
# AC-08 request shape
# ---------------------------------------------------------------------------



@pytest.mark.api
def test_address_optional(address_client, base_payload, expected, db):
    # case_id: TC-ADDR-033
    data = assert_ok(address_client.validate(without(base_payload, "address")), expected)
    assert data["success"] is True
    assert data["isPoBox"] is False
    assert_address_exists(db, data)


@pytest.mark.api
def test_unknown_field_ignored(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-034
    data = assert_ok(
        address_client.validate(merged(base_payload, **addr_data["unknown_fields"])),
        expected,
    )
    assert data["success"] is True
    assert_address_exists(db, data)


@pytest.mark.api
@pytest.mark.skip(reason="待确认：非法 JSON / 错误 Content-Type 的错误响应契约")
def test_invalid_json_and_content_type(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-035
    response = address_client.post(
        address_client.path,
        data=addr_data["malformed_json"],
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 415)
    response = address_client.post(
        address_client.path,
        json=base_payload,
        headers={"Content-Type": addr_data["content_type_plain"]},
    )
    assert response.status_code in (400, 415)


# ---------------------------------------------------------------------------
# AC-09 address text boundaries (text is decoupled from existence)
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_long_address_still_valid(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-036
    data = assert_ok(
        address_client.validate(merged(base_payload, address=addr_data["long_address"])),
        expected,
    )
    assert data["success"] is True
    assert data["isPoBox"] is False
    assert_address_exists(db, data)


@pytest.mark.api
def test_injection_payload_still_valid(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-037
    response = address_client.validate(
        merged(base_payload, address=addr_data["injection_address"])
    )
    data = assert_ok(response, expected)
    assert data["isPoBox"] is False
    for keyword in ("SQLSyntaxErrorException", "java.lang", "Stacktrace"):
        assert keyword not in response.text, "响应泄露内部异常: %s" % keyword
    assert_address_exists(db, data)


@pytest.mark.api
def test_unicode_address_still_valid(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-038
    data = assert_ok(
        address_client.validate(merged(base_payload, address=addr_data["unicode_address"])),
        expected,
    )
    assert data["success"] is True
    assert data["isPoBox"] is False
    assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-10 default country
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# AC-11 idempotency / concurrency
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_repeated_calls_consistent(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-040
    payload = merged(base_payload, order_id=addr_data["idempotency_order_id"])
    outcomes = []
    for _ in range(5):
        data = assert_ok(address_client.validate(payload), expected)
        assert_address_exists(db, data)
        outcomes.append(
            (data["success"], data["reason"], data["isPoBox"], data["stateCode"])
        )
    assert len(set(outcomes)) == 1, "重复调用结果不一致: %r" % outcomes


@pytest.mark.api
def test_concurrent_calls_consistent(
    address_client_factory, base_payload, addr_data, address_config, expected, db
):
    # case_id: TC-ADDR-041
    prefix = addr_data["concurrent_order_prefix"]
    concurrency = int(address_config.get("concurrency", 5))

    def send(index):
        order_id = "%s%03d" % (prefix, index)
        client = address_client_factory()
        try:
            return order_id, client.validate(merged(base_payload, order_id=order_id))
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(send, range(concurrency)))
    for order_id, response in results:
        data = assert_ok(response, expected)
        assert data["orderId"] == order_id, "并发响应 orderId 串号"
        assert data["isPoBox"] is False
        assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-12 database failure (needs fault injection)
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.skip(reason="需要故障注入使地址表不可用，当前环境未提供")
def test_db_unavailable(address_client, base_payload, expected):
    # case_id: TC-ADDR-042
    response = address_client.validate(base_payload)
    assert response.status_code != 200 or response.json()["data"]["success"] is False


@pytest.mark.api
@pytest.mark.skip(reason="需要故障注入使地址表查询超时，当前环境未提供")
def test_db_timeout(address_client, base_payload, expected):
    # case_id: TC-ADDR-043
    response = address_client.validate(base_payload)
    body = response.json()
    assert body.get("data", {}).get("success") is not True


# ---------------------------------------------------------------------------
# AC-13 response structure
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.skip(reason="待确认：OpenAPI 未声明 required，data 是否始终返回 15 个字段")
def test_success_envelope_schema(address_client, base_payload, db):
    # case_id: TC-ADDR-044
    response = address_client.validate(base_payload)
    assert response.status_code == 200
    body = response.json()
    assert_envelope(body, response)
    assert_data_schema(body["data"], response, require_all=True)
    assert body["data"]["success"] is True
    assert_address_exists(db, body["data"])





@pytest.mark.api
def test_content_type_json(address_client, base_payload, expected, db):
    # case_id: TC-ADDR-046
    response = address_client.validate(base_payload)
    assert response.status_code == expected["http_status"]["ok"]
    assert "application/json" in response.headers.get("Content-Type", "")
    body = response.json()
    assert isinstance(body, dict)
    data = body.get("data") or {}
    if data.get("success") is True:
        assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-14 address2
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.skip(reason="待确认：fullAddress 拼接顺序与 address2 规则")
def test_address2_full_address(address_client, base_payload, expected, db):
    # case_id: TC-ADDR-047
    payload = merged(base_payload, address="10 Market Street", address2="Unit 5")
    data = assert_ok(address_client.validate(payload), expected)
    assert data["address2"] == "Unit 5"
    assert "Unit 5" in data["fullAddress"]
    assert "10 Market Street" in data["fullAddress"]
    assert_address_exists(db, data)


@pytest.mark.api
def test_address2_long_special(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-048
    data = assert_ok(
        address_client.validate(merged(base_payload, address2=addr_data["address2_long"])),
        expected,
    )
    assert data["success"] is True
    assert data["isPoBox"] is False
    assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-15 state / suburb codes
# ---------------------------------------------------------------------------
@pytest.mark.api
@pytest.mark.xfail(reason="待确认：suburbCode 的来源与格式", strict=False)
def test_state_suburb_codes(address_client, base_payload, expected, db):
    # case_id: TC-ADDR-049
    data = assert_ok(address_client.validate(base_payload), expected)
    assert data["stateCode"] == base_payload["state"]
    assert data["suburbCode"]
    assert_address_exists(db, data)


@pytest.mark.api
@pytest.mark.regression
def test_all_states_abbrev_and_full(address_client, base_payload, addr_data, expected, db):
    # case_id: TC-ADDR-050
    for row in addr_data["valid_states"]:
        for state in (row["state"], row["state_full"]):
            payload = merged(
                base_payload,
                state=state,
                postcode=row["postcode"],
                suburb=row["suburb"],
            )
            data = assert_ok(address_client.validate(payload), expected)
            assert data["stateCode"] == row["state"]
            assert data["postcode"] == row["postcode"]
            assert_address_exists(db, data)


# ---------------------------------------------------------------------------
# AC-16 address text is decoupled from existence
# ---------------------------------------------------------------------------
@pytest.mark.api
def test_random_and_non_au_text_still_valid(
    address_client, base_payload, addr_data, expected, db
):
    # case_id: TC-ADDR-051
    for address in addr_data["random_addresses"]:
        data = assert_ok(
            address_client.validate(merged(base_payload, address=address)), expected
        )
        assert data["success"] is True
        assert data["isPoBox"] is False
        assert_address_exists(db, data)
