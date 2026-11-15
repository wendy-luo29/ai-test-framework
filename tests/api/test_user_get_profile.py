import pytest


@pytest.mark.api
@pytest.mark.smoke
def test_get_user_profile(api_client, load_json):
    # case_id: API-USER-001
    params = load_json("user_profile_request.json")

    response = api_client.get("/api/user/get_profile", params=params)

    # Layer 1: HTTP status code
    assert response.status_code == 200

    # Layer 2: response JSON structure
    body = response.json()
    assert isinstance(body, dict)
    assert {"user_id", "username", "email", "status"} <= set(body)
    assert isinstance(body["user_id"], int)
    assert isinstance(body["username"], str)
    assert isinstance(body["email"], str)
    assert isinstance(body["status"], str)

    # Layer 3: core business field values
    assert body["user_id"] == params["user_id"]
    assert body["username"] == "demo_user"
    assert body["email"] == "demo@example.com"
    assert body["status"] == "active"
