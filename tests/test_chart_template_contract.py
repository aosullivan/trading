from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "templates" / "index.html"
BACKTEST_TEMPLATE_PATH = ROOT / "templates" / "backtest.html"
TOOLBAR_PARTIAL_PATH = ROOT / "templates" / "partials" / "toolbar.html"
BACKTEST_PANEL_PARTIAL_PATH = ROOT / "templates" / "partials" / "backtest_panel.html"
CHART_CORE_JS_PATH = ROOT / "static" / "js" / "chart_core.js"
CHART_LEGEND_JS_PATH = ROOT / "static" / "js" / "chart_legend.js"
CHART_LOAD_JS_PATH = ROOT / "static" / "js" / "chart_load.js"
CHART_SIGNALS_JS_PATH = ROOT / "static" / "js" / "chart_signals.js"
CHART_SR_JS_PATH = ROOT / "static" / "js" / "chart_sr.js"
BACKTEST_PANEL_JS_PATH = ROOT / "static" / "js" / "backtest_panel.js"
BACKTEST_REPORT_JS_PATH = ROOT / "static" / "js" / "backtest_report.js"
WATCHLIST_PARTIAL_PATH = ROOT / "templates" / "partials" / "watchlist.html"
WATCHLIST_JS_PATH = ROOT / "static" / "js" / "watchlist.js"


def test_price_overlays_opt_out_of_autoscale():
    source = CHART_CORE_JS_PATH.read_text()
    assert "autoscaleInfoProvider:()=>null" in source
    assert "sma200wSeries" in source
    assert "sma100wSeries" in source
    assert "ribbonCenterSeries" in source


def test_support_resistance_autoscale_is_conditional():
    source = CHART_SR_JS_PATH.read_text()
    assert "if(!affectsAutoscale)" in source
    assert "centerLineOpts.autoscaleInfoProvider=()=>null" in source
    assert "if(showBand){" in source
    assert "bandOpts.autoscaleInfoProvider=()=>null" in source


def test_support_resistance_highlights_primary_level_and_demotes_secondary():
    source = CHART_SR_JS_PATH.read_text()
    assert "const showBand=isPrimary;" in source
    assert "showBand&&zoneCeiling>zoneFloor&&typeof chart.addBaselineSeries==='function'" in source
    assert "const centerLine=chart.addLineSeries(centerLineOpts);" in source
    assert "lineStyle:isPrimary?LightweightCharts.LineStyle.Solid:LightweightCharts.LineStyle.Dashed" in source


def test_support_resistance_primary_level_gets_axis_label():
    source = CHART_SR_JS_PATH.read_text()
    assert "const priceLine=isPrimary?candleSeries.createPriceLine({" in source
    assert "axisLabelVisible:true" in source
    assert "title:type==='support'?'SUP':'RES'" in source


def test_support_resistance_active_zone_uses_subtle_fill_without_boundary_lines():
    source = CHART_SR_JS_PATH.read_text()
    assert "const bandFill=type==='support'?'rgba(255,177,77,0.10)':'rgba(115,173,255,0.09)';" in source
    assert "upperEdge" not in source
    assert "lowerEdge" not in source


def test_template_uses_extracted_support_resistance_helper():
    template_source = TEMPLATE_PATH.read_text()
    sr_source = CHART_SR_JS_PATH.read_text()
    assert "chart_support_resistance.js" in template_source
    assert "srHelpers.selectVisibleLevels" in sr_source
    assert "srHelpers.getLevelRenderStartTime" in sr_source


def test_default_visible_range_opens_30_percent_further_out():
    source = CHART_CORE_JS_PATH.read_text()
    assert "const lookbackDays=interval==='1mo'?Math.round(365*8):interval==='1wk'?Math.round(365*1.69):Math.round(90*1.69);" in source


def test_template_exposes_monthly_interval_option_and_label():
    toolbar_source = TOOLBAR_PARTIAL_PATH.read_text()
    core_source = CHART_CORE_JS_PATH.read_text()
    assert '<option value="1mo">1M</option>' in toolbar_source
    assert "function intervalLabel(interval){" in core_source
    assert "if(interval==='1mo')return'Monthly';" in core_source


def test_toolbar_exposes_range_presets_and_default_reset():
    toolbar_source = TOOLBAR_PARTIAL_PATH.read_text()
    core_source = CHART_CORE_JS_PATH.read_text()

    assert "chartRangePresetYears(1)" in toolbar_source
    assert "chartRangePresetYears(3)" in toolbar_source
    assert "chartRangePresetYears(5)" in toolbar_source
    assert "chartRangePresetReset()" in toolbar_source
    assert "function chartRangePresetYears(years){" in core_source
    assert "function chartRangePresetReset(){" in core_source


def test_template_exposes_trend_flip_pulse_controls():
    toolbar_source = TOOLBAR_PARTIAL_PATH.read_text()
    template_source = TEMPLATE_PATH.read_text()
    signals_source = CHART_SIGNALS_JS_PATH.read_text()
    assert 'id="trend-flip-controls"' in toolbar_source
    assert 'id="trend-flip-aggregate-btn"' in toolbar_source
    assert 'id="trend-flip-aggregate-popover"' in toolbar_source
    assert "strategy_preference_helpers.js" in template_source
    assert "trend_pulse_helpers.js" in template_source
    assert "function renderTrendFlipAggregate(){" in signals_source
    assert "function toggleTrendFlipAggregate(e){" in signals_source
    assert "Signal Pulse" in signals_source
    assert "function fallbackFlipKey(frameFlips){" in signals_source
    assert "usingFallback:true" in signals_source
    assert "fallback`:`${sourceLabel}`" in signals_source


def test_template_updates_last_data_before_refreshing_trend_flip_ui():
    source = CHART_LOAD_JS_PATH.read_text()
    last_data_pos = source.index("lastData=data;")
    sync_pos = source.index("syncAutoMovingAverages();", last_data_pos)
    flip_pos = source.index("updateFlipInfo();", sync_pos)
    assert last_data_pos < sync_pos < flip_pos


def test_chart_load_uses_strategy_only_shared_path_and_lazy_strategy_fetches():
    source = CHART_LOAD_JS_PATH.read_text()

    assert "const candlesUrl=buildChartRequestUrl" in source
    assert "candlesOnly:true" in source
    assert "cancelWatchlistChartPreload" in source
    assert "applyCandlesPayload(ticker,interval,period,mult,candleData);" in source
    assert "include_shared=1" in source
    assert "function applySharedChartPayload" in source
    assert "async function loadStrategyPayload(name){" in source
    assert "async function switchStrategy(name){" in source


def test_stale_chart_loads_release_backtest_loading_counter():
    source = CHART_LOAD_JS_PATH.read_text()

    stale_return_pos = source.index("if(!candlesLoaded||requestToken!==chartLoadRequestToken){")
    stale_release_pos = source.index("setBacktestLoading(false)", stale_return_pos)
    stale_current_check_pos = source.index("if(requestToken===chartLoadRequestToken){", stale_return_pos)
    strategy_finally_pos = source.index("finally{", source.index("const data=await fetch(selectedStrategyUrl)"))
    strategy_release_pos = source.index("setBacktestLoading(false)", strategy_finally_pos)
    strategy_current_check_pos = source.index("if(requestToken===chartLoadRequestToken){", strategy_finally_pos)

    assert stale_release_pos < stale_current_check_pos
    assert strategy_release_pos < strategy_current_check_pos


def test_watchlist_neighbour_preload_uses_lightweight_chart_paths():
    source = WATCHLIST_JS_PATH.read_text()

    assert "function queueWatchlistChartPreload" in source
    assert "function cancelWatchlistChartPreload" in source
    assert "cancelWatchlistChartPreload();" in source
    assert "document.getElementById('loading')?.classList.contains('on')" in source
    assert "candlesOnly:true" in source
    assert "strategyOnly:true" in source
    assert "includeShared:true" in source
    assert "cache_only=1&prewarm=1" in source
    assert "candlesOnly:false" not in source


def test_backtest_launches_in_new_tab_and_standalone_page_uses_report_script():
    template_source = TEMPLATE_PATH.read_text()
    report_source = BACKTEST_TEMPLATE_PATH.read_text()
    partial_source = BACKTEST_PANEL_PARTIAL_PATH.read_text()
    panel_js_source = BACKTEST_PANEL_JS_PATH.read_text()
    report_js_source = BACKTEST_REPORT_JS_PATH.read_text()

    assert 'onclick="openBacktestTab()"' in template_source
    assert 'data-backtest-mode="standalone"' in report_source
    assert "backtest_report.js" in report_source
    assert 'onclick="closeBacktestView()"' in partial_source
    assert "function openBacktestTab(){" in panel_js_source
    assert "function loadBacktestReport(){" in report_js_source


def test_backtest_panel_has_shared_loading_and_ready_status():
    partial_source = BACKTEST_PANEL_PARTIAL_PATH.read_text()
    panel_source = BACKTEST_PANEL_JS_PATH.read_text()

    assert 'id="bt-head-indicator"' in partial_source
    assert 'id="bt-head-loading-txt"' in partial_source
    assert 'id="bt-loading-label"' in partial_source
    assert "function setBacktestLoading(isLoading){" in panel_source
    assert "headLabel.textContent=loading?'Updating…':'Ready';" in panel_source
    assert "bodyLabel.textContent=loading?'Updating backtest…':'Backtest ready';" in panel_source
    assert 'id="bt-window-hint"' in partial_source
    assert "Managed sizing compares only entries that begin inside the selected range." in panel_source


def test_backtest_equity_chart_renders_buy_hold_comparison_series():
    core_source = CHART_CORE_JS_PATH.read_text()
    panel_source = BACKTEST_PANEL_JS_PATH.read_text()
    partial_source = BACKTEST_PANEL_PARTIAL_PATH.read_text()
    load_source = CHART_LOAD_JS_PATH.read_text()

    assert "btPriceSeries=btEquityChart.addCandlestickSeries" in core_source
    assert "leftPriceScale:{visible:true" in "".join(core_source.split())
    assert "priceScaleId:'left'" in core_source
    assert "btHoldSeries=btEquityChart.addLineSeries" in core_source
    assert "function renderEquityCurve(points,holdPoints,trades){" in panel_source
    assert "btPriceSeries.setData(_lastCandles&&_lastCandles.length?_lastCandles:[]);" in panel_source
    assert "btHoldSeries.setData(holdPoints||[]);" in panel_source
    assert "btEquitySeries.setMarkers(buildBTTradeMarkers(trades));" in panel_source
    assert "Asset Price" in partial_source
    assert "Buy &amp; Hold" in partial_source
    compact_load_source = "".join(load_source.split())
    assert (
        "renderEquityCurve(s.equity_curve||[],s.buy_hold_equity_curve||lastData.buy_hold_equity_curve||[],s.trades||[]);"
        in compact_load_source
    )


def test_moving_average_legend_exposes_auto_and_100w_options():
    source = CHART_LEGEND_JS_PATH.read_text()
    assert "const MA_AUTO_KEY='maAuto';" in source
    assert "'1d':['sma50','sma100','sma200']" in source
    assert "'1wk':['sma50w','sma100w','sma200w']" in source
    assert "function syncAutoMovingAverages(){" in source
    assert "label:'100W MA'" in source


def test_watchlist_trends_shows_strength_and_trade_score_columns():
    partial_source = WATCHLIST_PARTIAL_PATH.read_text()
    watchlist_source = WATCHLIST_JS_PATH.read_text()

    assert 'data-side="all"' in partial_source
    assert ">All</button>" in partial_source
    assert "Strength" in partial_source
    assert "Trade Score" in partial_source
    assert "WL_TREND_SORT_KEYS=['ticker','flip','strength','score']" in watchlist_source
    assert "wlTrendSortKey==='strength'" in watchlist_source
    assert "openWatchlistTradeScore" in watchlist_source
    assert "openWatchlistActionStrength" in watchlist_source


def test_watchlist_trends_normalizes_preferred_strategy_payload_shape():
    watchlist_source = WATCHLIST_JS_PATH.read_text()

    assert "function wlNormalizePreferredStrategyMeta(meta,ticker){" in watchlist_source
    assert "meta?.strategy_key" in watchlist_source
    assert "strategyKey:meta.strategy_key" in watchlist_source
    assert "const preferredStrategy=wlResolvePreferredStrategyMeta(row,flips);" in watchlist_source


def test_watchlist_quotes_retry_and_show_syncing_until_prices_arrive():
    watchlist_source = WATCHLIST_JS_PATH.read_text()

    assert "const WL_QUOTES_RETRY_MS=4000;" in watchlist_source
    assert "let wlQuotesLoading=false;" in watchlist_source
    assert "let wlQuotesReady=false;" in watchlist_source
    assert "function scheduleWLQuoteRetry(){" in watchlist_source
    assert "wlQuotesLoading||(wlView==='watchlist'&&wlList.length&&!wlQuotesReady)" in watchlist_source
    assert "if(!Array.isArray(quotes))throw new Error('Watchlist quotes payload was not an array');" in watchlist_source
    assert "if((!quotes.length&&wlList.length)||hasMissingQuote||(!hasAnyQuote&&wlList.length)){" in watchlist_source


def test_watchlist_trend_side_filter_supports_all_mode():
    watchlist_source = WATCHLIST_JS_PATH.read_text()

    assert "const WL_DEFAULT_TREND_SIDE='all';" in watchlist_source
    assert "let wlTrendSide='all';" in watchlist_source
    assert "['all','bullish','bearish','mixed']" in watchlist_source
    assert "if(wlTrendSide==='all')return true;" in watchlist_source


def test_index_includes_trade_score_modal_assets():
    index_source = TEMPLATE_PATH.read_text()
    modal_source = (ROOT / "templates" / "partials" / "trade_score_modal.html").read_text()
    modal_js_source = (ROOT / "static" / "js" / "trade_score_modal.js").read_text()

    assert "partials/trade_score_modal.html" in index_source
    assert "js/trade_score_modal.js" in index_source
    assert 'id="trade-score-modal"' in modal_source
    assert "function openTradeScoreDetails" in modal_js_source
    assert "TRADE_SCORE_FORMULA_TEXT" in modal_js_source
    assert "tradeScoreBreakdown" in modal_js_source
    assert "tradeScoreActionStrength" in modal_js_source
    assert 'id="trade-score-action-strength"' in modal_source
