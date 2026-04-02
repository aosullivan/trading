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
    assert "bandOpts.autoscaleInfoProvider=()=>null" in source


def test_support_resistance_uses_shaded_band_and_single_center_line():
    source = TEMPLATE_PATH.read_text()
    assert "chart.addBaselineSeries(bandOpts)" in source
    assert "const centerLine=chart.addLineSeries(centerLineOpts);" in source
    assert "upperDotted" not in source
    assert "lowerDotted" not in source


def test_template_uses_extracted_support_resistance_helper():
    source = TEMPLATE_PATH.read_text()
    assert "chart_support_resistance.js" in source
    assert "srHelpers.selectVisibleLevels" in source
    assert "srHelpers.getLevelRenderStartTime" in source
