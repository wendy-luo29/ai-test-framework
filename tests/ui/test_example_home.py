import pytest

from pages.home_page import HomePage


@pytest.mark.ui
@pytest.mark.smoke
def test_home_page_heading(page):
    home = HomePage(page)

    home.open("/")
    home.expect_visible(home.heading)
    home.expect_text(home.heading, "Demo App")
    home.expect_text(home.message, "Ready")
