(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.ChartSupportResistance = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function getLevelEventTimes(level) {
    const pivotTimes = ((level && level.pivot_times) || []).filter(Number.isFinite);
    const touchTimes = ((level && level.touch_times) || []).filter(Number.isFinite);
    return {
      pivotTimes,
      touchTimes,
      allTimes: [...pivotTimes, ...touchTimes],
    };
  }

  function clampLogicalRange(candles, logicalRange) {
    let from = 0;
    let to = candles.length - 1;
    if (logicalRange) {
      from = Math.max(0, Math.floor(logicalRange.from));
      to = Math.min(candles.length - 1, Math.ceil(logicalRange.to));
    }
    return { from, to };
  }

  function getVisibleCandleRange(candles, logicalRange) {
    if (!candles || !candles.length) {
      return null;
    }
    const { from, to } = clampLogicalRange(candles, logicalRange);
    let low = Infinity;
    let high = -Infinity;
    for (let i = from; i <= to; i += 1) {
      const candle = candles[i];
      if (Number.isFinite(candle.low)) {
        low = Math.min(low, candle.low);
      }
      if (Number.isFinite(candle.high)) {
        high = Math.max(high, candle.high);
      }
    }
    if (!Number.isFinite(low) || !Number.isFinite(high)) {
      return null;
    }
    return {
      low,
      high,
      span: Math.max(high - low, Math.max(Math.abs(low), Math.abs(high)) * 0.01, 0.01),
    };
  }

  function levelAffectsAutoscale(level, visibleRange, bufferRatio) {
    const low = Number.isFinite(level == null ? void 0 : level.zone_low) ? level.zone_low : level == null ? void 0 : level.price;
    const high = Number.isFinite(level == null ? void 0 : level.zone_high) ? level.zone_high : level == null ? void 0 : level.price;
    if (!visibleRange || !Number.isFinite(low) || !Number.isFinite(high)) {
      return true;
    }
    const buffer = visibleRange.span * bufferRatio;
    return high >= visibleRange.low - buffer && low <= visibleRange.high + buffer;
  }

  function levelIsOnExpectedSide(level, type, currentPrice) {
    const low = Number.isFinite(level == null ? void 0 : level.zone_low) ? level.zone_low : level == null ? void 0 : level.price;
    const high = Number.isFinite(level == null ? void 0 : level.zone_high) ? level.zone_high : level == null ? void 0 : level.price;
    if (!Number.isFinite(currentPrice) || !Number.isFinite(low) || !Number.isFinite(high)) {
      return true;
    }
    if (type === "support") {
      return high < currentPrice;
    }
    if (type === "resistance") {
      return low > currentPrice;
    }
    return true;
  }

  function getVisibleTimeBounds(candles, logicalRange) {
    if (!candles || !candles.length) {
      return null;
    }
    const { from, to } = clampLogicalRange(candles, logicalRange);
    return {
      from: (candles[from] || candles[0]).time,
      to: (candles[to] || candles[candles.length - 1]).time,
    };
  }

  function recencyBeforeVisible(level, bounds) {
    const { allTimes: times } = getLevelEventTimes(level);
    if (!bounds || !times.length) {
      return Number.POSITIVE_INFINITY;
    }
    const priorTimes = times.filter((time) => time <= bounds.to);
    const reference = priorTimes.length ? Math.max(...priorTimes) : Math.min(...times);
    return Math.abs(bounds.to - reference);
  }

  function getLevelRenderStartTime(level, bounds) {
    const { pivotTimes, touchTimes } = getLevelEventTimes(level);
    const times = pivotTimes.length ? pivotTimes : touchTimes;
    if (!times.length) {
      return null;
    }
    if (!bounds) {
      return Math.max(...times);
    }
    const priorTimes = times.filter((time) => time <= bounds.to);
    return priorTimes.length ? Math.max(...priorTimes) : Math.max(...times);
  }

  function selectVisibleLevels(levels, type, candles, logicalRange, currentPrice, options) {
    const resolvedOptions = options || {};
    const bufferRatio = resolvedOptions.bufferRatio ?? 0.12;
    const maxVisible = resolvedOptions.maxVisible ?? 2;
    const visibleRange = getVisibleCandleRange(candles, logicalRange);
    const bounds = getVisibleTimeBounds(candles, logicalRange);
    return (levels || [])
      .filter((level) => level.type === type)
      .filter((level) => levelIsOnExpectedSide(level, type, currentPrice))
      .filter((level) => levelAffectsAutoscale(level, visibleRange, bufferRatio))
      .sort((left, right) => {
        const recencyDelta = recencyBeforeVisible(left, bounds) - recencyBeforeVisible(right, bounds);
        if (recencyDelta !== 0) {
          return recencyDelta;
        }
        return (right.touches || 0) - (left.touches || 0);
      })
      .slice(0, maxVisible);
  }

  return {
    getVisibleCandleRange,
    levelAffectsAutoscale,
    levelIsOnExpectedSide,
    getVisibleTimeBounds,
    recencyBeforeVisible,
    getLevelRenderStartTime,
    selectVisibleLevels,
  };
});
