"""Page-object base wrapping a Playwright Page. No assertions on business data."""

from playwright.sync_api import Locator, Page, expect


class BasePage:
    def __init__(self, page: Page):
        self.page = page

    def open(self, path: str = "/") -> None:
        self.page.goto(path)

    def locator(self, selector: str) -> Locator:
        return self.page.locator(selector)

    def expect_visible(self, locator: Locator) -> None:
        expect(locator).to_be_visible()

    def expect_text(self, locator: Locator, text) -> None:
        expect(locator).to_have_text(text)
