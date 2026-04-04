"""UI tests using Playwright against the live Flask app."""

import json
import re
import subprocess
import time
import signal
import socket
import os
import sys

import pytest
from playwright.sync_api import sync_playwright, expect, Error as PlaywrightError

BASE_URL = "http://127.0.0.1:5050"
pytestmark = pytest.mark.ui


def _wait_for_server(host="127.0.0.1", port=5050, timeout=15):
    """Poll until the server accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Server did not start within {timeout}s")


def _open_backtest_popup(page):
    with page.expect_popup() as popup_info:
        page.locator("#bt-btn").click()
    popup = popup_info.value
    popup.wait_for_load_state("domcontentloaded")
    return popup


@pytest.fixture(scope="module")
def server():
    """Start the Flask dev server for UI tests."""
    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    _wait_for_server()
    yield proc
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser_page(server):
    """Provide a Playwright browser page connected to the running server."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Playwright browser unavailable: {exc}")
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
        # Wait for initial JS to run
        page.wait_for_timeout(3000)
        yield page
        browser.close()


class TestPageLoad:
    def test_title(self, browser_page):
        assert browser_page.title() == "Trading App"

    def test_toolbar_visible(self, browser_page):
        toolbar = browser_page.locator(".toolbar")
        expect(toolbar).to_be_visible()

    def test_ticker_symbol_displayed(self, browser_page):
        sym = browser_page.locator("#tk-sym")
        expect(sym).to_be_visible()
        assert sym.text_content().strip() != ""

    def test_chart_container_exists(self, browser_page):
        chart = browser_page.locator("#chart-container")
        expect(chart).to_be_visible()


class TestWatchlistUI:
    def test_watchlist_panel_visible(self, browser_page):
        wl = browser_page.locator("#wl-panel")
        expect(wl).to_be_visible()

    def test_watchlist_and_trends_tabs_visible(self, browser_page):
        watchlist_tab = browser_page.locator(".wl-view-tab", has_text="Watchlist")
        trends_tab = browser_page.locator(".wl-view-tab", has_text="Trends")
        expect(watchlist_tab).to_be_visible()
        expect(watchlist_tab).to_have_class(re.compile(r"\bactive\b"))
        expect(trends_tab).to_be_visible()

    def test_watchlist_has_items(self, browser_page):
        # Wait for watchlist to load
        browser_page.wait_for_timeout(2000)
        items = browser_page.locator(".wl-row")
        assert items.count() > 0

    def test_treasury_tab_visible(self, browser_page):
        tab = browser_page.locator(".wl-tab", has_text="Treasury")
        expect(tab).to_be_visible()

    def test_add_ticker_input_exists(self, browser_page):
        inp = browser_page.locator("#wl-input")
        expect(inp).to_be_visible()
        expect(inp).to_have_attribute("placeholder", "Add ticker...")

    def test_trends_tab_renders_ranked_rows_and_click_loads_ticker(self, browser_page):
        browser_page.locator(".wl-view-tab", has_text="Trends").click()
        first_row = browser_page.locator(".wl-trend-row").first
        expect(first_row).to_be_visible(timeout=30000)
        expect(first_row.locator(".tf-cell").first).to_be_visible()
        expect(first_row.locator(".tf-flip-date").first).to_be_visible()

        ticker = first_row.locator(".wl-trend-symbol strong").text_content().strip()
        first_row.click()
        expect(browser_page.locator("#ticker")).to_have_value(ticker)

        browser_page.locator(".wl-view-tab", has_text="Watchlist").click()
        expect(browser_page.locator("#wl-input")).to_be_visible()

    def test_watchlist_tab_state_round_trips_through_url(self, browser_page):
        page = browser_page.context.new_page()
        restored_page = browser_page.context.new_page()
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)

            page.locator("#wl-tabs .wl-tab", has_text="Tech").click()
            page.locator(".wl-view-tab", has_text="Trends").click()
            page.locator("#wl-trend-tabs .wl-tab", has_text="Weekly").click()
            page.locator("#wl-toggle").click()

            assert "wlTab=tech" in page.url
            assert "wlView=trends" in page.url
            assert "wlFrame=weekly" in page.url
            assert "wlCollapsed=1" in page.url

            restored_page.goto(page.url, wait_until="domcontentloaded", timeout=15000)
            restored_page.wait_for_timeout(3000)

            expect(restored_page.locator("#wl-panel")).to_have_class(re.compile(r"\bcollapsed\b"))
            expect(restored_page.locator(".wl-view-tab[data-view='trends']")).to_have_class(
                re.compile(r"\bactive\b")
            )
            expect(restored_page.locator("#wl-trend-tabs .wl-tab[data-frame='weekly']")).to_have_class(
                re.compile(r"\bactive\b")
            )

            restored_page.locator("#wl-toggle").click()
            restored_page.locator(".wl-view-tab", has_text="Watchlist").click()
            expect(restored_page.locator("#wl-tabs .wl-tab[data-tab='tech']")).to_have_class(
                re.compile(r"\bactive\b")
            )
        finally:
            restored_page.close()
            page.close()

    def test_selected_ticker_survives_watchlist_trends_switches(self, browser_page):
        page = browser_page.context.new_page()
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)

            page.locator("#ticker").fill("TSLA")
            page.locator("#ticker").press("Enter")
            expect(page.locator("#ticker")).to_have_value("TSLA")

            page.locator("#wl-tabs .wl-tab[data-tab='crypto']").click()
            page.locator(".wl-view-tab[data-view='trends']").click()
            expect(page.locator(".wl-trend-row.active .wl-trend-symbol span")).to_have_text(
                "TSLA", timeout=30000
            )

            page.locator("#wl-tabs .wl-tab[data-tab='crypto']").click()
            page.locator(".wl-view-tab[data-view='watchlist']").click()
            expect(page.locator(".wl-row.active .wl-tk span")).to_have_text("TSLA")
        finally:
            page.close()


class TestOverlayChips:
    def test_overlay_chips_visible(self, browser_page):
        overlays = browser_page.locator(".overlays")
        expect(overlays).to_be_visible()

    def test_supertrend_chip_on_by_default(self, browser_page):
        st_chip = browser_page.locator(".chip").first
        expect(st_chip).to_have_class(re.compile(r"on"))

    def test_toggle_chip(self, browser_page):
        ema_chip = browser_page.locator(".chip", has_text="EMA Cross")
        # Should start off
        expect(ema_chip).not_to_have_class(re.compile(r"\bon\b"))
        ema_chip.click()
        expect(ema_chip).to_have_class(re.compile(r"on"))
        # Toggle back off
        ema_chip.click()
        expect(ema_chip).not_to_have_class(re.compile(r"\bon\b"))


class TestBacktestPanel:
    def test_backtest_button_visible(self, browser_page):
        btn = browser_page.locator("#bt-btn")
        expect(btn).to_be_visible()

    def test_backtest_panel_hidden_initially(self, browser_page):
        panel = browser_page.locator("#bt-panel-wrap")
        expect(panel).not_to_have_class(re.compile(r"open"))

    def test_backtest_button_opens_new_tab_report(self, browser_page):
        popup = _open_backtest_popup(browser_page)
        try:
            assert "/backtest" in popup.url
            expect(popup.locator("#bt-panel-wrap")).to_be_visible()
            expect(popup.locator("#bt-symbol-label")).to_contain_text("TSLA", timeout=20000)
        finally:
            popup.close()

    def test_strategy_select_options(self, browser_page):
        popup = _open_backtest_popup(browser_page)
        try:
            select = popup.locator("#strategy-select")
            options = select.locator("option")
            assert options.count() == 16
            assert options.first.get_attribute("value") == "ribbon"
            assert options.first.text_content().strip() == "Trend-Driven"
            assert options.nth(1).get_attribute("value") == "cb50"
            assert options.nth(1).text_content().strip() == "Channel Breakout 50"
        finally:
            popup.close()

    def test_backtest_range_controls(self, browser_page):
        popup = _open_backtest_popup(browser_page)
        try:
            expect(popup.locator("#bt-range-track")).to_be_visible()
            expect(popup.locator("#bt-range-lo")).to_be_visible()
            expect(popup.locator("#bt-range-hi")).to_be_visible()
        finally:
            popup.close()


class TestToolbarControls:
    def test_interval_select(self, browser_page):
        select = browser_page.locator("#interval")
        expect(select).to_be_visible()
        options = select.locator("option")
        assert options.count() == 3

    def test_supertrend_param_inputs(self, browser_page):
        period = browser_page.locator("#period")
        mult = browser_page.locator("#multiplier")
        expect(period).to_be_visible()
        expect(mult).to_be_visible()
        assert period.input_value() == "10"
        assert mult.input_value() == "3"

    def test_load_and_report_buttons_removed(self, browser_page):
        assert browser_page.locator("#load-btn").count() == 0
        assert browser_page.locator("a[href='/report']").count() == 0

    def test_financials_button_visible(self, browser_page):
        btn = browser_page.locator("#financials-btn")
        expect(btn).to_be_visible()
        expect(btn).to_have_text("Financials")

    def test_financials_modal_opens(self, browser_page):
        btn = browser_page.locator("#financials-btn")
        btn.click()
        modal = browser_page.locator("#financials-modal")
        expect(modal).to_have_class(re.compile(r"\bopen\b"))
        expect(browser_page.locator("#financials-title")).to_contain_text("TSLA")
        browser_page.locator(".fin-close").click()
        expect(modal).not_to_have_class(re.compile(r"\bopen\b"))


class TestTrendFlipPulse:
    def test_trend_flip_pulse_opens(self, browser_page):
        st_chip = browser_page.locator(".chip", has_text="Supertrend")
        if "on" not in (st_chip.get_attribute("class") or ""):
            st_chip.click()

        btn = browser_page.locator("#trend-flip-aggregate-btn")
        expect(btn).to_be_visible()
        expect(btn).to_contain_text("Pulse")

        btn.click()
        pop = browser_page.locator("#trend-flip-aggregate-popover")
        expect(pop).to_have_class(re.compile(r"\bopen\b"))
        expect(pop).to_contain_text("Signal Pulse")
        expect(pop).to_contain_text("Daily")
        expect(pop).to_contain_text("Weekly")
