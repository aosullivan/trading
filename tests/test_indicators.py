"""Tests for all technical indicator computations."""

import numpy as np
import pandas as pd
import pytest

from lib.technical_indicators import (
    compute_supertrend,
    compute_channel_breakout_close,
    compute_sma_crossover,
    compute_ema_trend_signal,
    compute_yearly_ma_trend,
    compute_ema_crossover,
    compute_macd_crossover,
    compute_donchian_breakout,
    compute_bollinger_breakout,
    compute_keltner_breakout,
    compute_parabolic_sar,
    compute_cci_trend,
    compute_trend_ribbon,
)


class TestSupertrend:
    def test_returns_correct_shape(self, sample_df):
        st, direction = compute_supertrend(sample_df, period=10, multiplier=3)
        assert len(st) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, direction = compute_supertrend(sample_df)
        unique = set(direction.dropna().unique())
        assert unique.issubset({-1, 1}), f"Unexpected direction values: {unique}"

    def test_supertrend_nan_during_warmup(self, sample_df):
        st, _ = compute_supertrend(sample_df, period=10)
        assert pd.isna(st.iloc[0])
        assert not pd.isna(st.iloc[15])

    def test_custom_params(self, sample_df):
        st1, d1 = compute_supertrend(sample_df, period=5, multiplier=1)
        st2, d2 = compute_supertrend(sample_df, period=20, multiplier=5)
        assert not st1.equals(st2)


class TestChannelBreakoutClose:
    def test_returns_correct_shape(self, sample_df):
        hc, lc, direction = compute_channel_breakout_close(sample_df, period=50)
        assert len(hc) == len(sample_df)
        assert len(lc) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, _, direction = compute_channel_breakout_close(sample_df, period=50)
        unique = set(direction.unique())
        assert unique.issubset({-1, 0, 1})

    def test_hc_gte_lc(self, sample_df):
        hc, lc, _ = compute_channel_breakout_close(sample_df, period=50)
        valid = hc.dropna().index
        assert (hc[valid] >= lc[valid]).all()


class TestSMACrossover:
    def test_returns_three_series(self, sample_df):
        fast, slow, direction = compute_sma_crossover(sample_df, fast=10, slow=100)
        assert len(fast) == len(sample_df)
        assert len(slow) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, _, direction = compute_sma_crossover(sample_df, fast=10, slow=100)
        unique = set(direction.iloc[100:].unique())
        assert unique.issubset({-1, 1})


class TestEMATrendSignal:
    def test_returns_correct_shape(self, sample_df):
        ref, sig, direction = compute_ema_trend_signal(sample_df, decay_days=105)
        assert len(ref) == len(sample_df)
        assert len(sig) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, _, direction = compute_ema_trend_signal(sample_df)
        unique = set(direction.unique())
        assert unique.issubset({-1, 0, 1})


class TestYearlyMATrend:
    def test_returns_correct_shape(self, sample_df):
        ma, direction = compute_yearly_ma_trend(sample_df, period=252)
        assert len(ma) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, direction = compute_yearly_ma_trend(sample_df)
        unique = set(direction.unique())
        assert unique.issubset({-1, 0, 1})


class TestEMACrossover:
    def test_returns_three_series(self, sample_df):
        fast, slow, direction = compute_ema_crossover(sample_df, fast=9, slow=21)
        assert len(fast) == len(sample_df)
        assert len(slow) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, _, direction = compute_ema_crossover(sample_df)
        unique = set(direction.iloc[21:].unique())
        assert unique.issubset({-1, 1})

    def test_fast_reacts_quicker(self, sample_df):
        fast, slow, _ = compute_ema_crossover(sample_df)
        last_close = sample_df["Close"].iloc[-1]
        assert abs(fast.iloc[-1] - last_close) <= abs(slow.iloc[-1] - last_close)


class TestMACDCrossover:
    def test_returns_four_series(self, sample_df):
        macd, signal, hist, direction = compute_macd_crossover(sample_df)
        assert len(macd) == len(sample_df)
        assert len(signal) == len(sample_df)
        assert len(hist) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_histogram_equals_diff(self, sample_df):
        macd, signal, hist, _ = compute_macd_crossover(sample_df)
        diff = macd - signal
        np.testing.assert_array_almost_equal(hist.values, diff.values)

    def test_direction_values(self, sample_df):
        _, _, _, direction = compute_macd_crossover(sample_df)
        unique = set(direction.iloc[50:].unique())
        assert unique.issubset({-1, 1})


class TestDonchianBreakout:
    def test_returns_correct_shape(self, sample_df):
        upper, lower, direction = compute_donchian_breakout(sample_df, period=20)
        assert len(upper) == len(sample_df)
        assert len(lower) == len(sample_df)

    def test_upper_gte_lower(self, sample_df):
        upper, lower, _ = compute_donchian_breakout(sample_df, period=20)
        valid = upper.dropna().index
        assert (upper[valid] >= lower[valid]).all()



class TestBollingerBreakout:
    def test_returns_correct_shape(self, sample_df):
        upper, middle, lower, direction = compute_bollinger_breakout(sample_df)
        assert len(upper) == len(sample_df)
        assert len(middle) == len(sample_df)
        assert len(lower) == len(sample_df)

    def test_band_ordering(self, sample_df):
        upper, middle, lower, _ = compute_bollinger_breakout(sample_df)
        valid = upper.dropna().index
        assert (upper[valid] >= middle[valid]).all()
        assert (middle[valid] >= lower[valid]).all()


class TestKeltnerBreakout:
    def test_returns_correct_shape(self, sample_df):
        upper, middle, lower, direction = compute_keltner_breakout(sample_df)
        assert len(upper) == len(sample_df)

    def test_band_ordering(self, sample_df):
        upper, middle, lower, _ = compute_keltner_breakout(sample_df)
        valid = upper.dropna().index
        assert (upper[valid] >= middle[valid]).all()
        assert (middle[valid] >= lower[valid]).all()


class TestParabolicSAR:
    def test_returns_correct_shape(self, sample_df):
        sar, direction = compute_parabolic_sar(sample_df)
        assert len(sar) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, direction = compute_parabolic_sar(sample_df)
        unique = set(direction.iloc[1:].unique())
        assert unique.issubset({-1, 1})


class TestCCITrend:
    def test_returns_correct_shape(self, sample_df):
        cci, direction = compute_cci_trend(sample_df)
        assert len(cci) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, direction = compute_cci_trend(sample_df)
        unique = set(direction.unique())
        assert unique.issubset({-1, 0, 1})


class TestTrendRibbon:
    def test_returns_five_series(self, sample_df):
        result = compute_trend_ribbon(sample_df)
        assert len(result) == 5, "Should return (center, upper, lower, strength, direction)"

    def test_correct_shape(self, sample_df):
        center, upper, lower, strength, direction = compute_trend_ribbon(sample_df)
        for s in (center, upper, lower, strength, direction):
            assert len(s) == len(sample_df)

    def test_band_ordering(self, sample_df):
        center, upper, lower, _, _ = compute_trend_ribbon(sample_df)
        valid = upper.dropna().index.intersection(lower.dropna().index).intersection(center.dropna().index)
        assert (upper[valid] >= center[valid]).all(), "Upper should be >= center"
        assert (center[valid] >= lower[valid]).all(), "Center should be >= lower"

    def test_direction_values(self, sample_df):
        _, _, _, _, direction = compute_trend_ribbon(sample_df)
        unique = set(direction.dropna().unique())
        assert unique.issubset({-1, 0, 1})

    def test_strength_range(self, sample_df):
        _, _, _, strength, _ = compute_trend_ribbon(sample_df)
        valid = strength.dropna()
        assert (valid >= 0).all(), "Strength should be >= 0"
        assert (valid <= 1).all(), "Strength should be <= 1"

    def test_width_varies_with_params(self, sample_df):
        """Wider max_width should produce a wider band on average."""
        _, upper_narrow, lower_narrow, _, _ = compute_trend_ribbon(
            sample_df, max_width=1.0
        )
        _, upper_wide, lower_wide, _, _ = compute_trend_ribbon(
            sample_df, max_width=5.0
        )
        valid = upper_narrow.dropna().index.intersection(upper_wide.dropna().index)
        narrow_avg = (upper_narrow[valid] - lower_narrow[valid]).mean()
        wide_avg = (upper_wide[valid] - lower_wide[valid]).mean()
        assert wide_avg > narrow_avg, "Larger max_width should give wider band"

    def test_center_is_ema(self, sample_df):
        """Center line should be close to the EMA of close prices."""
        center, _, _, _, _ = compute_trend_ribbon(sample_df, ema_period=21)
        ema = sample_df["Close"].ewm(span=21, adjust=False).mean()
        diff = (center - ema).abs()
        assert diff.max() < 1e-10, "Center should match EMA exactly"

    def test_nan_during_warmup(self, small_df):
        """Should have NaN values at the start during warmup period."""
        _, upper, lower, strength, _ = compute_trend_ribbon(small_df)
        assert pd.isna(upper.iloc[0]) or pd.isna(strength.iloc[0])

    def test_flip_passes_through_zero_width_neutral(self, sample_df):
        _, upper, lower, _, direction = compute_trend_ribbon(sample_df)
        width = (upper - lower).fillna(0)

        nonzero = direction[direction != 0]
        prev_dir = None
        for idx, curr_dir in nonzero.items():
            if prev_dir is not None and curr_dir != prev_dir:
                between = direction.loc[prev_idx:idx].iloc[1:-1]
                assert (between == 0).any(), "Direction flip must pass through neutral"
                zero_width = width.loc[between.index[between == 0]]
                assert (zero_width == 0).any(), "Neutral transition must collapse band width to zero"
            prev_dir = curr_dir
            prev_idx = idx

    def test_neutral_direction_has_zero_width(self, sample_df):
        _, upper, lower, _, direction = compute_trend_ribbon(sample_df)
        neutral = direction == 0
        width = (upper - lower).fillna(0)
        assert (width[neutral] == 0).all()

    def test_active_direction_keeps_width_floor(self, sample_df):
        _, upper, lower, _, direction = compute_trend_ribbon(sample_df)
        active = direction != 0
        width = (upper - lower).fillna(0)
        assert (width[active] > 0).all()

    def test_bearish_state_survives_same_side_softening(self):
        index = pd.date_range("2025-01-01", periods=180, freq="D")
        close = np.concatenate(
            [
                np.linspace(120.0, 80.0, 140),
                np.linspace(80.0, 80.8, 40),
            ]
        )
        df = pd.DataFrame(
            {
                "Open": close,
                "High": close + 1.5,
                "Low": close - 1.5,
                "Close": close,
                "Volume": np.full(len(index), 1000),
            },
            index=index,
        )

        _, upper, lower, _, direction = compute_trend_ribbon(df)

        assert (direction.iloc[-20:] == -1).all()
        assert ((upper - lower).iloc[-20:] > 0).all()
