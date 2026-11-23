"""Transport-only client for the quote price-sync service (REQ-002).

POST /quote/price_sync — 按订单与包裹信息返回各承运商运费报价列表。
Assertions stay in tests; this class adds no business logic.
"""

from api_clients.base_client import BaseApiClient


class PriceSyncClient(BaseApiClient):
    def __init__(self, base_url: str, timeout: float, path: str, headers=None):
        super().__init__(base_url, timeout=timeout, headers=headers)
        self.path = path

    def price_sync(self, payload: dict, **kwargs):
        """POST the QuoteTaskDto payload to the configured route."""
        return self.post(self.path, json=payload, **kwargs)
