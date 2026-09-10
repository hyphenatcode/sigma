"""End-to-end pipeline tests: §3.3 recommendation -> §3.4 substitution -> execution.

The point of these is the *routing*: given a dataset, does the engine land on
the test the spec says it should, and does it say why when it changes course?
"""

import numpy as np
import pandas as pd
import pytest

from app.stats.enums import MeasurementLevel as ML
from app.stats.enums import ResearchTask as RT
from app.stats.pipeline import (
    AnalysisRequest,
    UnsupportedAnalysisError,
    run_analysis,
)

RATIO = ML.RATIO
NOMINAL = ML.NOMINAL


def request_for(**kwargs) -> AnalysisRequest:
    return AnalysisRequest(**kwargs)


# ---------------------------------------------------------------------------
# Happy paths: assumptions hold, §3.3's candidate is what runs
# ---------------------------------------------------------------------------

def test_independent_t_test_survives_its_assumptions(reference):
    frame = reference("ttest_independent.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
    ))

    assert outcome.recommendation.candidate == "independent_t_test"
    assert outcome.executed_analysis_type == "independent_t_test"
    assert outcome.substituted is False
    assert outcome.result.statistics["t"] == pytest.approx(7.197247, abs=1e-4)

    # §3.4: the checks that ran must be reported, met or not
    kinds = [a.assumption for a in outcome.assumption_results]
    assert kinds.count("normality") == 2
    assert "homogeneity_of_variance" in kinds


def test_one_way_anova_survives_its_assumptions(reference):
    frame = reference("anova_three_groups.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="kaygi_puani",
        independent_variables=["sinif_duzeyi"],
        measurement_levels={"kaygi_puani": RATIO, "sinif_duzeyi": NOMINAL},
    ))
    assert outcome.executed_analysis_type == "one_way_anova"
    assert outcome.result.statistics["F"] == pytest.approx(71.552795, abs=1e-4)


def test_paired_design_runs_paired_t_test(reference):
    frame = reference("ttest_paired.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, is_paired=True,
        paired_measurements=["on_test", "son_test"],
        measurement_levels={"on_test": RATIO, "son_test": RATIO},
    ))
    assert outcome.recommendation.candidate == "paired_t_test"
    assert outcome.executed_analysis_type == "paired_t_test"
    assert outcome.result.statistics["t"] == pytest.approx(-16.878647, abs=1e-4)
    # normality is tested on the differences, not on each measurement
    assert [a.group for a in outcome.assumption_results] == ["Fark puanları"]


def test_pearson_correlation_runs_when_both_variables_are_normal(reference):
    frame = reference("correlation_regression.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.RELATIONSHIP, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO},
    ))
    assert outcome.executed_analysis_type == "pearson_correlation"
    assert outcome.result.statistics["r"] == pytest.approx(0.997798, abs=1e-4)


def test_prediction_task_routes_to_regression(reference):
    frame = reference("correlation_regression.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO},
    ))
    assert outcome.executed_analysis_type == "simple_linear_regression"


def test_multiple_regression_routes_and_reports_vif(reference):
    frame = reference("multiple_regression.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati", "uyku_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO, "uyku_saati": RATIO},
    ))
    assert outcome.executed_analysis_type == "multiple_linear_regression"
    assert any(a.assumption == "multicollinearity" for a in outcome.assumption_results)


def test_chi_square_routes_and_reports_cell_counts(reference):
    frame = reference("chi_square.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="tercih",
        independent_variables=["cinsiyet"],
        measurement_levels={"tercih": NOMINAL, "cinsiyet": NOMINAL},
    ))
    assert outcome.executed_analysis_type == "chi_square_independence"
    assert outcome.result.statistics["chi2"] == pytest.approx(6.666667, abs=1e-4)
    assert outcome.assumption_results[0].assumption == "expected_cell_count"


def test_reliability_routes_to_cronbach(reference):
    frame = reference("reliability_scale.csv")
    items = [f"madde{i}" for i in range(1, 6)]
    outcome = run_analysis(frame, request_for(
        task=RT.SCALE_RELIABILITY, scale_items=items,
        measurement_levels={item: ML.ORDINAL for item in items},
    ))
    assert outcome.executed_analysis_type == "cronbachs_alpha"
    assert outcome.result.statistics["alpha"] == pytest.approx(0.963366, abs=1e-4)
    # §3.4 defines no assumption test here — say so rather than omit the section
    assert outcome.assumption_results[0].status.value == "not_applicable"


# ---------------------------------------------------------------------------
# §3.4 substitutions
# ---------------------------------------------------------------------------

def test_non_normal_data_falls_back_to_mann_whitney(reference):
    frame = reference("nonparametric_skewed.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="tepki_suresi",
        independent_variables=["grup"],
        measurement_levels={"tepki_suresi": RATIO, "grup": NOMINAL},
    ))

    assert outcome.recommendation.candidate == "independent_t_test"
    assert outcome.executed_analysis_type == "mann_whitney_u"
    assert outcome.substituted is True
    assert "Normallik" in outcome.substitution_reason_tr
    assert "Mann-Whitney" in outcome.substitution_reason_tr
    assert outcome.result.statistics["U"] == pytest.approx(16.0)
    # the note travels with the result, so the report can show it
    assert outcome.result.substitution_note_tr == outcome.substitution_reason_tr


def test_unequal_variances_switch_anova_to_welch(reference):
    frame = reference("anova_unequal_variance.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="memnuniyet",
        independent_variables=["bolum"],
        measurement_levels={"memnuniyet": RATIO, "bolum": NOMINAL},
    ))

    assert outcome.recommendation.candidate == "one_way_anova"
    assert outcome.executed_analysis_type == "welch_anova"
    assert outcome.substituted is True
    assert "Varyansların homojenliği" in outcome.substitution_reason_tr
    assert outcome.result.statistics["F"] == pytest.approx(66.523642, abs=1e-3)


def test_unequal_variances_switch_t_test_to_welch():
    """Two normal groups with very different spreads -> Welch's t (§3.4)."""
    rng = np.random.default_rng(20)
    frame = pd.DataFrame({
        "puan": np.r_[rng.normal(50, 2, 30), rng.normal(53, 16, 30)],
        "grup": ["A"] * 30 + ["B"] * 30,
    })
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="puan", independent_variables=["grup"],
        measurement_levels={"puan": RATIO, "grup": NOMINAL},
    ))
    assert outcome.executed_analysis_type in {"welch_t_test", "mann_whitney_u"}
    if outcome.executed_analysis_type == "welch_t_test":
        assert "Welch" in outcome.substitution_reason_tr


def test_non_normal_paired_differences_fall_back_to_wilcoxon():
    rng = np.random.default_rng(9)
    before = rng.normal(50, 5, 30)
    frame = pd.DataFrame({"once": before, "sonra": before - rng.exponential(3, 30)})
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, is_paired=True,
        paired_measurements=["once", "sonra"],
        measurement_levels={"once": RATIO, "sonra": RATIO},
    ))
    assert outcome.recommendation.candidate == "paired_t_test"
    assert outcome.executed_analysis_type == "wilcoxon_signed_rank"
    assert outcome.substituted is True


def test_non_normal_variables_fall_back_to_spearman():
    rng = np.random.default_rng(4)
    x = rng.exponential(2, 60)
    frame = pd.DataFrame({"x": x, "y": x * 2 + rng.exponential(1, 60)})
    outcome = run_analysis(frame, request_for(
        task=RT.RELATIONSHIP, dependent_variable="y", independent_variables=["x"],
        measurement_levels={"x": RATIO, "y": RATIO},
    ))
    assert outcome.recommendation.candidate == "pearson_correlation"
    assert outcome.executed_analysis_type == "spearman_correlation"
    assert outcome.substituted is True


def test_non_normal_three_groups_fall_back_to_kruskal_wallis():
    rng = np.random.default_rng(6)
    frame = pd.DataFrame({
        "y": np.r_[rng.exponential(1, 20), rng.exponential(2, 20), rng.exponential(3, 20)],
        "g": ["A"] * 20 + ["B"] * 20 + ["C"] * 20,
    })
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="y", independent_variables=["g"],
        measurement_levels={"y": RATIO, "g": NOMINAL},
    ))
    assert outcome.executed_analysis_type == "kruskal_wallis"
    assert "Kruskal-Wallis" in outcome.substitution_reason_tr


# ---------------------------------------------------------------------------
# §3.3 refusals reach the caller intact
# ---------------------------------------------------------------------------

def test_unsupported_combination_raises_with_turkish_reason(reference):
    frame = reference("ttest_independent.csv")
    with pytest.raises(UnsupportedAnalysisError) as excinfo:
        run_analysis(frame, request_for(
            task=RT.COMPARISON, dependent_variable="yontem",
            independent_variables=["basari_puani"],
            measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
        ))
    assert excinfo.value.message_tr
    assert "desteklenmiyor" in excinfo.value.message_tr


def test_repeated_measures_refusal_names_the_test():
    frame = pd.DataFrame({"t1": [1.0, 2, 3], "t2": [2.0, 3, 4], "t3": [3.0, 4, 5]})
    with pytest.raises(UnsupportedAnalysisError) as excinfo:
        run_analysis(frame, request_for(
            task=RT.COMPARISON, is_paired=True,
            paired_measurements=["t1", "t2", "t3"],
            measurement_levels={"t1": RATIO, "t2": RATIO, "t3": RATIO},
        ))
    assert "Tekrarlı Ölçümler ANOVA" in excinfo.value.message_tr


def test_missing_measurement_level_is_refused(reference):
    frame = reference("ttest_independent.csv")
    with pytest.raises(UnsupportedAnalysisError):
        run_analysis(frame, request_for(
            task=RT.COMPARISON, dependent_variable="basari_puani",
            independent_variables=["yontem"],
            measurement_levels={"basari_puani": RATIO},  # 'yontem' missing
        ))


def test_outcome_serialises_for_the_api(reference):
    frame = reference("ttest_independent.csv")
    outcome = run_analysis(frame, request_for(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
    ))
    payload = outcome.to_dict()
    assert payload["recommended_analysis_type"] == "independent_t_test"
    assert payload["executed_analysis_type"] == "independent_t_test"
    assert payload["result"]["effect_size"]["band"] == "large"
    assert payload["rule_path"]
