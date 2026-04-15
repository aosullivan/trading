from lib.portfolio_research import (
    DEFAULT_MACRO_OVERLAY_CONFIGS,
    macro_overlay_matrix_catalog,
)


def test_macro_overlay_matrix_catalog_reports_expected_run_count():
    catalog = macro_overlay_matrix_catalog(
        strategies=["cci_hysteresis"],
        allocator_policies=["signal_top_n_strength_v1"],
        config_ids=[DEFAULT_MACRO_OVERLAY_CONFIGS[0]["id"]],
    )

    assert catalog["version"] == "macro_regime_overlay_matrix_v1"
    assert catalog["run_count"] == 9
    assert catalog["baseline"] == {
        "strategy": "cci_hysteresis",
        "allocator_policy": "signal_top_n_strength_v1",
    }
    assert catalog["configs"][0]["id"] == DEFAULT_MACRO_OVERLAY_CONFIGS[0]["id"]
