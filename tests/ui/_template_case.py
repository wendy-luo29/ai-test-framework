"""<模块> UI 用例模板。

用法：复制本文件并重命名为 test_<业务>.py（必须 test_ 开头，pytest 才会收集），
把 TemplatePage 换成实际 Page Object，删掉用不到的分区。

fixture 两种写法，二选一：
1) 本文件内用通用 logged_in_page 自己构造 Page Object（见下方 template_page）
2) 复用 tests/ui/conftest.py 已封装好的 fixture（如 manual_order_page）
"""

from __future__ import annotations

import pytest

from pages._template_page import TemplatePage

pytestmark = [pytest.mark.ui, pytest.mark.smoke]


@pytest.fixture
def template_page(logged_in_page):
    """本模块的页面 fixture：登录后进入目标页面。"""
    page = TemplatePage(logged_in_page)
    page.open_page()
    return page


class TestTemplate:
    """同一页面的一组用例放同一个 class，便于共用 fixture 与前置步骤。"""

    def test_search_shows_result(self, template_page):
        """正向：查询命中。"""
        template_page.search("TODO关键字")
        template_page.expect_row_value("TODO列名", "TODO期望值")

    @pytest.mark.parametrize(
        "keyword, expect_empty",
        [
            ("TODO合法关键字", False),
            ("TODO不存在的关键字", True),
        ],
    )
    def test_search_parametrized(self, template_page, keyword, expect_empty):
        """参数化：同一断言覆盖多组输入。"""
        template_page.search(keyword)
        has_rows = bool(template_page.first_row())
        assert has_rows != expect_empty, f"关键字「{keyword}」结果与预期不符"
