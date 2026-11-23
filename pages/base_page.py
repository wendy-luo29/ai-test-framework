"""Page-object base wrapping a Playwright Page.

通用层只放与具体业务无关的工具：导航、文本/可见性断言、
以及 ExtJS 控件的通用操作（下拉、遮罩、确认框）。
业务断言（金额、状态）一律放在各自 Page Object 或 test 里。
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect, TimeoutError as PWTimeout


class BasePage:
    def __init__(self, page: Page):
        self.page = page

    # ── 导航 ──────────────────────────────────────────────
    def open(self, path: str = "/") -> None:
        self.page.goto(path)

    def locator(self, selector: str) -> Locator:
        return self.page.locator(selector)

    # ── 基础断言 ──────────────────────────────────────────
    def expect_visible(self, locator: Locator) -> None:
        expect(locator).to_be_visible()

    def expect_text(self, locator: Locator, text) -> None:
        expect(locator).to_have_text(text)

    # ── ExtJS 通用控件 ───────────────────────────────────
    def fill(self, selector: str, value: str) -> None:
        self.page.fill(selector, value)

    def select_combo(self, input_selector: str, text: str) -> None:
        """ExtJS combobox：点开下拉，选中含 text 的可见项，关闭下拉。"""
        self.page.click(input_selector)
        self.page.wait_for_timeout(400)
        item = self.page.locator(".x-boundlist-item:visible", has_text=text).first
        item.click()
        # 关闭残留下拉，避免影响后续控件
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)

    def select_remote_combo(self, input_selector: str, search_text: str,
                            pick_text: str | None = None) -> None:
        """ExtJS 远程搜索下拉：输入 search_text 触发搜索，选中含 pick_text 的项。
        pick_text 为 None 时选第一个可见项。"""
        self.page.click(input_selector)
        self.page.fill(input_selector, search_text)
        self.page.wait_for_timeout(1500)  # 等远程结果返回
        target = pick_text or search_text
        item = self.page.locator(".x-boundlist-item:visible", has_text=target).first
        if item.count() == 0:
            item = self.page.locator(".x-boundlist-item:visible").first
        item.click()
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)

    def wait_overlay(self, timeout: int = 15000) -> None:
        """等待 loading 遮罩消失（ExtJS .x-mask）。"""
        try:
            self.page.wait_for_selector(".x-mask", state="hidden", timeout=timeout)
        except PWTimeout:
            pass
        self.page.wait_for_timeout(400)

    def click_confirm(self, btn_text: str = "是") -> bool:
        """处理 ExtJS 确认框（.x-message-box），点击指定按钮。返回是否点中。"""
        for sel in (
            f'.x-message-box a.x-btn:has-text("{btn_text}")',
            f'.x-window a.x-btn:has-text("{btn_text}")',
        ):
            loc = self.page.locator(sel)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=5000)
                    self.page.wait_for_timeout(1200)
                    return True
                except PWTimeout:
                    continue
        # 兜底：role 定位
        try:
            self.page.get_by_role("button", name=btn_text).first.click(timeout=5000)
            self.page.wait_for_timeout(1200)
            return True
        except PWTimeout:
            return False

    # ── ExtJS 列表页：关键字查询 / 表格读取 ───────────────
    def search_keywords(self, keyword: str, grid_id: str | None = None) -> None:
        """顶部关键字查询：填可见 keywords 框 → 点可见「查询」→ 等 store 加载完成。

        多页面 tab 同时存在于 DOM，隐藏页也带 input[name='keywords']，
        因此必须用 :visible 过滤，否则会填到其它 tab 的隐藏输入框。
        """
        self.page.locator("input[name='keywords']:visible").first.fill(keyword)
        self.page.locator("a.x-btn:visible:has-text('查询')").first.click()
        self.page.wait_for_timeout(800)
        if grid_id:
            try:
                self.page.wait_for_function(
                    """(gid) => {
                        const g = Ext.getCmp(gid);
                        if (!g) return true;
                        const s = g.getStore && g.getStore();
                        return !s || !s.isLoading();
                    }""",
                    arg=grid_id,
                    timeout=30000,
                )
            except PWTimeout:
                pass
        self.wait_overlay()

    def grid_rows(self, grid_id: str, limit: int = 50) -> list[dict]:
        """读取 ExtJS grid 前 limit 行：data(store 原始字段) + texts(按可见列头对齐的显示文本)。"""
        return self.page.evaluate(
            """({gridId, limit}) => {
                const g = Ext.getCmp(gridId);
                if (!g) return [];
                const s = g.getStore && g.getStore();
                if (!s) return [];
                const view = g.getView && g.getView();
                const wide = el => el.getBoundingClientRect().width > 1;
                const headers = (g.headerCt ? g.headerCt.getGridColumns() : [])
                    .filter(c => !c.hidden).map(c => c.text);
                const out = [];
                for (let i = 0; i < Math.min(s.getCount(), limit); i++) {
                    const rec = s.getAt(i);
                    const node = view && view.getNode(rec);
                    const tds = node
                        ? Array.from(node.querySelectorAll('td.x-grid-cell')).filter(wide)
                        : [];
                    const texts = {};
                    headers.forEach((h, j) => {
                        texts[h] = tds[j] ? tds[j].innerText.trim() : '';
                    });
                    out.push({data: rec.data || {}, texts});
                }
                return out;
            }""",
            {"gridId": grid_id, "limit": limit},
        )
