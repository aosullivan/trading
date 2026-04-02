import io
from unittest.mock import patch

from lib.data_fetching import _fetch_treasury_yield_history, _quote_from_frame


def test_fetch_treasury_yield_history_supports_observation_date_column():
    csv_payload = (
        "observation_date,DGS1\n"
        "2026-03-30,3.71\n"
        "2026-03-31,3.68\n"
    )

    with (
        patch("lib.data_fetching._cache_get", return_value=None),
        patch("lib.data_fetching._cache_set"),
        patch(
            "lib.data_fetching.urllib.request.urlopen",
            return_value=io.BytesIO(csv_payload.encode("utf-8")),
        ),
    ):
        df = _fetch_treasury_yield_history("UST1Y")

    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-03-30", "2026-03-31"]
    assert _quote_from_frame("UST1Y", df) == {
        "ticker": "UST1Y",
        "last": 3.68,
        "chg": -0.03,
        "chg_pct": -0.81,
    }
