"""UI 测试共享 fixture：登录后进入 0102 手工订单页。

凭据与地址来自 config/env.yaml 的 credentials.ui 与 ui_base_url，
禁止在测试代码里硬编码。
"""
from __future__ import annotations

import pytest

from pages.login_page import LoginPage
from pages.manual_order_page import ManualOrderPage


@pytest.fixture(scope="session")
def browser_context_args(ui_base_url):
    """UI 后台是 ExtJS 多面板布局，需要更大的视口才能完整渲染产品明细区。"""
    return {
        "base_url": ui_base_url,
        "viewport": {"width": 1600, "height": 1000},
    }


@pytest.fixture
def ui_credentials(config):
    creds = (config.get("credentials") or {}).get("ui") or {}
    if not creds.get("username") or not creds.get("password"):
        pytest.skip("config 未配置 credentials.ui 账号密码，跳过 UI 用例")
    return creds


@pytest.fixture
def logged_in_page(page, ui_base_url, ui_credentials):
    """已登录的后台 page，供各业务模块自行构造 Page Object。

    新增页面时在本模块写：
        @pytest.fixture
        def xxx_page(logged_in_page):
            p = XxxPage(logged_in_page)
            p.open_xxx()
            return p
    """
    if not ui_base_url:
        pytest.skip("ui_base_url 为空，跳过 UI 用例")
    login = LoginPage(page, ui_base_url, ui_credentials.get("login_path", "/business/manage/login/"))
    login.goto_login()
    login.login(ui_credentials["username"], ui_credentials["password"])
    login.expect_logged_in()
    return page


@pytest.fixture
def manual_order_page(logged_in_page):
    """登录后台并打开 0102 手工订单页，返回 ManualOrderPage。"""
    order = ManualOrderPage(logged_in_page)
    order.open_0102()
    return order
