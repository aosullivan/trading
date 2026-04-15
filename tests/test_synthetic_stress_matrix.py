from lib.portfolio_research import (
    DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS,
    SYNTHETIC_STRESS_MATRIX_VERSION,
    synthetic_stress_matrix_catalog,
)


def test_synthetic_stress_matrix_catalog_reports_expected_counts():
    catalog = synthetic_stress_matrix_catalog(
        strategies=["ribbon"],
        allocator_policies=["signal_top_n_strength_v1"],
        config_ids=DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS[:2],
        scenario_ids=["global_macro_crash_40"],
        upside_windows=["bull_recovery_2023_2025"],
    )

    assert catalog["version"] == SYNTHETIC_STRESS_MATRIX_VERSION
    assert catalog["run_count"] == 6
    assert catalog["upside_run_count"] == 6
    assert catalog["baseline"]["config_id"] == "macro63_high_core"
    assert [item["id"] for item in catalog["configs"]] == DEFAULT_SYNTHETIC_STRESS_CONFIG_IDS[:2]
    assert catalog["scenarios"][0]["id"] == "global_macro_crash_40"
