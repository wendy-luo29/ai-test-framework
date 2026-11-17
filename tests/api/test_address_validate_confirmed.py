# REQ-001 | 已确认通过的 13 条地址校验用例
"""POST /address/validate 已确认通过用例（smoke 子集）。

来源：.claude/skills/design-testcases/output/REQ-001-TC-design-v2.md
覆盖 TC-ADDR-001/002/005/006/007/013/019/020/021/027/032/039/045。
环境地址、默认国家、not found 文案来自 config/env.yaml；测试数据来自 data/。
"""

import os

import pytest

from config.config_loader import get_value
from utils.api_assertions import (
    assert_data_schema,
    assert_envelope,
    assert_not_found,
    assert_ok,
    assert_validation_error,
    parse_json,
    merged,
    without,
)

_REASONS = []
_RUN_IN_CI = os.getenv("ADDRESS_API_ALLOW_CI", "").strip().lower() in ("true", "1", "yes")
if os.getenv("CI", "").strip().lower() in ("true", "1", "yes") and not _RUN_IN_CI:
    _REASONS.append("CI 环境无法访问内网地址服务（设置 ADDRESS_API_ALLOW_CI=1 可强制执行）")
if not get_value("api_base_url", ""):
    _REASONS.append("api_base_url 为空，本地 demo server 未实现 /address/validate")

pytestmark = pytest.mark.skipif(bool(_REASONS), reason="；".join(_REASONS))


@pytest.mark.api
@pytest.mark.smoke
def test_validate_valid_address(address_client, base_payload, expected):
    # case_id: TC-ADDR-001
    data = assert_ok(address_client.validate(base_payload), expected)
    assert data["success"] is True
    assert data["isPoBox"] is False
    assert data["countryCode"] == "AU"
    assert data["stateCode"] == base_payload["state"]
    assert data["postcode"] == base_payload["postcode"]
    assert data["suburb"] == base_payload["suburb"]
    assert data["orderId"] == base_payload["order_id"]


@pytest.mark.api
@pytest.mark.smoke
def test_not_found_suburb(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-002
    payload = merged(base_payload, suburb=addr_data["not_found"]["suburb"])
    assert_not_found(address_client.validate(payload), address_config)


@pytest.mark.api
@pytest.mark.smoke
def test_not_found_postcode(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-005
    payload = merged(base_payload, postcode=addr_data["not_found"]["postcode"])
    assert_not_found(address_client.validate(payload), address_config)


@pytest.mark.api
@pytest.mark.smoke
def test_not_found_state(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-006
    payload = merged(base_payload, state=addr_data["not_found"]["state"])
    assert_not_found(address_client.validate(payload), address_config)


@pytest.mark.api
@pytest.mark.smoke
def test_cross_state_postcode_mismatch(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-007
    payload = merged(base_payload, **addr_data["not_found"]["cross"])
    assert_not_found(address_client.validate(payload), address_config)


@pytest.mark.api
@pytest.mark.smoke
def test_order_id_roundtrip(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-013
    order_id = addr_data["order_ids"][0]
    data = assert_ok(
        address_client.validate(merged(base_payload, order_id=order_id)), expected
    )
    assert data["orderId"] == order_id


@pytest.mark.api
@pytest.mark.smoke
def test_pobox_address1_match(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-019
    data = assert_ok(
        address_client.validate(merged(base_payload, **addr_data["pobox_primary"])),
        expected,
    )
    assert data["success"] is True
    assert data["isPoBox"] is True


@pytest.mark.api
@pytest.mark.smoke
def test_pobox_address2_match(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-020
    data = assert_ok(
        address_client.validate(merged(base_payload, **addr_data["pobox_address2"])),
        expected,
    )
    assert data["isPoBox"] is True


@pytest.mark.api
@pytest.mark.smoke
def test_pobox_not_matched(address_client, base_payload, addr_data, expected):
    # case_id: TC-ADDR-021
    data = assert_ok(
        address_client.validate(merged(base_payload, **addr_data["pobox_none"])),
        expected,
    )
    assert data["isPoBox"] is False


@pytest.mark.api
@pytest.mark.smoke
def test_missing_key_fields(address_client, base_payload, expected):
    # case_id: TC-ADDR-027
    for field in ("state", "postcode", "suburb"):
        body = assert_validation_error(
            address_client.validate(without(base_payload, field)), expected
        )
        if body is not None:
            assert field in body["msg"], "msg 应指出缺失字段: %r" % body["msg"]


@pytest.mark.api
@pytest.mark.smoke
def test_empty_json_body(address_client, expected):
    # case_id: TC-ADDR-032
    body = assert_validation_error(address_client.validate({}), expected)
    if body is not None:
        assert body["msg"]


@pytest.mark.api
@pytest.mark.smoke
def test_default_country(address_client, base_payload, address_config, expected):
    # case_id: TC-ADDR-039
    data = assert_ok(address_client.validate(without(base_payload, "country")), expected)
    assert data["country"] == address_config["default_country"]
    assert data["countryCode"] == "AU"


@pytest.mark.api
@pytest.mark.smoke
def test_not_found_envelope_schema(address_client, base_payload, addr_data, address_config):
    # case_id: TC-ADDR-045
    payload = merged(base_payload, suburb=addr_data["not_found"]["suburb"])
    response = address_client.validate(payload)
    body = parse_json(response)
    assert response.status_code == address_config["expected"]["http_status"]["ok"]
    assert_envelope(body, response)
    assert_data_schema(body["data"], response)
    assert body["data"]["success"] is False
    assert body["data"]["reason"] == address_config["reason"]["not_found"]
