# -*- coding: utf-8 -*-
"""Manual debug helper for POST /address/validate (not collected by pytest).

Run manually:
    python tests/api/debug_api.py
"""
import json
from pathlib import Path

from api_clients.address_client import AddressClient
from config.config_loader import get_required

ROOT = Path(__file__).resolve().parents[1]


def main():
    base_url = get_required("api_base_url")
    path = get_required("address_validation.path")
    timeout = float(get_required("api_timeout"))
    payload = json.loads(
        (ROOT / "data" / "address_validate.json").read_text(encoding="utf-8")
    )["base"]
    client = AddressClient(base_url, timeout=timeout, path=path)
    try:
        response = client.validate(payload)
        print("HTTP", response.status_code)
        print(response.text)
    finally:
        client.close()


if __name__ == "__main__":
    main()
