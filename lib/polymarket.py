"""Polymarket Bitcoin prediction market data fetcher.

Fetches BTC price prediction markets from Polymarket's public APIs
and computes an implied probability distribution for Bitcoin's future price.
"""

import json
import os
import time as _time

import requests
import pandas as pd

from lib.cache import _cache_get, _cache_set, _PROJECT_CACHE_ROOT

# ---------------------------------------------------------------------------
# Cache settings
# ---------------------------------------------------------------------------
_POLYMARKET_CACHE_TTL = 900  # 15 minutes for live market data
_POLYMARKET_HISTORY_CACHE_TTL = 3600  # 1 hour for historical snapshots
_POLYMARKET_DISK_CACHE_DIR = os.path.join(_PROJECT_CACHE_ROOT, "polymarket")
os.makedirs(_POLYMARKET_DISK_CACHE_DIR, exist_ok=True)
_POLYMARKET_AUTOSEED_FAILURE_TTL = 1800  # 30 minutes
_POLYMARKET_DEFAULT_BULL_THRESHOLD = 1.05
_POLYMARKET_DEFAULT_BEAR_THRESHOLD = 0.95
_POLYMARKET_RELEVANCE_DISTANCE_SCALE = 4.0
_POLYMARKET_RELEVANCE_POWER = 2.0
_POLYMARKET_NEAR_STRIKE_PCT = 0.12
_POLYMARKET_NEAR_STRIKE_BONUS = 0.5

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CLOB_BASE = "https://clob.polymarket.com"

# ---------------------------------------------------------------------------
# Market discovery
# ---------------------------------------------------------------------------


def fetch_btc_events(limit=20):
    """Fetch Bitcoin-related events from Polymarket's Gamma API.

    Returns a list of event dicts, each containing nested markets
    with probabilities and metadata.
    """
    cache_key = f"polymarket:btc_events:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = requests.get(
        f"{_GAMMA_BASE}/events",
        params={
            "_q": "bitcoin",
            "closed": "false",
            "limit": limit,
            "order": "volume",
            "ascending": "false",
        },
        timeout=15,
    )
    resp.raise_for_status()
    events = resp.json()
    _cache_set(cache_key, events, ttl=_POLYMARKET_CACHE_TTL)
    return events


def fetch_btc_price_markets():
    """Fetch all active BTC price prediction markets.

    Paginates through Polymarket events, finds Bitcoin-related events,
    and extracts price-level markets with strike prices and probabilities.
    """
    cache_key = "polymarket:btc_price_markets"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Paginate through events to find all BTC-related ones
    raw_markets = []
    seen_ids = set()

    for offset in range(0, 1000, 100):
        try:
            resp = requests.get(
                f"{_GAMMA_BASE}/events",
                params={
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                },
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception:
            break

        if not events:
            break

        for event in events:
            title = event.get("title", "").lower()
            # Only keep Bitcoin-related events
            if not any(kw in title for kw in ["bitcoin", "btc"]):
                continue
            # Skip non-price events (governance, tech, 5-min gambling)
            if any(kw in title for kw in [
                "sha-256", "replace", "unban", "knots",
                "up or down", "bip-",
            ]):
                continue

            for m in event.get("markets", []):
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    raw_markets.append(m)

    # Also grab individual BTC markets from the markets endpoint
    for offset in range(0, 400, 100):
        try:
            resp = requests.get(
                f"{_GAMMA_BASE}/markets",
                params={
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            for m in resp.json():
                q = m.get("question", "").lower()
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    if any(kw in q for kw in ["bitcoin", "btc"]):
                        if "up or down" not in q:
                            seen_ids.add(mid)
                            raw_markets.append(m)
        except Exception:
            break

    parsed = _parse_price_markets(raw_markets)
    _cache_set(cache_key, parsed, ttl=_POLYMARKET_CACHE_TTL)
    return parsed


def _parse_price_markets(raw_markets):
    """Extract structured data from raw Gamma API market responses.

    Keeps only direct BTC price-target questions.
    """
    parsed = []
    for m in raw_markets:
        question = m.get("question", "")
        q_lower = question.lower()
        if not _is_price_target_question(question):
            continue

        # Parse outcome prices
        try:
            prices = json.loads(m.get("outcomePrices", "[]"))
            yes_price = float(prices[0]) if prices else None
        except (json.JSONDecodeError, IndexError, TypeError):
            yes_price = None

        # Extract strike price from question
        strike = _extract_strike_price(question)

        # Determine direction
        direction = "above"
        if any(kw in q_lower for kw in ["below", "dip", "drop", "fall"]):
            direction = "below"

        # Parse clob token IDs
        try:
            clob_ids = json.loads(m.get("clobTokenIds", "[]"))
        except (json.JSONDecodeError, TypeError):
            clob_ids = []

        parsed.append({
            "id": m.get("id"),
            "question": question,
            "slug": m.get("slug", ""),
            "yes_price": yes_price,
            "volume": m.get("volumeNum", 0),
            "liquidity": m.get("liquidityNum", 0),
            "strike_price": strike,
            "direction": direction,
            "end_date": m.get("endDateIso"),
            "clob_token_ids": clob_ids,
            "best_bid": m.get("bestBid"),
            "best_ask": m.get("bestAsk"),
        })

    return parsed


def _extract_strike_price(question):
    """Extract dollar price target from a market question string.

    Examples:
        "Will Bitcoin be above $100k on April 7?" -> 100000
        "Will BTC reach $85,000 by December?" -> 85000
        "Bitcoin dip to $45k?" -> 45000
    """
    import re

    # Try $Xk / $XK pattern first (e.g. "$150k" -> 150000)
    match = re.search(r'\$(\d+(?:\.\d+)?)[kK]', question)
    if match:
        return float(match.group(1)) * 1000

    # Try $X,XXX,XXX pattern (e.g. "$100,000" -> 100000)
    match = re.search(r'\$(\d{1,3}(?:,\d{3})+)', question)
    if match:
        return float(match.group(1).replace(",", ""))

    # Try $XXXXX+ bare number (e.g. "$200000" -> 200000, but not "$50")
    match = re.search(r'\$(\d{4,})', question)
    if match:
        return float(match.group(1))

    # Try "$X billion/million" patterns
    match = re.search(r'\$(\d+(?:\.\d+)?)\s*[bB]', question)
    if match:
        return float(match.group(1)) * 1_000_000_000

    match = re.search(r'\$(\d+(?:\.\d+)?)\s*[mM]', question)
    if match:
        return float(match.group(1)) * 1_000_000

    return None


def _is_price_target_question(question: str) -> bool:
    """Return True only for direct BTC price-target questions."""
    q_lower = question.lower().strip()
    if not any(token in q_lower for token in ["bitcoin", "btc"]):
        return False

    price_patterns = [
        "price of bitcoin be above",
        "price of bitcoin be below",
        "price of bitcoin be between",
        "bitcoin reach $",
        "bitcoin hit $",
        "bitcoin dip to $",
        "btc reach $",
        "btc hit $",
        "btc dip to $",
        "bitcoin be above $",
        "bitcoin be below $",
    ]
    return any(pattern in q_lower for pattern in price_patterns)


# ---------------------------------------------------------------------------
# Price history for probability tracking
# ---------------------------------------------------------------------------


def fetch_price_history(token_id, interval="1d", fidelity=60):
    """Fetch probability price history for a specific market token.

    Returns list of {"t": unix_timestamp, "p": probability} dicts.
    """
    cache_key = f"polymarket:history:{token_id}:{interval}:{fidelity}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = requests.get(
        f"{_CLOB_BASE}/prices-history",
        params={
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    history = data.get("history", [])
    _cache_set(cache_key, history, ttl=_POLYMARKET_HISTORY_CACHE_TTL)
    return history


def _probability_history_file() -> str:
    return os.path.join(_POLYMARKET_DISK_CACHE_DIR, "probability_history.json")


def fetch_midpoint(token_id):
    """Fetch current midpoint price for a market token."""
    resp = requests.get(
        f"{_CLOB_BASE}/midpoint",
        params={"token_id": token_id},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data.get("mid", 0))


# ---------------------------------------------------------------------------
# Implied distribution computation
# ---------------------------------------------------------------------------


def build_implied_distribution(markets):
    """Build an implied probability distribution from Polymarket strike markets.

    Takes parsed price markets and constructs a picture of where the crowd
    thinks BTC is headed.

    Returns a dict with:
        - upside_strikes: [{strike, probability, question}, ...] sorted by strike
        - downside_strikes: [{strike, probability, question}, ...] sorted by strike
        - skew_ratio: P(upside) / P(downside) — values > 1 = bullish
        - implied_expected_move_pct: probability-weighted expected move
        - bull_probability: aggregate probability of upside targets
        - bear_probability: aggregate probability of downside targets
    """
    upside = []
    downside = []

    for m in markets:
        if m["strike_price"] is None or m["yes_price"] is None:
            continue
        entry = {
            "strike": m["strike_price"],
            "probability": m["yes_price"],
            "question": m["question"],
            "volume": m["volume"],
            "direction": m["direction"],
        }
        if m["direction"] == "above":
            upside.append(entry)
        else:
            downside.append(entry)

    upside.sort(key=lambda x: x["strike"])
    downside.sort(key=lambda x: x["strike"], reverse=True)

    # Aggregate probabilities (volume-weighted for better signal)
    total_up_vol = sum(s["volume"] for s in upside) or 1
    total_down_vol = sum(s["volume"] for s in downside) or 1

    bull_prob = sum(
        s["probability"] * s["volume"] / total_up_vol for s in upside
    ) if upside else 0

    bear_prob = sum(
        s["probability"] * s["volume"] / total_down_vol for s in downside
    ) if downside else 0

    # Skew ratio: > 1 means market is more bullish than bearish
    skew = bull_prob / bear_prob if bear_prob > 0 else float("inf")

    distribution = {
        "upside_strikes": upside,
        "downside_strikes": downside,
        "skew_ratio": round(skew, 4),
        "bull_probability": round(bull_prob, 4),
        "bear_probability": round(bear_prob, 4),
    }
    signal_metrics = _build_signal_distribution_from_entries(
        upside + downside,
        spot_price=fetch_btc_spot_price(),
    )
    distribution.update(signal_metrics)
    return distribution


def _build_signal_distribution_from_entries(entries, spot_price):
    """Build the Polymarket signal from strike relevance around spot price."""
    if not spot_price:
        return _fallback_signal_distribution()

    upside_weighted = []
    downside_weighted = []

    for entry in entries:
        strike = _safe_float(entry.get("strike"))
        probability = _safe_float(entry.get("probability"))
        volume = _safe_float(entry.get("volume"))
        direction = entry.get("direction")
        if (
            strike is None
            or probability is None
            or volume is None
            or volume <= 0
            or probability <= 0
            or direction not in {"above", "below"}
        ):
            continue

        distance_pct = abs(strike - spot_price) / spot_price if spot_price else None
        if distance_pct is None:
            continue
        weight = volume / (
            (1 + distance_pct * _POLYMARKET_RELEVANCE_DISTANCE_SCALE)
            ** _POLYMARKET_RELEVANCE_POWER
        )
        if distance_pct <= _POLYMARKET_NEAR_STRIKE_PCT:
            weight *= 1 + _POLYMARKET_NEAR_STRIKE_BONUS
        bucket = upside_weighted if direction == "above" else downside_weighted
        bucket.append((probability, weight))

    if not upside_weighted or not downside_weighted:
        return _fallback_signal_distribution()

    total_up_weight = sum(weight for _, weight in upside_weighted) or 1
    total_down_weight = sum(weight for _, weight in downside_weighted) or 1
    signal_bull = sum(
        probability * weight / total_up_weight for probability, weight in upside_weighted
    )
    signal_bear = sum(
        probability * weight / total_down_weight for probability, weight in downside_weighted
    )
    signal_skew = signal_bull / signal_bear if signal_bear > 0 else float("inf")
    if signal_skew == float("inf"):
        signal_skew = 10.0

    return {
        "signal_source": "relevance_weighted",
        "signal_skew_ratio": round(signal_skew, 4),
        "signal_bull_probability": round(signal_bull, 4),
        "signal_bear_probability": round(signal_bear, 4),
    }


def _fallback_signal_distribution():
    return {
        "signal_source": "raw_skew",
        "signal_skew_ratio": None,
        "signal_bull_probability": None,
        "signal_bear_probability": None,
    }


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_snapshot_signal_metrics(snapshot):
    """Compute a strategy-ready skew series from a saved snapshot row."""
    signal_skew = snapshot.get("signal_skew_ratio")
    signal_bull = snapshot.get("signal_bull_probability")
    signal_bear = snapshot.get("signal_bear_probability")
    if signal_skew is not None and signal_bull is not None and signal_bear is not None:
        return {
            "signal_source": snapshot.get("signal_source", "persisted"),
            "signal_skew_ratio": _safe_float(signal_skew),
            "signal_bull_probability": _safe_float(signal_bull),
            "signal_bear_probability": _safe_float(signal_bear),
        }

    spot_price = _safe_float(snapshot.get("spot_price"))
    strikes = snapshot.get("strikes") or []
    entries = []
    for strike in strikes:
        entries.append(
            {
                "strike": strike.get("strike"),
                "probability": strike.get("probability"),
                "volume": strike.get("volume"),
                "direction": strike.get("direction"),
            }
        )
    signal_metrics = _build_signal_distribution_from_entries(entries, spot_price)
    if signal_metrics["signal_skew_ratio"] is None:
        signal_metrics.update(
            {
                "signal_skew_ratio": _safe_float(snapshot.get("skew_ratio")),
                "signal_bull_probability": _safe_float(
                    snapshot.get("bull_probability")
                ),
                "signal_bear_probability": _safe_float(
                    snapshot.get("bear_probability")
                ),
            }
        )
    return signal_metrics


# ---------------------------------------------------------------------------
# Snapshot persistence for backtesting
# ---------------------------------------------------------------------------


def fetch_btc_spot_price():
    """Fetch current BTC-USD spot price from Yahoo Finance via yfinance.

    Caches for 5 minutes to avoid rate limiting.
    """
    cache_key = "polymarket:btc_spot"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from lib.data_fetching import cached_download
        df = cached_download("BTC-USD", interval="1d", period="5d")
        if df is not None and not df.empty:
            price = round(float(df["Close"].iloc[-1]), 2)
            _cache_set(cache_key, price, ttl=300)
            return price
    except Exception:
        pass
    latest_snapshot_spot = _latest_saved_spot_price()
    if latest_snapshot_spot is not None:
        _cache_set(cache_key, latest_snapshot_spot, ttl=300)
        return latest_snapshot_spot
    return None


def _latest_saved_spot_price():
    history_file = _probability_history_file()
    if not os.path.exists(history_file):
        return None
    try:
        with open(history_file) as f:
            history = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    for snapshot in reversed(history):
        spot_price = _safe_float(snapshot.get("spot_price"))
        if spot_price is not None:
            return round(spot_price, 2)
    return None


def seed_probability_history():
    """Backfill historical Polymarket probability snapshots from CLOB history."""
    markets = fetch_btc_price_markets()
    markets_with_tokens = [
        m
        for m in markets
        if m["clob_token_ids"]
        and m["volume"]
        and m["volume"] > 1000
        and m["strike_price"]
        and m["strike_price"] >= 1000
    ]
    if not markets_with_tokens:
        return pd.DataFrame()

    all_histories = {}
    for m in markets_with_tokens:
        token_id = m["clob_token_ids"][0]
        history = fetch_price_history(token_id, interval="max", fidelity=1440)
        if history:
            all_histories[f"{m['direction']}_{m['strike_price']:.0f}"] = {
                "question": m["question"],
                "strike": m["strike_price"],
                "direction": m["direction"],
                "volume": m["volume"],
                "history": history,
            }

    if not all_histories:
        return pd.DataFrame()

    all_dates = set()
    for data in all_histories.values():
        for point in data["history"]:
            all_dates.add(pd.Timestamp(point["t"], unit="s").normalize())
    if not all_dates:
        return pd.DataFrame()

    all_dates = sorted(all_dates)

    from lib.data_fetching import cached_download

    start_str = all_dates[0].strftime("%Y-%m-%d")
    end_str = all_dates[-1].strftime("%Y-%m-%d")
    btc_df = cached_download("BTC-USD", interval="1d", start=start_str, end=end_str)
    spot_prices = {}
    if btc_df is not None and not btc_df.empty:
        for dt, row in btc_df.iterrows():
            spot_prices[dt.normalize()] = round(float(row["Close"]), 2)

    daily_snapshots = []
    for date in all_dates:
        upside_probs = []
        downside_probs = []
        strikes_snapshot = []

        for data in all_histories.values():
            closest = None
            for point in data["history"]:
                pt = pd.Timestamp(point["t"], unit="s").normalize()
                if pt <= date:
                    closest = point
                elif closest is not None:
                    break

            if closest is None:
                continue

            prob = closest["p"]
            vol = data["volume"]
            strikes_snapshot.append(
                {
                    "strike": data["strike"],
                    "direction": data["direction"],
                    "probability": round(prob, 4),
                    "volume": vol,
                }
            )
            if data["direction"] == "above":
                upside_probs.append((prob, vol))
            else:
                downside_probs.append((prob, vol))

        if not upside_probs and not downside_probs:
            continue

        total_up_vol = sum(v for _, v in upside_probs) or 1
        total_down_vol = sum(v for _, v in downside_probs) or 1
        bull_prob = sum(p * v / total_up_vol for p, v in upside_probs) if upside_probs else 0
        bear_prob = sum(p * v / total_down_vol for p, v in downside_probs) if downside_probs else 0
        skew = bull_prob / bear_prob if bear_prob > 0 else float("inf")
        if skew == float("inf"):
            skew = 10.0

        spot = spot_prices.get(date)
        if spot is None:
            for offset in range(1, 5):
                spot = spot_prices.get(date - pd.Timedelta(days=offset))
                if spot is not None:
                    break

        daily_snapshots.append(
            {
                "timestamp": date.timestamp(),
                "date": date.strftime("%Y-%m-%d"),
                "spot_price": spot,
                "skew_ratio": round(skew, 4),
                "bull_probability": round(bull_prob, 4),
                "bear_probability": round(bear_prob, 4),
                "upside_count": len(upside_probs),
                "downside_count": len(downside_probs),
                "total_markets": len(strikes_snapshot),
                "strikes": strikes_snapshot,
            }
        )

    if not daily_snapshots:
        return pd.DataFrame()

    history_file = _probability_history_file()
    os.makedirs(_POLYMARKET_DISK_CACHE_DIR, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(daily_snapshots, f, indent=2)

    df = pd.DataFrame(daily_snapshots)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def save_probability_snapshot(distribution, spot_price=None):
    """Save current probability distribution snapshot to disk for historical tracking.

    If spot_price is not provided, automatically fetches from Yahoo Finance.
    """
    if spot_price is None:
        spot_price = fetch_btc_spot_price()

    # Build per-strike snapshot for richer history
    strikes_snapshot = []
    for s in distribution.get("upside_strikes", []):
        strikes_snapshot.append({
            "strike": s["strike"],
            "direction": "above",
            "probability": s["probability"],
            "volume": s["volume"],
        })
    for s in distribution.get("downside_strikes", []):
        strikes_snapshot.append({
            "strike": s["strike"],
            "direction": "below",
            "probability": s["probability"],
            "volume": s["volume"],
        })

    snapshot = {
        "timestamp": _time.time(),
        "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "spot_price": spot_price,
        "skew_ratio": distribution["skew_ratio"],
        "bull_probability": distribution["bull_probability"],
        "bear_probability": distribution["bear_probability"],
        "signal_source": distribution.get("signal_source"),
        "signal_skew_ratio": distribution.get("signal_skew_ratio"),
        "signal_bull_probability": distribution.get("signal_bull_probability"),
        "signal_bear_probability": distribution.get("signal_bear_probability"),
        "upside_count": len(distribution.get("upside_strikes", [])),
        "downside_count": len(distribution.get("downside_strikes", [])),
        "total_markets": len(strikes_snapshot),
        "strikes": strikes_snapshot,
    }

    history_file = _probability_history_file()
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file) as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []

    # Avoid duplicate entries for the same date
    today = snapshot["date"]
    history = [h for h in history if h.get("date") != today]
    history.append(snapshot)

    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)

    return snapshot


def load_probability_history(auto_seed=False):
    """Load accumulated probability snapshots from disk.

    Returns a DataFrame with columns: date, skew_ratio, bull_probability,
    bear_probability, spot_price.
    """
    history_file = _probability_history_file()
    if not os.path.exists(history_file):
        if auto_seed and _cache_get("polymarket:history_autoseed_failed") is None:
            try:
                seeded = seed_probability_history()
                if not seeded.empty:
                    return seeded
            except Exception:
                _cache_set(
                    "polymarket:history_autoseed_failed",
                    True,
                    ttl=_POLYMARKET_AUTOSEED_FAILURE_TTL,
                )
        return pd.DataFrame()

    try:
        with open(history_file) as f:
            history = json.load(f)
    except (json.JSONDecodeError, IOError):
        return pd.DataFrame()

    if not history:
        if auto_seed and _cache_get("polymarket:history_autoseed_failed") is None:
            try:
                seeded = seed_probability_history()
                if not seeded.empty:
                    return seeded
            except Exception:
                _cache_set(
                    "polymarket:history_autoseed_failed",
                    True,
                    ttl=_POLYMARKET_AUTOSEED_FAILURE_TTL,
                )
        return pd.DataFrame()

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def compute_polymarket_signal(
    markets,
    skew_bull_threshold=_POLYMARKET_DEFAULT_BULL_THRESHOLD,
    skew_bear_threshold=_POLYMARKET_DEFAULT_BEAR_THRESHOLD,
):
    """Compute a directional trading signal from Polymarket data.

    Signal logic:
        - skew_ratio > skew_bull_threshold → Long (1)
        - skew_ratio < skew_bear_threshold → Flat/Short (-1)
        - In between → Neutral (0)

    Returns:
        direction (int): 1 = long, -1 = short/flat, 0 = neutral
        distribution (dict): full implied distribution data
    """
    distribution = build_implied_distribution(markets)
    skew = distribution.get("signal_skew_ratio") or distribution["skew_ratio"]

    if skew > skew_bull_threshold:
        direction = 1
    elif skew < skew_bear_threshold:
        direction = -1
    else:
        direction = 0

    return direction, distribution


def compute_polymarket_direction_series(
    ohlcv_df,
    probability_history_df=None,
    skew_bull_threshold=_POLYMARKET_DEFAULT_BULL_THRESHOLD,
    skew_bear_threshold=_POLYMARKET_DEFAULT_BEAR_THRESHOLD,
    momentum_window=3,
):
    """Build a direction Series aligned to an OHLCV DataFrame using Polymarket data.

    This is the main integration point with the backtesting engine.
    It merges Polymarket probability history with price data to produce
    a standard direction Series (1/-1/0).

    Signal components:
    1. Skew signal: skew_ratio > bull_threshold → long
    2. Momentum signal: rising skew over momentum_window days → confirmation
    3. Combined: both must agree for a signal change

    If no probability_history is available, falls back to current live data.

    Returns: pd.Series of direction values (1, -1, 0) aligned to ohlcv_df.index
    """
    direction = pd.Series(0, index=ohlcv_df.index)

    if probability_history_df is None or probability_history_df.empty:
        # No historical data — try live snapshot
        try:
            markets = fetch_btc_price_markets()
            live_dir, dist = compute_polymarket_signal(
                markets, skew_bull_threshold, skew_bear_threshold
            )
            # Apply the live signal to recent bars only (last 5 days)
            direction.iloc[-5:] = live_dir
        except Exception:
            pass
        return direction

    # Merge probability history with OHLCV index
    prob_df = probability_history_df.copy()
    if "signal_skew_ratio" not in prob_df.columns:
        signal_rows = []
        for _, row in prob_df.iterrows():
            signal_rows.append(_compute_snapshot_signal_metrics(row))
        signal_df = pd.DataFrame(signal_rows, index=prob_df.index)
        prob_df = pd.concat([prob_df, signal_df], axis=1)

    # Reindex to match OHLCV dates, forward-fill probabilities
    prob_aligned = prob_df.reindex(ohlcv_df.index, method="ffill")

    if "signal_skew_ratio" not in prob_aligned.columns and "skew_ratio" not in prob_aligned.columns:
        return direction

    skew = prob_aligned["signal_skew_ratio"].fillna(prob_aligned.get("skew_ratio"))

    # Component 1: Level signal
    level_signal = pd.Series(0, index=ohlcv_df.index)
    level_signal[skew > skew_bull_threshold] = 1
    level_signal[skew < skew_bear_threshold] = -1

    # Component 2: Momentum signal (rising/falling skew)
    skew_ma = skew.rolling(window=momentum_window, min_periods=1).mean()
    skew_momentum = skew - skew_ma
    momentum_signal = pd.Series(0, index=ohlcv_df.index)
    momentum_signal[skew_momentum > 0] = 1
    momentum_signal[skew_momentum < 0] = -1

    # Combined: level signal takes precedence, momentum confirms
    # Go long when skew is bullish AND momentum is positive (or neutral)
    # Go flat when skew is bearish AND momentum is negative (or neutral)
    direction[(level_signal == 1) & (momentum_signal >= 0)] = 1
    direction[(level_signal == -1) & (momentum_signal <= 0)] = -1

    # In ambiguous cases, carry forward the previous signal
    direction = direction.replace(0, pd.NA).ffill().fillna(0).astype(int)

    return direction
