from __future__ import annotations

from lib.data_fetching import _TREASURY_PRICE_PROXIES


_INDEX_SYMBOLS = {
    "IXIC",
    "GSPC",
    "DJI",
    "RUT",
    "VIX",
    "NYA",
    "XAX",
    "FTSE",
    "GDAXI",
    "FCHI",
    "N225",
    "HSI",
    "STOXX50E",
    "BVSP",
    "GSPTSE",
    "AXJO",
    "NZ50",
    "KS11",
    "TWII",
    "SSEC",
    "JKSE",
    "KLSE",
    "STI",
    "NSEI",
    "BSESN",
    "TNX",
    "TYX",
    "FVX",
    "IRX",
    "SOX",
    "SPX",
}
_TREASURY_SYMBOLS = set(_TREASURY_PRICE_PROXIES)
_SEMI_SYMBOLS = {"ALAB", "AMD", "ARM", "ASML", "AVGO", "MRVL", "MU", "NVDA", "SNDK", "TSM"}
_SOFTWARE_SYMBOLS = {"CRM", "CRWD", "NOW", "PLTR", "SNOW", "ZS"}
_TECH_SYMBOLS = {"AAPL", "AMZN", "GOOG", "HIMS", "HOOD", "META", "MSFT", "RKLB", "TSLA"}
_ETF_SYMBOLS = {"ARKK", "CPER", "IAU", "IGV", "MAGS", "SMH", "TLT", "USO", "VGT", "XLE"}
_CRYPTO_ADJACENT_SYMBOLS = {"COIN", "CRCL", "GLXY", "HUT", "MSTR"}

_CATEGORY_LABELS = {
    "indexes": "Index",
    "treasuries": "Rates",
    "semis": "Semis",
    "tech": "Tech",
    "software": "Software",
    "etfs": "ETF",
    "crypto": "Crypto",
    "misc": "General",
}

_PREFERRED_STRATEGY_BY_CATEGORY = {
    "indexes": ("ema_9_26", "EMA 9/26 Cross"),
    "treasuries": ("trend_sr_macro_v1", "Trend SR + Macro v1"),
    "semis": ("semis_persist_v1", "Semis Persist v1"),
    "tech": ("ema_crossover", "EMA 5/20 Cross"),
    "software": ("trend_sr_macro_v1", "Trend SR + Macro v1"),
    "etfs": ("ribbon", "Trend-Driven"),
    "crypto": ("cci_trend", "CCI Trend"),
    "misc": ("ribbon", "Trend-Driven"),
}

_STRATEGY_OVERRIDES = {
    "SMH": ("semis_persist_v1", "Semis Persist v1"),
    "SOX": ("semis_persist_v1", "Semis Persist v1"),
}


def ticker_category(ticker: str | None) -> str:
    raw_ticker = (ticker or "").upper()
    if raw_ticker.endswith("-USD"):
        return "crypto"
    raw = raw_ticker.replace("^", "")
    if raw in _TREASURY_SYMBOLS:
        return "treasuries"
    if raw in _INDEX_SYMBOLS or raw_ticker.startswith("^"):
        return "indexes"
    if raw in _SEMI_SYMBOLS:
        return "semis"
    if raw in _SOFTWARE_SYMBOLS:
        return "software"
    if raw in _TECH_SYMBOLS:
        return "tech"
    if raw in _ETF_SYMBOLS:
        return "etfs"
    if raw in _CRYPTO_ADJACENT_SYMBOLS:
        return "crypto"
    return "misc"


def preferred_strategy_for_ticker(ticker: str | None) -> dict[str, str]:
    raw_ticker = (ticker or "").upper()
    raw = raw_ticker.replace("^", "")
    category = ticker_category(raw_ticker)
    strategy_key, strategy_label = _STRATEGY_OVERRIDES.get(
        raw,
        _PREFERRED_STRATEGY_BY_CATEGORY.get(category, _PREFERRED_STRATEGY_BY_CATEGORY["misc"]),
    )
    return {
        "category": category,
        "category_label": _CATEGORY_LABELS.get(category, "General"),
        "strategy_key": strategy_key,
        "strategy_label": strategy_label,
    }
