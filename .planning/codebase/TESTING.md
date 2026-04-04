# Codebase Testing

## Tooling
- Pytest is configured by `pytest.ini`.
- Playwright is used in `tests/test_ui.py`.
- Node-based tests cover `static/chart_support_resistance.js` in `tests/test_chart_sr_js.py`.

## Fixtures
- `tests/conftest.py` provides `app`, `client`, `sample_df`, and `small_df`.
- It sets `TRIEDINGVIEW_USER_DATA_DIR` to a temp directory and patches `routes.watchlist` plus `lib.data_fetching` cache paths.
- It clears `lib.cache` globals between tests.

## Test Coverage Areas
- Indicator math and direction semantics in `tests/test_indicators.py`.
- Trade simulation and summary metrics in `tests/test_backtest.py`.
- Market-data normalization/cache behavior in `tests/test_data_fetching.py`.
- Support/resistance detection and regression fixtures in `tests/test_support_resistance.py` and `tests/test_sr_regression.py`.
- Flask endpoint contracts in `tests/test_routes.py`.
- Optimizer logic and resumable runs in `tests/test_trend_optimizer.py`.
- Template/script contract checks in `tests/test_chart_template_contract.py`.
- End-to-end UI behavior in `tests/test_ui.py`.

## Known Test Gaps/Risks
- `tests/test_ui.py` expects title `"Trading App"` while `templates/index.html` sets `"TriedingView"`.
- `scipy` and `playwright` are used but missing from `requirements.txt`.
- There is no visible CI workflow or coverage threshold in this snapshot.
- Most frontend JS remains covered indirectly through Playwright rather than unit tests.

## Useful Commands
- `pytest`
- `pytest tests/test_backtest.py`
- `pytest -m ui`
