"""Transport-only API client base. Assertions belong in tests."""

from urllib.parse import urljoin

import requests


class BaseApiClient:
    def __init__(self, base_url: str, timeout: float = 10.0, headers=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()
        if headers:
            self.session.headers.update(headers)

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        url = urljoin(self.base_url, path.lstrip("/"))
        return self.session.request(method, url, **kwargs)

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "BaseApiClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
