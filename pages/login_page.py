"""登录页 — ExtJS 管理后台。"""
from __future__ import annotations

from playwright.sync_api import Page

from pages.base_page import BasePage


class LoginPage(BasePage):
    # 选择器集中管理；ExtJS 生成的 id 不稳定，优先用 name
    USERNAME = "input[name='username']"
    PASSWORD = "input[name='password']"
    LOGIN_BTN = "a#button-1012"  # Login 按钮（探测多次稳定）

    def __init__(self, page: Page, base_url: str, login_path: str):
        super().__init__(page)
        self.base_url = base_url.rstrip("/")
        self.login_path = login_path

    def goto_login(self) -> None:
        self.page.goto(f"{self.base_url}{self.login_path}")
        self.page.wait_for_load_state("networkidle")

    def login(self, username: str, password: str) -> None:
        self.fill(self.USERNAME, username)
        self.fill(self.PASSWORD, password)
        self.page.click(self.LOGIN_BTN)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1500)

    def expect_logged_in(self) -> None:
        # 登录成功后出现「业务管理」tab
        self.expect_visible(self.page.locator("#tab-1029"))
