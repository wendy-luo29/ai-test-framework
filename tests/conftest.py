"""Root conftest: shared fixtures across ALL test modules.

只放跨模块通用的东西：config、DB 连接、HTTP server demo、
browser_context_args、load_json 辅助。

模块专属 fixture（如 address_client、quote_client 等）
放在各自模块的 conftest.py 里。
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:  # pragma: no cover
    pymysql = None
    DictCursor = None

from config.config_loader import ConfigError, get_config

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

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
    """When service URLs are empty → tests run against this in-process server."""
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
    """Merged configuration from config/env.yaml or config/base.yaml."""
    return get_config()


@pytest.fixture(scope="session")
def ui_base_url(config, local_server):
    """UI base URL; empty → demo server."""
    return config.get("ui_base_url")


@pytest.fixture(scope="session")
def api_base_url(config, local_server):
    """Default API base URL; empty → demo server."""
    return config.get("api_base_url")


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, ui_base_url):
    """Inject base URL and fixed viewport into every browser context."""
    return {
        **browser_context_args,
        "base_url": ui_base_url,
        "viewport": {"width": 1280, "height": 720},
    }


@pytest.fixture(scope="session")
def load_json():
    """Load a JSON file from data/<module>/ or data/ by filename."""

    def _load(module_or_name: str, name: str | None = None):
        # Callable signatures:
        #   load_json("address_validate.json")             → data/address_validate.json
        #   load_json("lsp_backend", "address_validate.json") → data/lsp_backend/address_validate.json
        if name is None:
            path = DATA_DIR / module_or_name
        else:
            path = DATA_DIR / module_or_name / name
        return json.loads(path.read_text(encoding="utf-8"))

    return _load


# ──────────────────────────────────────────────────────────
# DatabaseClient (跨模块通用，只读断言)
# ──────────────────────────────────────────────────────────

class DatabaseClient:
    """Read-only MySQL access for assertions. Queries stay in tests."""

    def __init__(self, options: dict, password: str):
        self.conn = pymysql.connect(
            host=options["host"],
            port=int(options.get("port", 3306)),
            user=options["user"],
            password=password,
            database=options["name"],
            charset=options.get("charset", "utf8mb4"),
            connect_timeout=int(options.get("connect_timeout", 5)),
            read_timeout=int(options.get("read_timeout", 10)),
            cursorclass=DictCursor,
        )

    def fetch_one(self, sql: str, params=None):
        self.conn.ping(reconnect=True)
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def fetch_all(self, sql: str, params=None):
        self.conn.ping(reconnect=True)
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def close(self) -> None:
        self.conn.close()


@pytest.fixture(scope="session")
def db(config):
    """MySQL connection for data assertions. Skips when not configured."""
    options = config.get("database") or {}
    if pymysql is None:
        pytest.skip("pymysql 未安装，跳过数据库断言")
    if not options.get("host") or not options.get("name") or not options.get("user"):
        pytest.skip("config/base.yaml 未配置 database.host/user/name，跳过数据库断言")

    env_name = options.get("password_env", "TEST_DB_PASSWORD")
    password = os.getenv(env_name, "")
    if not password:
        pytest.skip(f"环境变量 {env_name} 未设置，跳过数据库断言")

    try:
        client = DatabaseClient(options, password)
    except Exception as exc:
        pytest.skip(f"数据库连接失败：{exc}")

    yield client
    client.close()
