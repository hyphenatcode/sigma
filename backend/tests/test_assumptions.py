"""§3.4 assumption-layer tests."""

import numpy as np
import pandas as pd

from app.stats import assumptions as assump
from app.stats.enums import AssumptionStatus


def test_shapiro_used_below_fifty_and_ks_at_or_above(reference):
    """§3.4: Shapiro-Wilk for n<50, Kolmogorov-Smirnov for n>=50."""
    rng = np.random.default_rng(0)
    small = assump.check_normality(rng.normal(0, 1, 49))
    large = assump.check_normality(rng.normal(0, 1, 50))

    assert small.test_name == "Shapiro-Wilk"
    assert large.test_name.startswith("Kolmogorov-Smirnov")


def test_normality_met_on_normal_data():
    rng = np.random.default_rng(42)
    result = assump.check_normality(rng.normal(100, 15, 40))
    assert result.status is AssumptionStatus.MET
    assert result.blocking is True
    assert "karşılanmaktadır" in result.message_tr


def test_normality_violated_on_skewed_data():
    rng = np.random.default_rng(42)
    result = assump.check_normality(rng.exponential(1.0, 45))
    assert result.status is AssumptionStatus.VIOLATED
    assert "karşılanmamaktadır" in result.message_tr


def test_normality_reported_not_skipped_when_it_cannot_run():
    """§3.4: never silently skip — a check that cannot run says so."""
    result = assump.check_normality([5.0, 5.0, 5.0, 5.0])
    assert result.status is AssumptionStatus.NOT_RUN
    assert result.detail["reason"] == "zero_variance"
    assert result.message_tr


def test_normality_by_group_returns_one_result_per_group(reference):
    frame = reference("anova_three_groups.csv")
    results = assump.check_normality_by_group(frame.kaygi_puani, frame.sinif_duzeyi)
    assert [r.group for r in results] == ["Doktora", "Lisans", "Yuksek Lisans"]
    assert all(r.assumption == "normality" for r in results)


def test_levene_met_on_equal_variances(reference):
    frame = reference("anova_three_groups.csv")
    samples = [g.kaygi_puani.to_numpy(float)
               for _, g in frame.groupby("sinif_duzeyi", sort=True)]
    result = assump.check_homogeneity(samples)
    assert result.status is AssumptionStatus.MET
    assert result.detail["center"] == "median"


def test_levene_violated_on_unequal_variances(reference):
    frame = reference("anova_unequal_variance.csv")
    samples = [g.memnuniyet.to_numpy(float)
               for _, g in frame.groupby("bolum", sort=True)]
    result = assump.check_homogeneity(samples)
    assert result.status is AssumptionStatus.VIOLATED
    assert result.p_value < 0.05


def test_vif_is_not_applicable_for_a_single_predictor():
    design = pd.DataFrame({"x": [1.0, 2, 3, 4, 5]})
    results = assump.check_multicollinearity(design)
    assert len(results) == 1
    assert results[0].status is AssumptionStatus.NOT_APPLICABLE


def test_vif_flags_collinear_predictors_without_blocking():
    """§3.4: VIF > 10 is a flag. x2 is x1 plus a whisper of noise."""
    rng = np.random.default_rng(1)
    x1 = rng.normal(0, 1, 60)
    design = pd.DataFrame({"x1": x1, "x2": x1 + rng.normal(0, 0.01, 60)})
    results = assump.check_multicollinearity(design)

    assert all(r.statistic > assump.VIF_THRESHOLD for r in results)
    assert all(r.status is AssumptionStatus.VIOLATED for r in results)
    assert all(r.blocking is False for r in results)


def test_breusch_pagan_flags_heteroscedasticity_without_blocking():
    rng = np.random.default_rng(5)
    x = np.linspace(1, 20, 120)
    # error variance grows with x — textbook heteroscedasticity
    resid = rng.normal(0, 1, 120) * x
    exog = np.column_stack([np.ones(120), x])
    result = assump.check_homoscedasticity(resid, exog)

    assert result.status is AssumptionStatus.VIOLATED
    assert result.blocking is False
    assert result.test_name == "Breusch-Pagan"


def test_linearity_never_blocks():
    """§3.4 explicitly says linearity is a visual flag in v1."""
    rng = np.random.default_rng(2)
    fitted = np.linspace(0, 10, 80)
    result = assump.check_linearity(rng.normal(0, 1, 80), fitted)
    assert result.blocking is False


def test_expected_cell_counts_threshold_is_five():
    met = assump.check_expected_cell_counts(np.array([[10.0, 12.0], [8.0, 9.0]]))
    violated = assump.check_expected_cell_counts(np.array([[10.0, 12.0], [8.0, 4.9]]))

    assert met.status is AssumptionStatus.MET
    assert violated.status is AssumptionStatus.VIOLATED
    assert violated.detail["cells_below_threshold"] == 1
    assert violated.blocking is False


def test_every_assumption_result_serialises_with_a_turkish_message():
    rng = np.random.default_rng(3)
    results = [
        assump.check_normality(rng.normal(0, 1, 30)),
        assump.check_homogeneity([rng.normal(0, 1, 20), rng.normal(0, 1, 20)]),
        assump.check_expected_cell_counts(np.array([[10.0, 10.0], [10.0, 10.0]])),
    ]
    for result in results:
        payload = result.to_dict()
        assert payload["message_tr"]
        assert payload["status"] in {s.value for s in AssumptionStatus}
