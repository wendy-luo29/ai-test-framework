"""API 层公共前置：被测环境未配置时整体失败，而不是静默 skip。

原问题：services.<module>.<env> 为空时每条用例各自 skip，pytest 退出码仍为 0，
形成"全部跳过 = 全部通过"的假绿。这里在会话开始前统一校验，缺配置直接失败。
"""

from __future__ import annotations

import pytest

from config.config_loader import get_config


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
