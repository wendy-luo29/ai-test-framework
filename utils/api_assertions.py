# -*- coding: utf-8 -*-
"""Assertion helpers for the API layer.

Three-layer checks: HTTP status -> JSON envelope/schema -> business fields.
No transport, no test data, no business rules.
"""

import json

ENVELOPE_FIELDS = {"code", "data", "hasMore", "msg", "success", "tc", "tp"}
DATA_FIELDS = {
    "address", "address2", "adviceAddress", "country", "countryCode",
    "fullAddress", "isPoBox", "orderId", "postcode", "reason", "state",
    "stateCode", "suburb", "suburbCode", "success",
}
CORE_DATA_FIELDS = {"success", "isPoBox", "reason", "state", "postcode", "suburb"}
BOOL_FIELDS = {"success", "isPoBox"}


def _body(response):
    try:
        return response.json()
    except ValueError:
        return None


def _message(response, text):
    body = _body(response)
    rendered = json.dumps(body, ensure_ascii=False) if body is not None else response.text
    return "%s\nHTTP %s\n响应体: %s" % (text, response.status_code, rendered)


def parse_json(response):
    """Return the JSON body or fail with response context."""
    body = _body(response)
    assert body is not None, _message(response, "响应体不是合法 JSON")
    return body


def assert_envelope(body, response):
    """Layer 2: RestResult envelope keys and value types."""
    assert isinstance(body, dict), _message(response, "响应体不是 JSON 对象")
    missing = ENVELOPE_FIELDS - set(body)
    assert not missing, _message(response, "包装层缺少字段: %s" % sorted(missing))
    assert isinstance(body["code"], str), _message(response, "code 应为 string")
    assert isinstance(body["msg"], str), _message(response, "msg 应为 string")
    assert isinstance(body["success"], bool), _message(response, "success 应为 boolean")
    for field in ("hasMore", "tc", "tp"):
        value = body[field]
        assert isinstance(value, int) and not isinstance(value, bool), _message(
            response, "%s 应为整数" % field
        )


def assert_data_schema(data, response, require_all=False):
    """Layer 2: data object types; core business keys are mandatory."""
    assert isinstance(data, dict), _message(response, "data 不是 JSON 对象")
    required = DATA_FIELDS if require_all else CORE_DATA_FIELDS
    missing = required - set(data)
    assert not missing, _message(response, "data 缺少字段: %s" % sorted(missing))
    for field in DATA_FIELDS & set(data):
        value = data[field]
        if field in BOOL_FIELDS:
            assert isinstance(value, bool), _message(response, "data.%s 应为 boolean" % field)
        else:
            assert value is None or isinstance(value, str), _message(
                response, "data.%s 应为 string 或 null" % field
            )


def assert_ok(response, expected):
    """Layer 1/2/3 for a successful validation."""
    assert response.status_code == expected["http_status"]["ok"], _message(
        response, "HTTP 状态码应为 %s" % expected["http_status"]["ok"]
    )
    body = parse_json(response)
    assert_envelope(body, response)
    assert body["success"] is True, _message(response, "包装 success 应为 true")
    data = body["data"]
    assert_data_schema(data, response)
    assert data["success"] is True, _message(response, "data.success 应为 true")
    return data


def assert_business_failure(response, expected):
    """HTTP 200 + handled business failure (e.g. address not found)."""
    assert response.status_code == expected["http_status"]["ok"], _message(
        response, "业务失败应返回 HTTP 200"
    )
    body = parse_json(response)
    assert_envelope(body, response)
    data = body["data"]
    assert_data_schema(data, response)
    assert data["success"] is False, _message(response, "data.success 应为 false")
    reason = data["reason"] or body["msg"]
    assert reason, _message(response, "业务失败必须返回 reason 或 msg")
    return data


def assert_not_found(response, address_config):
    """Layer 3: exact not-found business result."""
    expected = address_config["expected"]
    reason = address_config["reason"]["not_found"]
    body = parse_json(response)
    data = assert_business_failure(response, expected)
    actual = data["reason"] or body["msg"] or ""
    assert actual == reason or reason.lower() in actual.lower(), _message(
        response, "reason 应为 %r，实际 %r" % (reason, actual)
    )
    return data


def assert_validation_error(response, expected):
    """Handled parameter-validation failure (HTTP 200 code=400 data=null)."""
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(
        response, "状态码应属于 %s" % sorted(allowed)
    )
    if response.status_code == expected["http_status"]["client_error"]:
        return None
    body = parse_json(response)
    assert_envelope(body, response)
    assert body["success"] is False, _message(response, "参数校验失败时包装 success 应为 false")
    assert body["code"] == expected["code"]["param_error"], _message(
        response, "参数校验失败 code 应为 %s" % expected["code"]["param_error"]
    )
    assert body["msg"], _message(response, "参数校验失败必须返回 msg")
    return body


def assert_rejected(response, expected):
    """Malformed input: HTTP 400, or HTTP 200 validation/business failure.

    Returns the parsed envelope for HTTP 200, or None for HTTP 400.
    """
    allowed = {expected["http_status"]["ok"], expected["http_status"]["client_error"]}
    assert response.status_code in allowed, _message(
        response, "状态码应属于 %s" % sorted(allowed)
    )
    if response.status_code == expected["http_status"]["client_error"]:
        return None
    body = parse_json(response)
    assert_envelope(body, response)
    if body.get("data") is None:
        assert body["success"] is False, _message(
            response, "参数校验失败时包装 success 应为 false"
        )
        assert body["code"] == expected["code"]["param_error"], _message(
            response, "参数校验失败 code 应为 %s" % expected["code"]["param_error"]
        )
        assert body["msg"], _message(response, "参数校验失败必须返回 msg")
        return body
    return assert_business_failure(response, expected)


def merged(base, **overrides):
    payload = dict(base)
    payload.update(overrides)
    return payload


def without(base, *keys):
    payload = dict(base)
    for key in keys:
        payload.pop(key, None)
    return payload
