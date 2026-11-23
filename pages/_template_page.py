"""<页面名> — <一句话职责>。

用法：复制本文件，重命名为 pages/<业务>_page.py，替换所有 TODO 占位。

ExtJS 后台定位约定（0102 手工订单已验证）：
- 表单字段优先用 name 属性：input[name='main.xxx']（ExtJS 生成的 id 不稳定）
- 下拉框交给 BasePage：select_combo（本地选项）/ select_remote_combo（远程搜索）
- 工具栏按钮一律带 :visible（页面上常存在同名的隐藏按钮）
- 弹窗确认交给 BasePage.click_confirm("是")
- 表格列值用 ExtJS store + view.getNode 读取（隐藏列不渲染 td，直接按 DOM 索引会错位）
"""

from __future__ import annotations

from playwright.sync_api import expect

from pages.base_page import BasePage


class TemplatePage(BasePage):
    # ── 选择器（集中管理，便于统一维护）──────────────────
    BUSINESS_TAB = "#tab-1029"
    MENU_ENTRY = "span.x-tree-node-text:has-text('TODO菜单名')"

    BTN_SEARCH = "a.x-btn:visible:has-text('查询')"
    BTN_NEW = "a.x-btn:visible:has-text('新建')"
    BTN_SAVE = "a.x-btn:visible:has-text('保存')"

    F_KEYWORD = "input[name='keywords']"

    # 列表主键字段（用于定位目标 grid 并取第一行）
    LIST_KEY_FIELD = "TODO主键字段名"

    # ── 导航 ─────────────────────────────────────────────
    def open_page(self) -> None:
        """从首页进入本页面（已登录状态）。"""
        self.page.click(self.BUSINESS_TAB)
        self.page.wait_for_timeout(1500)
        self.page.locator(self.MENU_ENTRY).first.click()
        self.page.wait_for_timeout(2500)
        self.wait_overlay()
        expect(self.page.locator(self.BTN_SEARCH).first).to_be_visible()

    # ── 操作 ─────────────────────────────────────────────
    def search(self, keyword: str) -> None:
        self.fill(self.F_KEYWORD, keyword)
        self.page.locator(self.BTN_SEARCH).first.click()
        self.wait_overlay()

    def save(self) -> bool:
        """点保存并确认弹窗。返回是否确认成功。"""
        self.page.locator(self.BTN_SAVE).first.click()
        self.page.wait_for_timeout(1000)
        ok = self.click_confirm("是")
        self.wait_overlay()
        self.page.wait_for_timeout(2000)
        return ok

    # ── 读取 / 断言 ───────────────────────────────────────
    def first_row(self) -> dict:
        """读取表格第一行，返回 {列名: 单元格文本}。"""
        return self.page.evaluate(
            """(keyField) => {
                const wide = el => el.getBoundingClientRect().width > 1;
                const grids = Ext.ComponentQuery.query('gridpanel');
                for (const g of grids) {
                    if (g.up('window')) continue;
                    const s = g.getStore && g.getStore();
                    if (!s || !s.getCount()) continue;
                    const r = s.getAt(0);
                    if (r.get(keyField) === undefined) continue;
                    const view = g.getView && g.getView();
                    const rowEl = view && view.getNode(r);
                    if (!rowEl) continue;
                    let box = rowEl;
                    while (box && !box.querySelector('.x-column-header')) {
                        box = box.parentElement;
                    }
                    if (!box) continue;
                    const headers = Array.from(box.querySelectorAll('.x-column-header'))
                        .filter(wide).map(h => h.innerText.trim());
                    const tds = Array.from(rowEl.querySelectorAll('td.x-grid-cell')).filter(wide);
                    const obj = {};
                    headers.forEach((name, i) => {
                        obj[name] = tds[i] ? tds[i].innerText.trim() : '';
                    });
                    return obj;
                }
                return {};
            }""",
            self.LIST_KEY_FIELD,
        )

    def expect_row_value(self, column: str, expected: str) -> None:
        row = self.first_row()
        actual = row.get(column)
        assert actual == expected, f"列「{column}」期望「{expected}」，实际「{actual}」，行：{row}"
