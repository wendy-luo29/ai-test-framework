import pytest


@pytest.mark.api
def test_create_post(api_client, load_json):
    # case_id: API-POST-002
    payload = load_json("example_post.json")
    response = api_client.post("/api/posts", json=payload)

    # Layer 1: HTTP status code
    assert response.status_code == 201

    # Layer 2: response JSON structure
    body = response.json()
    assert isinstance(body, dict)
    assert {"id", "title", "body", "userId"} <= set(body)
    assert isinstance(body["id"], int)
    assert isinstance(body["userId"], int)
    assert isinstance(body["title"], str)
    assert isinstance(body["body"], str)

    # Layer 3: core business field values
    assert body["title"] == payload["title"]
    assert body["body"] == payload["body"]
    assert body["userId"] == payload["userId"]
