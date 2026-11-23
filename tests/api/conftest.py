"""API 层公共前置：被测环境未配置时整体失败，而不是静默 skip。

原问题：services.<module>.<env> 为空时每条用例各自 skip，pytest 退出码仍为 0，
形成"全部跳过 = 全部通过"的假绿。这里在会话开始前统一校验，缺配置直接失败。
"""

from __future__ import annotations

import os

import pytest

from config.config_loader import get_config, get_module_config


@pytest.fixture(scope="session", autouse=True)
def require_api_environment():
    cfg = get_config()
    env = cfg.get("env", "local")
    quote_url = (cfg.get("services") or {}).get("lsp_quote", {}).get(env, "")
    if not quote_url:
        pytest.fail(
            f"API 被测环境未配置：services.lsp_quote.{env} 为空。"
            f"请在 config/base.yaml 填写该环境地址，或把 config/env.yaml 的 env 改到已配置环境。",
            pytrace=False,
        )

    token_env = (get_module_config("lsp_quote", "price_sync").get("auth") or {}).get("token_env")
    if token_env and not os.getenv(token_env):
        pytest.fail(
            f"鉴权 Token 未提供：环境变量 {token_env} 为空。"
            f"REQ-002 接口要求 Bearer Token，缺失时不再逐条 skip。",
            pytrace=False,
        )
