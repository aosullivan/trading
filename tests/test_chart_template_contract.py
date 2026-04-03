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


def test_template_exposes_trend_flip_pulse_controls():
    toolbar_source = TOOLBAR_PARTIAL_PATH.read_text()
    signals_source = CHART_SIGNALS_JS_PATH.read_text()
    assert 'id="trend-flip-controls"' in toolbar_source
    assert 'id="trend-flip-aggregate-btn"' in toolbar_source
    assert 'id="trend-flip-aggregate-popover"' in toolbar_source
    assert "function renderTrendFlipAggregate(){" in signals_source
    assert "function toggleTrendFlipAggregate(e){" in signals_source
    assert "Signal Pulse" in signals_source


def test_template_updates_last_data_before_refreshing_trend_flip_ui():
    source = CHART_LOAD_JS_PATH.read_text()
    assert "lastData=data;\n    syncAutoMovingAverages();\n    // Trend flip dates\n    updateFlipInfo();" in source


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


def test_backtest_equity_chart_renders_buy_hold_comparison_series():
    core_source = CHART_CORE_JS_PATH.read_text()
    panel_source = BACKTEST_PANEL_JS_PATH.read_text()
    partial_source = BACKTEST_PANEL_PARTIAL_PATH.read_text()
    load_source = CHART_LOAD_JS_PATH.read_text()

    assert "btHoldSeries=btEquityChart.addLineSeries" in core_source
    assert "function renderEquityCurve(points,holdPoints,trades){" in panel_source
    assert "btHoldSeries.setData(holdPoints||[]);" in panel_source
    assert "btEquitySeries.setMarkers(buildBTTradeMarkers(trades));" in panel_source
    assert "Buy &amp; Hold" in partial_source
    compact_load_source = "".join(load_source.split())
    assert (
        "renderEquityCurve(s.equity_curve||[],lastData.buy_hold_equity_curve||[],s.trades||[]);"
        in compact_load_source
    )


def test_moving_average_legend_exposes_auto_and_100w_options():
    source = CHART_LEGEND_JS_PATH.read_text()
    assert "const MA_AUTO_KEY='maAuto';" in source
    assert "'1d':['sma50','sma100','sma200']" in source
    assert "'1wk':['sma50w','sma100w','sma200w']" in source
    assert "function syncAutoMovingAverages(){" in source
    assert "label:'100W MA'" in source
