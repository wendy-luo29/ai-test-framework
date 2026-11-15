import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

class BasePage:
    def __init__(self, page: Page):
        self.page = page

    def click(self, selector: str):
        logger.info(f"点击元素: {selector}")
        self.page.click(selector)

    def fill(self, selector: str, text: str):
        logger.info(f"在元素 {selector} 中输入: {text}")
        self.page.fill(selector, text)

    def get_text(self, selector: str) -> str:
        logger.info(f"获取元素文本: {selector}")
        return self.page.text_content(selector)