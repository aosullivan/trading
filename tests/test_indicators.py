"""Tests for all technical indicator computations."""

import numpy as np
import pandas as pd
import pytest

from app import (
    compute_supertrend,
    compute_ma_confirmation,
    compute_ema_crossover,
    compute_macd_crossover,
    compute_donchian_breakout,
    compute_adx_trend,
    compute_bollinger_breakout,
    compute_keltner_breakout,
    compute_parabolic_sar,
    compute_cci_trend,
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
        # Different parameters should produce different results
        assert not st1.equals(st2)


class TestMAConfirmation:
    def test_returns_correct_shape(self, sample_df):
        ma, direction = compute_ma_confirmation(sample_df, ma_period=200, confirm_candles=3)
        assert len(ma) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, direction = compute_ma_confirmation(sample_df)
        unique = set(direction.unique())
        assert unique.issubset({-1, 0, 1})

    def test_ma_nan_during_warmup(self, sample_df):
        ma, _ = compute_ma_confirmation(sample_df, ma_period=200)
        assert pd.isna(ma.iloc[0])


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
        # Fast EMA should be closer to current price than slow
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


class TestADXTrend:
    def test_returns_correct_shape(self, sample_df):
        adx, plus_di, minus_di, direction = compute_adx_trend(sample_df)
        assert len(adx) == len(sample_df)
        assert len(direction) == len(sample_df)

    def test_direction_values(self, sample_df):
        _, _, _, direction = compute_adx_trend(sample_df)
        unique = set(direction.unique())
        assert unique.issubset({-1, 0, 1})


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
