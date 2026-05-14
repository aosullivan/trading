from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Iterable

from lib.paths import get_resource_path, get_user_data_path
from lib.strategy_preferences import preferred_strategy_for_ticker


POSITIONS_FILE = get_user_data_path("positions.json")
POSITIONS_CACHE_FILE = get_user_data_path("positions_cache.json")
ACCOUNTS_FILE = get_user_data_path("accounts.json")
POSITIONS_EXPORT_FILE = get_resource_path("posn.html")
QUOTEABLE_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.^-]*$")
CASH_SYMBOLS = {"FDRXX", "SPAXX", "VMFXX"}
OPTION_SYMBOL_RE = re.compile(r"^([A-Z]{1,6})\d{6}[CP]\d{8}$")
POSITION_CATEGORY_LABELS = {
    "cash": "Cash & Equivalents",
    "indexes": "Indexes",
    "treasuries": "Rates",
    "semis": "Semiconductor Stocks",
    "tech": "Tech Stocks",
    "software": "Software",
    "etfs": "ETFs",
    "crypto": "Crypto & Crypto Adjacent",
    "misc": "Other Holdings",
}

RETIREMENT_ACCOUNT_KEYWORDS = (
    "IRA",
    "401K",
    "401(K)",
    "ROTH",
    "ROLLOVER",
    "BROKERAGELINK",
    "PENSION",
    "SIPP",
    "HSA",
)

STRATEGIC_SLEEVE_LABELS = {
    "cash": "Cash",
    "fixed_income": "Fixed Income (<10y, high quality)",
    "gold": "Gold",
    "trend": "Trend / Managed Futures",
    "commodities": "Commodities & Energy",
    "crypto": "Crypto",
    "us_equity": "US Equity",
    "non_us_developed": "Non-US Developed Equity",
    "emerging_markets": "Emerging Markets Equity",
    "pending": "Pending Activity",
}

STRATEGIC_SLEEVE_ORDER = [
    "cash",
    "gold",
    "trend",
    "commodities",
    "crypto",
    "us_equity",
    "non_us_developed",
    "emerging_markets",
    "pending",
]

SLEEVE_BY_SYMBOL = {
    "SPAXX": "cash",
    "VMFXX": "cash",
    "LCAS": "cash",
    "SGOV": "fixed_income",
    "BIL": "fixed_income",
    "BSV": "fixed_income",
    "VGSH": "fixed_income",
    "IAU": "gold",
    "GLD": "gold",
    "AHLT": "trend",
    "KMLM": "trend",
    "DBMF": "trend",
    "COMT": "commodities",
    "CPER": "commodities",
    "XLE": "commodities",
    "URA": "commodities",
    "PDBC": "commodities",
    "DBC": "commodities",
    "FBTC": "crypto",
    "IBIT": "crypto",
    "KBEV": "non_us_developed",
    "VXUS": "non_us_developed",
    "IXUS": "non_us_developed",
    "EFA": "non_us_developed",
    "LEMO": "emerging_markets",
    "VWO": "emerging_markets",
    "IEMG": "emerging_markets",
    "TSM": "emerging_markets",
}

SCENARIO_1_TARGETS = {
    "cash": 5.0,
    "gold": 4.0,
    "trend": 2.0,
    "commodities": 3.0,
    "crypto": 7.0,
    "us_equity": 70.0,
    "non_us_developed": 5.0,
    "emerging_markets": 3.0,
}

SCENARIO_2_TARGETS = {
    "cash": 8.0,
    "gold": 6.0,
    "trend": 3.0,
    "commodities": 5.0,
    "crypto": 6.0,
    "us_equity": 62.0,
    "non_us_developed": 6.0,
    "emerging_markets": 3.0,
}

SCENARIO_3_TARGETS = {
    "cash": 12.0,
    "gold": 10.0,
    "trend": 12.0,
    "commodities": 10.0,
    "crypto": 3.0,
    "us_equity": 25.0,
    "non_us_developed": 10.0,
    "emerging_markets": 3.0,
}


def _clean_number(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_first_number(*values) -> float | None:
    for value in values:
        number = _clean_number(value)
        if number is not None:
            return number
    return None


def _clean_money(value: str) -> float | None:
    if not value:
        return None
    match = re.search(r"([+-]?\$[\d,]+(?:\.\d+)?)", value)
    if not match:
        return None
    raw = match.group(1).replace("$", "").replace(",", "")
    return _clean_number(raw)


def _clean_percent(value: str) -> float | None:
    if not value:
        return None
    match = re.search(r"([+-]?[\d,]+(?:\.\d+)?)%", value)
    if not match:
        return None
    return _clean_number(match.group(1).replace(",", ""))


def _category_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().upper()
    option_match = OPTION_SYMBOL_RE.match(raw)
    if option_match:
        return option_match.group(1)
    return raw


def _position_category(symbol: str) -> tuple[str, str]:
    raw = (symbol or "").strip().upper()
    if raw in CASH_SYMBOLS:
        return "cash", POSITION_CATEGORY_LABELS["cash"]
    category = preferred_strategy_for_ticker(_category_symbol(raw))["category"]
    return category, POSITION_CATEGORY_LABELS.get(category, "Other Holdings")


def strategic_sleeve(symbol: str, category: str) -> str:
    raw = (symbol or "").strip().upper()
    if raw.startswith("_PENDING"):
        return "pending"
    if raw in SLEEVE_BY_SYMBOL:
        return SLEEVE_BY_SYMBOL[raw]
    if category == "cash":
        return "cash"
    return "us_equity"


def account_is_retirement(account_name: str) -> bool:
    upper = (account_name or "").strip().upper()
    return any(keyword in upper for keyword in RETIREMENT_ACCOUNT_KEYWORDS)


def _normalize_account_position(row: dict) -> dict:
    return {
        "account": str(row.get("account") or row.get("name") or "").strip(),
        "quantity": _clean_number(row.get("quantity")),
        "current_price": _clean_number(row.get("current_price")),
        "exposure_pct": _clean_number(row.get("exposure_pct")),
        "cost_basis": _clean_number(row.get("cost_basis")),
        "market_value": _clean_number(row.get("market_value")),
        "day_change": _clean_number(row.get("day_change")),
        "day_change_pct": _clean_number(row.get("day_change_pct")),
        "unrealized_gain_loss": _clean_first_number(
            row.get("unrealized_gain_loss"),
            row.get("unrealized_pnl"),
        ),
        "unrealized_gain_loss_pct": _clean_number(
            row.get("unrealized_gain_loss_pct")
        ),
        "realized_gain_loss": _clean_number(row.get("realized_gain_loss")),
    }


def _extract_yahoo_summary(html: str) -> dict:
    fields = {
        "currentMarketValue": "market_value",
        "dailyGain": "day_change",
        "totalGain": "unrealized_gain_loss",
    }
    summary: dict[str, float] = {}
    for tag_match in re.finditer(r"<fin-streamer\b[^>]*>", html):
        tag = tag_match.group(0)
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        if attrs.get("data-symbol") != "all":
            continue
        key = fields.get(attrs.get("data-field"))
        if not key:
            continue
        value = _clean_number(attrs.get("data-value"))
        if value is not None:
            summary[key] = value
    return summary


def _normalize_position(row: dict) -> dict:
    symbol = str(row.get("symbol") or "").strip()
    category, category_label = _position_category(symbol)
    accounts = row.get("accounts")
    if not isinstance(accounts, list):
        accounts = []
    accounts = [str(account).strip() for account in accounts if str(account).strip()]
    sleeve = strategic_sleeve(symbol, category)
    retirement_accounts = [a for a in accounts if account_is_retirement(a)]
    taxable_accounts = [a for a in accounts if not account_is_retirement(a)]
    if retirement_accounts and taxable_accounts:
        account_type = "mixed"
    elif retirement_accounts:
        account_type = "retirement"
    elif taxable_accounts:
        account_type = "taxable"
    else:
        account_type = "unknown"
    normalized = {
        "symbol": symbol,
        "name": str(row.get("name") or symbol).strip(),
        "account": str(row.get("account") or "").strip(),
        "accounts": accounts,
        "quantity": _clean_number(row.get("quantity")),
        "current_price": _clean_number(row.get("current_price")),
        "exposure_pct": _clean_number(row.get("exposure_pct")),
        "cost_basis": _clean_number(row.get("cost_basis")),
        "market_value": _clean_number(row.get("market_value")) or 0.0,
        "day_change": _clean_number(row.get("day_change")),
        "day_change_pct": _clean_number(row.get("day_change_pct")),
        "unrealized_gain_loss": _clean_first_number(
            row.get("unrealized_gain_loss"),
            row.get("unrealized_pnl"),
        ),
        "unrealized_gain_loss_pct": _clean_number(
            row.get("unrealized_gain_loss_pct")
        ),
        "realized_gain_loss": _clean_number(row.get("realized_gain_loss")),
        "stop_loss_exit_trigger": _clean_number(row.get("stop_loss_exit_trigger")),
        "category": str(row.get("category") or category).strip() or category,
        "category_label": str(row.get("category_label") or category_label).strip()
        or category_label,
        "sleeve": str(row.get("sleeve") or sleeve).strip() or sleeve,
        "sleeve_label": STRATEGIC_SLEEVE_LABELS.get(sleeve, "Other"),
        "account_type": account_type,
    }
    if isinstance(row.get("_summary"), dict):
        normalized["_summary"] = {
            key: _clean_number(value)
            for key, value in row["_summary"].items()
            if _clean_number(value) is not None
        }
    account_positions = row.get("account_positions")
    if isinstance(account_positions, list):
        normalized["account_positions"] = [
            account_position
            for account_position in (
                _normalize_account_position(account_position)
                for account_position in account_positions
                if isinstance(account_position, dict)
            )
            if account_position["account"]
        ]
    return normalized


class _YahooHoldingsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[dict]] = []
        self._table_depth = 0
        self._in_target_table = False
        self._in_row = False
        self._in_cell = False
        self._current_row: list[dict] = []
        self._current_cell: dict | None = None
        self._span_class_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("data-testid") == "table-container":
            self._in_target_table = True
            self._table_depth = 1
            return
        if self._in_target_table and tag == "table":
            self._table_depth += 1
        if not self._in_target_table:
            return
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = {"text": [], "symbol": [], "name": []}
        elif self._in_cell and tag == "span":
            self._span_class_stack.append(attrs_dict.get("class", ""))

    def handle_data(self, data):
        if not self._in_cell or self._current_cell is None:
            return
        text = data.strip()
        if not text:
            return
        self._current_cell["text"].append(text)
        active_class = self._span_class_stack[-1] if self._span_class_stack else ""
        class_parts = set(active_class.split())
        if "symbol" in class_parts:
            self._current_cell["symbol"].append(text)
        if "longName" in class_parts:
            self._current_cell["name"].append(text)

    def handle_endtag(self, tag):
        if not self._in_target_table:
            return
        if self._in_cell and tag == "span" and self._span_class_stack:
            self._span_class_stack.pop()
        elif self._in_cell and tag in {"td", "th"}:
            assert self._current_cell is not None
            self._current_cell["text"] = " ".join(self._current_cell["text"])
            self._current_cell["symbol"] = " ".join(self._current_cell["symbol"])
            self._current_cell["name"] = " ".join(self._current_cell["name"])
            self._current_row.append(self._current_cell)
            self._current_cell = None
            self._in_cell = False
            self._span_class_stack = []
        elif self._in_row and tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []
            self._in_row = False
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_target_table = False


class _YahooAccountTickerParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.symbol_accounts: dict[str, set[str]] = {}
        self._current_account: str | None = None
        self._in_account_link = False
        self._account_text: list[str] = []
        self._in_ticker_link = False
        self._in_symbol = False
        self._ticker_symbol: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_parts = set(attrs_dict.get("class", "").split())
        data_testid = attrs_dict.get("data-testid")
        if tag == "a" and data_testid == "portfolio-row-container":
            self._in_account_link = True
            self._account_text = []
            return
        if (
            tag == "a"
            and data_testid == "ticker-list-item"
            and self._current_account
        ):
            self._in_ticker_link = True
            self._ticker_symbol = []
            return
        if self._in_ticker_link and tag == "span" and "symbol" in class_parts:
            self._in_symbol = True

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_account_link:
            self._account_text.append(text)
        if self._in_symbol:
            self._ticker_symbol.append(text)

    def handle_endtag(self, tag):
        if self._in_account_link and tag == "a":
            account = " ".join(self._account_text).strip()
            self._current_account = account if " : " in account else None
            self._in_account_link = False
            self._account_text = []
            return
        if self._in_symbol and tag == "span":
            self._in_symbol = False
            return
        if self._in_ticker_link and tag == "a":
            symbol = " ".join(self._ticker_symbol).strip()
            if symbol and self._current_account:
                self.symbol_accounts.setdefault(symbol, set()).add(self._current_account)
            self._in_ticker_link = False
            self._in_symbol = False
            self._ticker_symbol = []


def _extract_yahoo_account_membership(html: str) -> dict[str, list[str]]:
    parser = _YahooAccountTickerParser()
    parser.feed(html)
    return {
        symbol: sorted(accounts)
        for symbol, accounts in parser.symbol_accounts.items()
        if accounts
    }


def load_yahoo_positions_export(path: str | None = None) -> list[dict]:
    path = path or POSITIONS_EXPORT_FILE
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            html = f.read()
    except FileNotFoundError:
        return []
    parser = _YahooHoldingsTableParser()
    parser.feed(html)
    summary = _extract_yahoo_summary(html)
    account_membership = _extract_yahoo_account_membership(html)
    rows: list[dict] = []
    for raw_row in parser.rows:
        if len(raw_row) < 7 or raw_row[0]["text"] == "Symbol":
            continue
        symbol = raw_row[0]["symbol"] or raw_row[0]["text"]
        name = raw_row[0]["name"] or symbol
        if name == "--":
            name = symbol
        accounts = account_membership.get(symbol)
        rows.append(_normalize_position({
            "symbol": symbol,
            "name": name,
            "account": ", ".join(accounts) if accounts else "Yahoo Finance",
            "accounts": accounts,
            "exposure_pct": _clean_percent(raw_row[1]["text"]),
            "cost_basis": _clean_money(raw_row[2]["text"]),
            "market_value": _clean_money(raw_row[3]["text"]),
            "day_change": _clean_money(raw_row[4]["text"]),
            "day_change_pct": _clean_percent(raw_row[4]["text"]),
            "unrealized_gain_loss": _clean_money(raw_row[5]["text"]),
            "unrealized_gain_loss_pct": _clean_percent(raw_row[5]["text"]),
            "realized_gain_loss": _clean_money(raw_row[6]["text"]),
        }))
    rows = [row for row in rows if row["symbol"]]
    if rows and summary:
        rows[0]["_summary"] = summary
    return rows


def _load_json_file(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _load_position_rows(path: str) -> list[dict]:
    payload = _load_json_file(path)
    if not isinstance(payload, list):
        return []
    rows = [_normalize_position(row) for row in payload if isinstance(row, dict)]
    return [row for row in rows if row["symbol"]]


def _load_account_names() -> dict[str, str]:
    payload = _load_json_file(ACCOUNTS_FILE)
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(accounts, list):
        return {}
    names: dict[str, str] = {}
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_id = str(account.get("id") or "").strip()
        account_name = str(account.get("name") or account_id).strip()
        if account_id and account_name:
            names[account_id] = account_name
    return names


def _load_cached_position_rows() -> list[dict]:
    payload = _load_json_file(POSITIONS_CACHE_FILE)
    if not isinstance(payload, dict):
        return []
    account_names = _load_account_names()
    rows: list[dict] = []
    for account_id, account_payload in payload.items():
        if not isinstance(account_payload, dict):
            continue
        positions = account_payload.get("positions")
        if not isinstance(positions, list):
            continue
        for row in positions:
            if not isinstance(row, dict):
                continue
            cached_row = dict(row)
            cached_account_id = str(cached_row.get("account_id") or account_id).strip()
            cached_row.setdefault(
                "account",
                account_names.get(cached_account_id) or cached_account_id,
            )
            rows.append(_normalize_position(cached_row))
    return [row for row in rows if row["symbol"]]


def load_imported_positions() -> list[dict]:
    rows = _load_position_rows(POSITIONS_FILE)
    if rows:
        return rows
    rows = load_yahoo_positions_export()
    if rows:
        return rows
    return _load_cached_position_rows()


def summarize_positions(positions: Iterable[dict]) -> dict:
    rows = list(positions)
    override = next((row.get("_summary") for row in rows if row.get("_summary")), {})
    cost_basis = sum(row["cost_basis"] or 0 for row in rows)
    market_value = sum(row["market_value"] or 0 for row in rows)
    day_change = sum(row["day_change"] or 0 for row in rows)
    unrealized = sum(row["unrealized_gain_loss"] or 0 for row in rows)
    accounts = set()
    for row in rows:
        row_accounts = row.get("accounts") or []
        if row_accounts:
            accounts.update(row_accounts)
        elif row["account"]:
            accounts.add(row["account"])
    symbols = {row["symbol"] for row in rows if row["symbol"]}
    return {
        "cost_basis": cost_basis,
        "market_value": override.get("market_value", market_value),
        "day_change": override.get("day_change", day_change),
        "unrealized_gain_loss": override.get("unrealized_gain_loss", unrealized),
        "account_count": len(accounts),
        "symbol_count": len(symbols),
        "position_count": len(rows),
    }


def _market_value_for_account(row: dict, account: str) -> float:
    children = row.get("account_positions") or []
    for child in children:
        if str(child.get("account") or "").strip() == account:
            value = child.get("market_value")
            if isinstance(value, (int, float)):
                return float(value)
    accounts = row.get("accounts") or ([row["account"]] if row.get("account") else [])
    if accounts:
        total_mv = row.get("market_value") or 0
        return float(total_mv) / len(accounts) if account in accounts else 0.0
    return 0.0


def retirement_split(positions: Iterable[dict]) -> dict:
    retirement_mv = 0.0
    taxable_mv = 0.0
    for row in positions:
        children = row.get("account_positions") or []
        if children:
            for child in children:
                account = str(child.get("account") or "").strip()
                mv = float(child.get("market_value") or 0)
                if account_is_retirement(account):
                    retirement_mv += mv
                else:
                    taxable_mv += mv
        else:
            account = str(row.get("account") or "").strip()
            mv = float(row.get("market_value") or 0)
            if account_is_retirement(account):
                retirement_mv += mv
            else:
                taxable_mv += mv
    total = retirement_mv + taxable_mv
    return {
        "retirement_market_value": retirement_mv,
        "taxable_market_value": taxable_mv,
        "total_market_value": total,
        "retirement_pct": (retirement_mv / total * 100) if total else 0.0,
        "taxable_pct": (taxable_mv / total * 100) if total else 0.0,
    }


def _gap(target: float | None, current_pct: float, total_mv: float) -> tuple[float | None, float | None]:
    if target is None:
        return None, None
    gap_pct = target - current_pct
    return gap_pct, gap_pct / 100 * total_mv


def allocation_plan(positions: Iterable[dict]) -> list[dict]:
    rows = list(positions)
    sleeve_mv: dict[str, float] = {}
    for row in rows:
        sleeve = row.get("sleeve") or strategic_sleeve(row.get("symbol", ""), row.get("category", ""))
        mv = float(row.get("market_value") or 0)
        sleeve_mv[sleeve] = sleeve_mv.get(sleeve, 0.0) + mv
    total_mv = sum(value for sleeve, value in sleeve_mv.items() if sleeve != "pending")
    plan: list[dict] = []
    seen = set()
    for sleeve in STRATEGIC_SLEEVE_ORDER:
        if sleeve == "pending":
            continue
        seen.add(sleeve)
        current_mv = sleeve_mv.get(sleeve, 0.0)
        current_pct = (current_mv / total_mv * 100) if total_mv else 0.0
        s1_target = SCENARIO_1_TARGETS.get(sleeve)
        s2_target = SCENARIO_2_TARGETS.get(sleeve)
        s3_target = SCENARIO_3_TARGETS.get(sleeve)
        s1_gap_pct, s1_gap_dollars = _gap(s1_target, current_pct, total_mv)
        s2_gap_pct, s2_gap_dollars = _gap(s2_target, current_pct, total_mv)
        s3_gap_pct, s3_gap_dollars = _gap(s3_target, current_pct, total_mv)
        plan.append({
            "sleeve": sleeve,
            "label": STRATEGIC_SLEEVE_LABELS.get(sleeve, sleeve.title()),
            "current_market_value": current_mv,
            "current_pct": current_pct,
            "s1_target_pct": s1_target,
            "s1_gap_pct": s1_gap_pct,
            "s1_gap_dollars": s1_gap_dollars,
            "s2_target_pct": s2_target,
            "s2_gap_pct": s2_gap_pct,
            "s2_gap_dollars": s2_gap_dollars,
            "s3_target_pct": s3_target,
            "s3_gap_pct": s3_gap_pct,
            "s3_gap_dollars": s3_gap_dollars,
        })
    for sleeve, mv in sleeve_mv.items():
        if sleeve in seen or sleeve == "pending":
            continue
        current_pct = (mv / total_mv * 100) if total_mv else 0.0
        plan.append({
            "sleeve": sleeve,
            "label": STRATEGIC_SLEEVE_LABELS.get(sleeve, sleeve.title()),
            "current_market_value": mv,
            "current_pct": current_pct,
            "s1_target_pct": None, "s1_gap_pct": None, "s1_gap_dollars": None,
            "s2_target_pct": None, "s2_gap_pct": None, "s2_gap_dollars": None,
            "s3_target_pct": None, "s3_gap_pct": None, "s3_gap_dollars": None,
        })
    return plan


def quoteable_symbols(positions: Iterable[dict]) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for row in positions:
        symbol = row["symbol"]
        if row["market_value"] <= 0 or not QUOTEABLE_SYMBOL_RE.match(symbol):
            continue
        if symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols
