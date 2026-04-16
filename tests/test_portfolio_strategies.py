import pandas as pd

from lib.portfolio_strategies import (
    compute_monthly_breadth_guard_directions,
    compute_monthly_breadth_guard_ladder_directions,
)


def _monthly_frame(values):
    index = pd.date_range("2023-01-31", periods=len(values), freq="BME")
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Volume": [0] * len(values),
        },
        index=index,
    )


def test_monthly_breadth_guard_waits_for_confirmation_and_selects_top_two():
    ticker_data = {
        "AAPL": _monthly_frame([100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 124, 126]),
        "MSFT": _monthly_frame([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113]),
        "NVDA": _monthly_frame([100, 100.5, 101, 101.5, 102, 102.5, 103, 103.5, 104, 104.5, 105, 105.5, 106, 106.5]),
        "TSLA": _monthly_frame([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87]),
    }

    directions = compute_monthly_breadth_guard_directions(ticker_data)

    transition_date = ticker_data["AAPL"].index[9]
    confirmed_date = ticker_data["AAPL"].index[10]
    final_date = ticker_data["AAPL"].index[-1]

    assert directions["AAPL"].loc[transition_date] == -1
    assert directions["AAPL"].loc[confirmed_date] == 1
    assert directions["MSFT"].loc[final_date] == 1
    assert directions["NVDA"].loc[final_date] == -1
    assert directions["TSLA"].loc[final_date] == -1


def test_monthly_breadth_guard_exits_after_two_confirmed_breakdown_months():
    ticker_data = {
        "AAPL": _monthly_frame([100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 90, 84]),
        "MSFT": _monthly_frame([100, 101, 103, 105, 107, 109, 111, 113, 115, 117, 119, 121, 89, 83]),
        "NVDA": _monthly_frame([100, 103, 106, 109, 112, 115, 118, 121, 124, 127, 130, 133, 95, 82]),
    }

    directions = compute_monthly_breadth_guard_directions(ticker_data)

    pre_break_month = ticker_data["AAPL"].index[-3]
    second_break_month = ticker_data["AAPL"].index[-1]

    assert max(directions[ticker].loc[pre_break_month] for ticker in ticker_data) == 1
    assert all(directions[ticker].loc[second_break_month] == -1 for ticker in ticker_data)


def test_monthly_breadth_guard_ladder_reenters_after_deep_drawdown_before_full_reclaim():
    ticker_data = {
        "AAPL": _monthly_frame([100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 100, 90, 95, 97]),
        "MSFT": _monthly_frame([100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 96, 88, 93, 94]),
        "NVDA": _monthly_frame([100, 106, 112, 118, 124, 130, 136, 142, 148, 154, 102, 89, 94, 98]),
        "TSLA": _monthly_frame([100, 103, 106, 109, 112, 115, 118, 121, 124, 127, 90, 85, 84, 83]),
    }

    guard = compute_monthly_breadth_guard_directions(ticker_data)
    ladder = compute_monthly_breadth_guard_ladder_directions(ticker_data)

    rebound_month = ticker_data["AAPL"].index[12]

    assert all(guard[ticker].loc[rebound_month] == -1 for ticker in ticker_data)
    assert sum(ladder[ticker].loc[rebound_month] == 1 for ticker in ticker_data) >= 1


def test_monthly_breadth_guard_ladder_scales_back_in_on_extreme_drawdowns():
    ticker_data = {
        "AAPL": _monthly_frame([100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 70, 74, 78, 84]),
        "MSFT": _monthly_frame([100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 68, 72, 76, 82]),
        "NVDA": _monthly_frame([100, 106, 112, 118, 124, 130, 136, 142, 148, 154, 72, 75, 80, 88]),
        "GOOG": _monthly_frame([100, 103, 106, 109, 112, 115, 118, 121, 124, 127, 65, 70, 74, 78]),
        "TSLA": _monthly_frame([100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 60, 62, 61, 60]),
    }

    ladder = compute_monthly_breadth_guard_ladder_directions(ticker_data)

    deep_rebound_month = ticker_data["AAPL"].index[12]

    assert sum(ladder[ticker].loc[deep_rebound_month] == 1 for ticker in ticker_data) >= 3
