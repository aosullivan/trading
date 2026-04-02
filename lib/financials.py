def _compact_number(value) -> str:
    value = float(value)
    abs_value = abs(value)
    suffixes = [
        (1_000_000_000_000, "T"),
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    ]
    for divisor, suffix in suffixes:
        if abs_value >= divisor:
            return f"{value / divisor:.2f}{suffix}"
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _money_display(value, currency: str | None = None) -> str:
    prefix = "$" if not currency or currency.upper() == "USD" else f"{currency.upper()} "
    return f"{prefix}{_compact_number(value)}"


def _multiple_display(value) -> str:
    return f"{float(value):.2f}x"


def _percent_display(value) -> str:
    return f"{float(value) * 100:.2f}%"


def _plain_number_display(value) -> str:
    value = float(value)
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _metric(label: str, value, formatter):
    if value is None or value == "":
        return None
    try:
        return {"label": label, "value": value, "display": formatter(value)}
    except Exception:
        return None


def _metric_list(*items):
    return [item for item in items if item is not None]


def _build_financials_payload(display_ticker: str, normalized_ticker: str, info: dict) -> dict:
    ticker_name = info.get("shortName") or info.get("longName") or display_ticker
    currency = info.get("currency") or "USD"
    quote_type = str(info.get("quoteType") or "").lower()

    valuation = _metric_list(
        _metric("Trailing P/E", info.get("trailingPE"), _multiple_display),
        _metric("Forward P/E", info.get("forwardPE"), _multiple_display),
        _metric("PEG Ratio", info.get("pegRatio"), _plain_number_display),
        _metric("Price/Sales", info.get("priceToSalesTrailing12Months"), _multiple_display),
        _metric("EV/EBITDA", info.get("enterpriseToEbitda"), _multiple_display),
    )
    scale = _metric_list(
        _metric("Market Cap", info.get("marketCap"), lambda v: _money_display(v, currency)),
        _metric("Enterprise Value", info.get("enterpriseValue"), lambda v: _money_display(v, currency)),
        _metric("Revenue", info.get("totalRevenue"), lambda v: _money_display(v, currency)),
        _metric("Operating Cash Flow", info.get("operatingCashflow"), lambda v: _money_display(v, currency)),
        _metric("Free Cash Flow", info.get("freeCashflow"), lambda v: _money_display(v, currency)),
    )
    quality = _metric_list(
        _metric("Gross Margin", info.get("grossMargins"), _percent_display),
        _metric("Operating Margin", info.get("operatingMargins"), _percent_display),
        _metric("Profit Margin", info.get("profitMargins"), _percent_display),
        _metric("ROE", info.get("returnOnEquity"), _percent_display),
        _metric("ROA", info.get("returnOnAssets"), _percent_display),
    )
    balance = _metric_list(
        _metric("Revenue Growth", info.get("revenueGrowth"), _percent_display),
        _metric("Earnings Growth", info.get("earningsGrowth"), _percent_display),
        _metric("Current Ratio", info.get("currentRatio"), _plain_number_display),
        _metric("Quick Ratio", info.get("quickRatio"), _plain_number_display),
        _metric("Debt/Equity", info.get("debtToEquity"), _plain_number_display),
        _metric("Beta", info.get("beta"), _plain_number_display),
    )

    sections = [
        {"title": "Valuation", "metrics": valuation},
        {"title": "Scale", "metrics": scale},
        {"title": "Quality", "metrics": quality},
        {"title": "Growth & Balance Sheet", "metrics": balance},
    ]
    sections = [section for section in sections if section["metrics"]]

    company_bits = [bit for bit in [info.get("sector"), info.get("industry")] if bit]
    overview = {
        "ticker": display_ticker,
        "yf_ticker": normalized_ticker,
        "ticker_name": ticker_name,
        "currency": currency,
        "quote_type": quote_type or None,
        "company_line": " . ".join(company_bits) if company_bits else None,
        "website": info.get("website") or None,
        "summary": info.get("longBusinessSummary") or None,
    }

    has_financial_content = bool(sections)
    available = has_financial_content or bool(overview["company_line"] or overview["summary"])
    message = None
    if not available:
        asset_type = quote_type or "this instrument"
        message = f"Detailed company financials are not available for {asset_type}."

    return {
        "available": available,
        "message": message,
        "overview": overview,
        "sections": sections,
    }
