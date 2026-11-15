import pytest


@pytest.mark.api
@pytest.mark.smoke
def test_get_post_detail(api_client):
    # case_id: API-POST-001
    response = api_client.get("/api/posts/1")

    # Layer 1: HTTP status code
    assert response.status_code == 200

    # Layer 2: response JSON structure
    body = response.json()
    assert isinstance(body, dict)
    assert {"id", "title", "body", "userId"} <= set(body)
    assert isinstance(body["id"], int)
    assert isinstance(body["userId"], int)
    assert isinstance(body["title"], str)
    assert isinstance(body["body"], str)

    # Layer 3: core business field values
    assert body["id"] == 1
    assert body["userId"] == 1
    assert body["title"] == "demo post"
