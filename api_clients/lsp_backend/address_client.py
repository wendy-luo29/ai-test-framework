"""Transport-only client for the address-validation service (module 06_地址校验)."""

from api_clients.base_client import BaseApiClient


class AddressClient(BaseApiClient):
    """Wraps POST /address/validate. Assertions stay in tests."""

    def __init__(self, base_url: str, timeout: float, path: str, headers=None):
        super().__init__(base_url, timeout=timeout, headers=headers)
        self.path = path

    def validate(self, payload: dict, **kwargs):
        """POST the address payload to the configured validation route."""
        return self.post(self.path, json=payload, **kwargs)
