"""Sample page object for the bundled demo app; replace with real screens."""

from playwright.sync_api import Locator

from pages.base_page import BasePage


class HomePage(BasePage):
    @property
    def heading(self) -> Locator:
        return self.page.get_by_role("heading", level=1)

    @property
    def message(self) -> Locator:
        return self.page.locator("#message")
