import json
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("TRIEDINGVIEW_USER_DATA_DIR", tempfile.mkdtemp())

from app import app as flask_app


@pytest.fixture
def app(tmp_path):
    """Create a Flask test app with an isolated watchlist file."""
    wl_file = tmp_path / "watchlist.json"
    wl_file.write_text(json.dumps(["AAPL", "TSLA"]))
    flask_app.config["TESTING"] = True
    # Patch the watchlist file path
    import routes.watchlist as watchlist_module
    import lib.data_fetching as data_fetching_module
    import lib.cache as cache_module
    original_wl = watchlist_module.WATCHLIST_FILE
    original_trends_cache_dir = watchlist_module._TRENDS_CACHE_DIR
    original_cache_dir = data_fetching_module._DATA_CACHE_DIR
    watchlist_module.WATCHLIST_FILE = str(wl_file)
    watchlist_module._TRENDS_CACHE_DIR = str(tmp_path / "watchlist_trends")
    data_fetching_module._DATA_CACHE_DIR = str(tmp_path / "data_cache")
    os.makedirs(data_fetching_module._DATA_CACHE_DIR, exist_ok=True)
    cache_module._cache.clear()
    cache_module._watchlist_quotes_cache.clear()
    cache_module._watchlist_quote_refreshing.clear()
    cache_module._watchlist_trends_cache.clear()
    cache_module._watchlist_trend_refreshing.clear()
    yield flask_app
    watchlist_module.WATCHLIST_FILE = original_wl
    watchlist_module._TRENDS_CACHE_DIR = original_trends_cache_dir
    data_fetching_module._DATA_CACHE_DIR = original_cache_dir


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def sample_df():
    """Create a sample OHLCV DataFrame for indicator testing."""
    np.random.seed(42)
    n = 300
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n)) * 2
    low = close - np.abs(np.random.randn(n)) * 2
    open_ = close + np.random.randn(n) * 0.5
    volume = np.random.randint(1_000_000, 10_000_000, n)

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture
def small_df():
    """A small DataFrame for edge-case tests."""
    dates = pd.bdate_range("2024-01-01", periods=50)
    np.random.seed(99)
    close = 50 + np.cumsum(np.random.randn(50))
    high = close + 1
    low = close - 1
    open_ = close + 0.5
    volume = np.full(50, 1_000_000)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
