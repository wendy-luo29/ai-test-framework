"""Shared fixtures: a bundled demo server plus wiring to config/env.yaml.

All URLs, credentials, and timeouts come from config/env.yaml via
config/config_loader.py. When the UI/API base URLs are empty, tests run against
a local in-process server so the suite is deterministic and offline.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from api_clients.address_client import AddressClient
from api_clients.base_client import BaseApiClient
from config.config_loader import ConfigError, get_config, get_required

DATA_DIR = Path(__file__).resolve().parent / "data"

DEMO_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Demo App</title></head>
<body>
  <h1>Demo App</h1>
  <p id="message">Ready</p>
</body>
</html>
"""

DEMO_POSTS = {1: {"id": 1, "title": "demo post", "body": "hello", "userId": 1}}

DEMO_USERS = {
    1: {
        "user_id": 1,
        "username": "demo_user",
        "email": "demo@example.com",
        "status": "active",
    }
}


class _DemoHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html(200, DEMO_HTML)
        elif parsed.path == "/api/user/get_profile":
            self._handle_get_profile(parse_qs(parsed.query))
        elif parsed.path.startswith("/api/posts/"):
            try:
                post = DEMO_POSTS.get(int(parsed.path.rsplit("/", 1)[-1]))
            except ValueError:
                post = None
            if post is None:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(200, post)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_get_profile(self, query: dict) -> None:
        raw_user_id = query.get("user_id")
        if not raw_user_id:
            self._send_json(400, {"error": "user_id is required"})
            return
        try:
            user_id = int(raw_user_id[0])
        except ValueError:
            self._send_json(400, {"error": "user_id must be an integer"})
            return
        user = DEMO_USERS.get(user_id)
        if user is None:
            self._send_json(404, {"error": "user not found"})
        else:
            self._send_json(200, user)

    def do_POST(self) -> None:
        if self.path == "/api/posts":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._send_json(201, {"id": 101, **payload})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="session")
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def config():
    return get_config()


@pytest.fixture(scope="session")
def ui_base_url(config, local_server):
    return config.get("ui_base_url") or local_server


@pytest.fixture(scope="session")
def api_base_url(config, local_server):
    return config.get("api_base_url") or local_server


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, ui_base_url):
    """Inject the UI base URL and a fixed viewport into every browser context."""
    return {
        **browser_context_args,
        "base_url": ui_base_url,
        "viewport": {"width": 1280, "height": 720},
    }


@pytest.fixture
def api_client(config, api_base_url):
    timeout = get_required("api_timeout", config=config)
    if not isinstance(timeout, (int, float)):
        raise ConfigError("'api_timeout' must be a number in config/env.yaml")
    client = BaseApiClient(api_base_url, timeout=float(timeout))
    yield client
    client.close()


@pytest.fixture(scope="session")
def address_config(config):
    """Raw address_validation block: path, default_country, expected code table."""
    return get_required("address_validation", config=config)


@pytest.fixture
def address_client(config, api_base_url, address_config):
    timeout = get_required("api_timeout", config=config)
    if not isinstance(timeout, (int, float)):
        raise ConfigError("'api_timeout' must be a number in config/env.yaml")
    client = AddressClient(
        api_base_url,
        timeout=float(timeout),
        path=address_config["path"],
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def load_json():
    """Load a JSON file from data/ by filename."""

    def _load(name: str):
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))

    return _load
