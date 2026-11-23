# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Python test automation framework split into two independent layers: API tests driven by `requests` (`tests/api`, `api_clients/`) and browser UI tests driven by Playwright through `pytest-playwright` (`tests/ui`, `pages/`). The root `conftest.py` wires both layers to `config/env.yaml` through `config/config_loader.py`.

By default the suite runs fully offline against an in-process demo server started by the `local_server` fixture in `conftest.py`. Setting `ui_base_url` / `api_base_url` in `config/env.yaml` redirects the suite at a real system under test; when empty, the fixtures fall back to the demo server.

## Team conventions (mandatory)

These rules are binding for every script generated or edited in this repository.

1. **Naming and case IDs**
   - API test scripts live in `tests/api/`.
   - Filename format: `test_<module>_<scenario>.py` (e.g. `test_user_register.py`, `test_post_get_detail.py`).
   - The first line of every `def test_*` body must be a case ID comment, e.g. `# case_id: API-LOGIN-001`.
2. **Three-layer assertions** — API tests must never assert only the status code. Every test asserts:
   - Layer 1: HTTP status code.
   - Layer 2: response JSON structure completeness (required keys and value types).
   - Layer 3: core business field values.
3. **No hardcoding** — literal URLs, accounts, passwords, and timeouts are forbidden in code. All such settings must be read from `config/env.yaml` through `config/config_loader.py` (`get_config()` / `get_value()` / `get_required()`).

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate        # Git Bash on Windows; .venv\Scripts\activate in cmd/PowerShell
pip install -r requirements.txt
playwright install                   # add --with-deps on Linux CI
```

Edit `config/env.yaml` to target a real system; no environment file is needed for the default offline run.

## Commands

```bash
pytest                                                        # full suite
pytest -m smoke                                               # critical-path subset
pytest tests/api                                              # API layer only
pytest tests/ui                                               # UI layer only
pytest tests/ui/test_example_home.py::test_home_page_heading  # single test
pytest --headed                                               # watch the browser
pytest --browser firefox                                      # chromium (default) | firefox | webkit
pytest --html=reports/report.html --self-contained-html       # HTML report
PWDEBUG=1 pytest tests/ui                                     # Playwright inspector (bash syntax)
```

## Architecture

Dependency direction is `tests/` → `pages/` or `api_clients/` → `config/`; fixtures live in the root `conftest.py`, with layer-specific fixtures in `tests/api/conftest.py` and `tests/ui/conftest.py`.

- `config/base.yaml` + `config/env.yaml` — `base.yaml` 维护公共定义（`env`、`services.<module>.<env>`、`database`、`api_timeout`），`env.yaml` 只写本机差异（地址、账号），加载时深度合并，同名键由 `env.yaml` 覆盖。`api_base_url` 仅作兼容保留，新代码用 `get_service_url(module)`。
- `config/config_loader.py` — `load_config()` parses and validates the YAML mapping; `get_config()` caches it; `get_value("dotted.path")` and `get_required("dotted.path")` read nested values, with `ConfigError` for missing/malformed config.
- `conftest.py` — owns the fixture graph:
  - `local_server` — session-scoped threaded `http.server` exposing `/` (demo HTML page), `/api/posts[/{id}]`, and `/api/user/get_profile?user_id=`; the offline default target.
  - `config` — cached YAML configuration.
  - `ui_base_url` / `api_base_url` — read the merged config, falling back to `local_server`.
  - `browser_context_args` — overrides pytest-playwright to inject `base_url` and a fixed viewport into every browser context.
  - API 层 fixture（`quote_client`、`scp_db` 等）在 `tests/api/` 内定义；`tests/api/conftest.py` 的会话级自检会在被测地址或 Token 缺失时直接失败，避免"全部 skip 仍算通过"。
  - `load_json` — reads payloads from `data/`.
- `api_clients/base_client.py` — `BaseApiClient` wraps a `requests.Session` with base-URL joining, a default timeout, and `get`/`post` helpers. Service-specific clients subclass it and stay transport-only.
- `pages/base_page.py` — `BasePage` wraps a Playwright `Page` with navigation and locate/expect helpers. One class per screen.
- `tests/` — `tests/api` and `tests/ui` mirror the two layers. Tests own all assertions.
- `data/` — JSON fixtures loaded through `load_json`.
- `reports/` — generated output, git-ignored except `.gitkeep`.

`pytest-playwright` supplies the `page`, `context`, and `browser` fixtures; browser-level options (base URL, viewport, storage state) belong in the `browser_context_args` override rather than in individual tests.

## Extending

- New API coverage: add `api_clients/<service>_client.py` subclassing `BaseApiClient`, expose a fixture in `conftest.py`, then add `tests/api/test_<module>_<scenario>.py` with a `# case_id:` first line and all three assertion layers.
- New UI coverage: add `pages/<screen>_page.py` subclassing `BasePage`, inject `page` into the test, and mark it `@pytest.mark.ui`.
- New local demo endpoint: extend `_DemoHandler` in `conftest.py` so offline tests can cover the new path.

## Markers

Registered in `pytest.ini` under `--strict-markers`: `smoke`, `api`, `ui`, `regression`. An unregistered marker fails the run, so add new ones to `pytest.ini`.
