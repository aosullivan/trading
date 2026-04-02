from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "index.html"


def test_price_overlays_opt_out_of_autoscale():
    source = TEMPLATE_PATH.read_text()
    assert "autoscaleInfoProvider:()=>null" in source
    assert "sma200wSeries" in source
    assert "ribbonCenterSeries" in source


def test_support_resistance_autoscale_is_conditional():
    source = TEMPLATE_PATH.read_text()
    assert "if(!affectsAutoscale)" in source
    assert "centerLineOpts.autoscaleInfoProvider=()=>null" in source
    assert "if(showBand){" in source
    assert "bandOpts.autoscaleInfoProvider=()=>null" in source


def test_support_resistance_highlights_primary_level_and_demotes_secondary():
    source = TEMPLATE_PATH.read_text()
    assert "const showBand=isPrimary;" in source
    assert "showBand&&zoneCeiling>zoneFloor&&typeof chart.addBaselineSeries==='function'" in source
    assert "const centerLine=chart.addLineSeries(centerLineOpts);" in source
    assert "lineStyle:isPrimary?LightweightCharts.LineStyle.Solid:LightweightCharts.LineStyle.Dashed" in source


def test_support_resistance_primary_level_gets_axis_label():
    source = TEMPLATE_PATH.read_text()
    assert "const priceLine=isPrimary?candleSeries.createPriceLine({" in source
    assert "axisLabelVisible:true" in source
    assert "title:type==='support'?'SUP':'RES'" in source


def test_support_resistance_active_zone_uses_subtle_fill_without_boundary_lines():
    source = TEMPLATE_PATH.read_text()
    assert "const bandFill=type==='support'?'rgba(255,177,77,0.10)':'rgba(115,173,255,0.09)';" in source
    assert "upperEdge" not in source
    assert "lowerEdge" not in source


def test_template_uses_extracted_support_resistance_helper():
    source = TEMPLATE_PATH.read_text()
    assert "chart_support_resistance.js" in source
    assert "srHelpers.selectVisibleLevels" in source
    assert "srHelpers.getLevelRenderStartTime" in source


def test_default_visible_range_opens_30_percent_further_out():
    source = TEMPLATE_PATH.read_text()
    assert "const lookbackDays=interval==='1mo'?Math.round(365*8):interval==='1wk'?Math.round(365*1.69):Math.round(90*1.69);" in source


def test_template_exposes_monthly_interval_option_and_label():
    source = TEMPLATE_PATH.read_text()
    assert '<option value="1mo">1M</option>' in source
    assert "function intervalLabel(interval){" in source
    assert "if(interval==='1mo')return'Monthly';" in source


def test_template_exposes_trend_flip_pulse_controls():
    source = TEMPLATE_PATH.read_text()
    assert 'id="trend-flip-controls"' in source
    assert 'id="trend-flip-aggregate-btn"' in source
    assert 'id="trend-flip-aggregate-popover"' in source
    assert "function renderTrendFlipAggregate(){" in source
    assert "function toggleTrendFlipAggregate(e){" in source
    assert "Signal Pulse" in source


def test_template_updates_last_data_before_refreshing_trend_flip_ui():
    source = TEMPLATE_PATH.read_text()
    assert "lastData=data;\n    // Trend flip dates\n    updateFlipInfo();" in source
