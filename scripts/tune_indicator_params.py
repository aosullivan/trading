import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.backtesting import backtest_direction
from lib.data_fetching import (
    cached_download,
    normalize_ticker,
    resolve_treasury_price_proxy_ticker,
)
from lib.technical_indicators import (
    compute_bollinger_breakout,
    compute_cci_trend,
    compute_channel_breakout_close,
    compute_donchian_breakout,
    compute_ema_crossover,
    compute_ema_trend_signal,
    compute_keltner_breakout,
    compute_macd_crossover,
    compute_parabolic_sar,
    compute_sma_crossover,
    compute_supertrend,
    compute_trend_ribbon,
    compute_yearly_ma_trend,
)


WARMUP_START = "2015-01-01"
START = "2020-01-01"
END = "2026-04-02"
TICKERS = [
    "BTC-USD",
    "ETH-USD",
    "SPX",
    "VGT",
    "TLT",
    "NVDA",
    "AAPL",
    "TSLA",
    "XLE",
]


def load_frames():
    frames = {}
    for ticker in TICKERS:
        yf_ticker = normalize_ticker(resolve_treasury_price_proxy_ticker(ticker))
        df = cached_download(
            yf_ticker,
            start=WARMUP_START,
            end=END,
            interval="1d",
            progress=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        view = df.loc[
            (df.index >= pd.Timestamp(START)) & (df.index <= pd.Timestamp(END))
        ].copy()
        if not view.empty:
            frames[ticker] = (df, view)
    return frames


def score_direction(df, view, direction):
    start_idx = df.index.get_indexer([view.index[0]])[0]
    prior = int(direction.iloc[start_idx - 1]) if start_idx > 0 else 0
    _trades, summary, _eq = backtest_direction(
        view,
        direction.loc[view.index],
        start_in_position=(prior == 1),
        prior_direction=prior,
    )
    score = summary["net_profit_pct"] - 0.45 * summary["max_drawdown_pct"]
    return score, summary


def evaluate_strategy(frames, name, variants):
    baseline_label, _baseline_fn = variants[0]
    per_ticker_baseline = {}
    rows = []

    for label, fn in variants:
        scores = []
        nets = []
        dds = []
        trades = []
        beats = 0

        for ticker, (df, view) in frames.items():
            try:
                direction = fn(df)
                score, summary = score_direction(df, view, direction)
            except Exception:
                continue

            if label == baseline_label:
                per_ticker_baseline[ticker] = summary["net_profit_pct"]
            elif (
                ticker in per_ticker_baseline
                and summary["net_profit_pct"] > per_ticker_baseline[ticker]
            ):
                beats += 1

            scores.append(score)
            nets.append(summary["net_profit_pct"])
            dds.append(summary["max_drawdown_pct"])
            trades.append(summary["total_trades"])

        if not scores:
            continue

        rows.append(
            {
                "label": label,
                "avg_score": round(sum(scores) / len(scores), 4),
                "avg_net": round(sum(nets) / len(nets), 4),
                "avg_dd": round(sum(dds) / len(dds), 4),
                "avg_trades": round(sum(trades) / len(trades), 2),
                "beats": beats,
                "valid": len(scores),
            }
        )

    rows.sort(
        key=lambda row: (
            row["avg_score"],
            row["avg_net"],
            -row["avg_dd"],
            row["beats"],
        ),
        reverse=True,
    )

    print(f"\n{name}")
    for row in rows[:10]:
        print(row)


def supertrend_variants():
    variants = [("baseline_10_3", lambda d: compute_supertrend(d, 10, 3)[1])]
    for period in [7, 10, 14, 20]:
        for multiplier in [2.0, 2.5, 3.0, 3.5, 4.0]:
            if (period, multiplier) == (10, 3.0):
                continue
            variants.append(
                (
                    f"p{period}_m{multiplier:g}",
                    lambda d, p=period, m=multiplier: compute_supertrend(d, p, m)[1],
                )
            )
    return variants


def ema_variants():
    variants = [("baseline_9_21", lambda d: compute_ema_crossover(d, 9, 21)[2])]
    for fast, slow in [
        (5, 20),
        (6, 17),
        (8, 21),
        (9, 26),
        (10, 30),
        (12, 26),
        (13, 34),
        (20, 50),
    ]:
        variants.append(
            (
                f"{fast}_{slow}",
                lambda d, f=fast, s=slow: compute_ema_crossover(d, f, s)[2],
            )
        )
    return variants


def macd_variants():
    variants = [
        (
            "baseline_12_26_9",
            lambda d: compute_macd_crossover(d, 12, 26, 9)[3],
        )
    ]
    for fast, slow, signal in [
        (8, 17, 9),
        (10, 21, 8),
        (12, 26, 5),
        (16, 32, 9),
        (6, 19, 5),
        (5, 35, 5),
        (10, 30, 10),
    ]:
        variants.append(
            (
                f"{fast}_{slow}_{signal}",
                lambda d, f=fast, s=slow, g=signal: compute_macd_crossover(
                    d, f, s, g
                )[3],
            )
        )
    return variants


def donchian_variants():
    variants = [("baseline_20", lambda d: compute_donchian_breakout(d, 20)[2])]
    for period in [10, 14, 30, 40, 55, 80]:
        variants.append(
            (
                f"p{period}",
                lambda d, p=period: compute_donchian_breakout(d, p)[2],
            )
        )
    return variants


def cb_variants():
    variants = [("baseline_cb50", lambda d: compute_channel_breakout_close(d, 50)[2])]
    for period in [20, 50, 100, 150, 200]:
        variants.append(
            (
                f"cb{period}",
                lambda d, p=period: compute_channel_breakout_close(d, p)[2],
            )
        )
    return variants


def bb_variants():
    variants = [
        ("baseline_20_2", lambda d: compute_bollinger_breakout(d, 20, 2)[3])
    ]
    for period in [10, 14, 20, 30]:
        for std_dev in [1.5, 2.5, 3.0]:
            variants.append(
                (
                    f"p{period}_s{std_dev:g}",
                    lambda d, p=period, s=std_dev: compute_bollinger_breakout(
                        d, p, s
                    )[3],
                )
            )
    return variants


def keltner_variants():
    variants = [
        (
            "baseline_20_10_1.5",
            lambda d: compute_keltner_breakout(d, 20, 10, 1.5)[3],
        )
    ]
    for ema_p, atr_p, mult in [
        (20, 14, 1.5),
        (20, 10, 2.0),
        (20, 14, 2.0),
        (30, 14, 2.0),
        (10, 10, 1.5),
        (10, 10, 2.0),
        (30, 10, 1.5),
        (30, 20, 2.0),
        (50, 20, 2.5),
    ]:
        variants.append(
            (
                f"e{ema_p}_a{atr_p}_m{mult:g}",
                lambda d, e=ema_p, a=atr_p, m=mult: compute_keltner_breakout(
                    d, e, a, m
                )[3],
            )
        )
    return variants


def psar_variants():
    variants = [
        (
            "baseline_0.02_0.02_0.2",
            lambda d: compute_parabolic_sar(d, 0.02, 0.02, 0.2)[1],
        )
    ]
    for af_start, af_increment, af_max in [
        (0.01, 0.01, 0.1),
        (0.01, 0.01, 0.2),
        (0.01, 0.02, 0.2),
        (0.02, 0.01, 0.2),
        (0.02, 0.03, 0.2),
        (0.03, 0.03, 0.2),
        (0.02, 0.02, 0.3),
        (0.03, 0.02, 0.3),
        (0.04, 0.04, 0.4),
    ]:
        variants.append(
            (
                f"{af_start:g}_{af_increment:g}_{af_max:g}",
                lambda d, s=af_start, i=af_increment, m=af_max: compute_parabolic_sar(
                    d, s, i, m
                )[1],
            )
        )
    return variants


def cci_variants():
    variants = [("baseline_20_100", lambda d: compute_cci_trend(d, 20, 100)[1])]
    for period in [10, 14, 20, 30, 40]:
        for threshold in [80, 120, 150, 200]:
            variants.append(
                (
                    f"p{period}_t{threshold}",
                    lambda d, p=period, t=threshold: compute_cci_trend(d, p, t)[1],
                )
            )
    return variants


def ribbon_variants():
    variants = [("baseline", lambda d: compute_trend_ribbon(d)[4])]
    for ema_p, atr_p, fast_p, slow_p, smooth_p, collapse_t, expand_t in [
        (21, 14, 6, 21, 5, 0.08, 0.15),
        (21, 14, 5, 21, 3, 0.06, 0.12),
        (20, 10, 8, 21, 5, 0.08, 0.12),
        (20, 10, 6, 17, 4, 0.06, 0.12),
        (21, 14, 4, 13, 5, 0.08, 0.12),
        (34, 14, 8, 34, 5, 0.08, 0.15),
        (13, 10, 5, 21, 3, 0.06, 0.12),
    ]:
        variants.append(
            (
                f"e{ema_p}_a{atr_p}_f{fast_p}_s{slow_p}_sm{smooth_p}_c{collapse_t:g}_x{expand_t:g}",
                lambda d,
                e=ema_p,
                a=atr_p,
                f=fast_p,
                s=slow_p,
                sm=smooth_p,
                c=collapse_t,
                x=expand_t: compute_trend_ribbon(
                    d,
                    ema_period=e,
                    atr_period=a,
                    fast_period=f,
                    slow_period=s,
                    smooth_period=sm,
                    collapse_threshold=c,
                    expand_threshold=x,
                )[4],
            )
        )
    return variants


STRATEGY_GRIDS = {
    "supertrend": ("Supertrend", supertrend_variants),
    "ema": ("EMA", ema_variants),
    "macd": ("MACD", macd_variants),
    "donchian": ("Donchian", donchian_variants),
    "cb": ("Channel Breakout", cb_variants),
    "bb": ("Bollinger", bb_variants),
    "keltner": ("Keltner", keltner_variants),
    "psar": ("Parabolic SAR", psar_variants),
    "cci": ("CCI", cci_variants),
    "ribbon": ("Trend Ribbon", ribbon_variants),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("strategies", nargs="*", default=sorted(STRATEGY_GRIDS))
    args = parser.parse_args()

    frames = load_frames()
    print("loaded tickers:", ", ".join(sorted(frames)))

    for key in args.strategies:
        name, build_variants = STRATEGY_GRIDS[key]
        evaluate_strategy(frames, name, build_variants())


if __name__ == "__main__":
    main()
