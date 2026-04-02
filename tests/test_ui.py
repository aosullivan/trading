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

    def test_watchlist_header(self, browser_page):
        header = browser_page.locator(".wl-head h2")
        expect(header).to_have_text("Watchlist")

    def test_watchlist_has_items(self, browser_page):
        # Wait for watchlist to load
        browser_page.wait_for_timeout(2000)
        items = browser_page.locator(".wl-row")
        assert items.count() > 0

    def test_add_ticker_input_exists(self, browser_page):
        inp = browser_page.locator("#wl-input")
        expect(inp).to_be_visible()
        expect(inp).to_have_attribute("placeholder", "Add ticker...")


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

    def test_toggle_backtest_panel(self, browser_page):
        btn = browser_page.locator("#bt-btn")
        btn.click()
        panel = browser_page.locator("#bt-panel-wrap")
        expect(panel).to_have_class(re.compile(r"open"))
        # Close it
        close_btn = browser_page.locator(".bt-close")
        close_btn.click()
        expect(panel).not_to_have_class(re.compile(r"open"))

    def test_strategy_select_options(self, browser_page):
        btn = browser_page.locator("#bt-btn")
        btn.click()
        select = browser_page.locator("#strategy-select")
        options = select.locator("option")
        assert options.count() == 11
        # Close panel
        browser_page.locator(".bt-close").click()

    def test_backtest_range_controls(self, browser_page):
        btn = browser_page.locator("#bt-btn")
        btn.click()
        expect(browser_page.locator("#bt-range-track")).to_be_visible()
        expect(browser_page.locator("#bt-range-lo")).to_be_visible()
        expect(browser_page.locator("#bt-range-hi")).to_be_visible()
        browser_page.locator(".bt-close").click()


class TestToolbarControls:
    def test_interval_select(self, browser_page):
        select = browser_page.locator("#interval")
        expect(select).to_be_visible()
        options = select.locator("option")
        assert options.count() == 2

    def test_supertrend_param_inputs(self, browser_page):
        period = browser_page.locator("#period")
        mult = browser_page.locator("#multiplier")
        expect(period).to_be_visible()
        expect(mult).to_be_visible()
        assert period.input_value() == "10"
        assert mult.input_value() == "3"

    def test_load_button(self, browser_page):
        btn = browser_page.locator("#load-btn")
        expect(btn).to_be_visible()
        expect(btn).to_have_text("Load")
