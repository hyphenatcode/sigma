"""Reference-dataset tests for every statistical procedure (§5, §8).

Each expected value below was derived independently of the engine — by writing
the textbook formula out directly against the fixture (see the docstring on each
test for the arithmetic) — so a test failing here means the engine disagrees
with the definition, not merely with itself.

This is the highest-priority NFR in §5: correctness over coverage.
"""

import numpy as np
import pytest

from app.stats.procedures.associations import (
    chi_square_independence,
    correlation,
    cronbachs_alpha,
    linear_regression,
)
from app.stats.procedures.comparisons import (
    independent_t_test,
    kruskal_wallis,
    mann_whitney_u,
    one_way_anova,
    paired_t_test,
    wilcoxon_signed_rank,
)
from app.stats.results import InsufficientDataError

TOL = 1e-4


# ---------------------------------------------------------------------------
# Independent samples t-test — ttest_independent.csv
#   Deney   n=10, M=84.00, SD=5.0111
#   Kontrol n=10, M=70.30, SD=3.3350
#   SD_pooled = sqrt((9*25.111 + 9*11.122)/18) = 4.2564
#   t = (84.00-70.30) / (4.2564*sqrt(1/10+1/10)) = 7.197247, df=18
#   d = 13.70/4.2564 = 3.218707  -> "large" (>= 0.8)
# ---------------------------------------------------------------------------

def test_independent_t_test_matches_reference(reference):
    frame = reference("ttest_independent.csv")
    deney = frame[frame.yontem == "Deney"].basari_puani
    kontrol = frame[frame.yontem == "Kontrol"].basari_puani

    result = independent_t_test(deney, kontrol, labels=("Deney", "Kontrol"))

    assert result.analysis_type == "independent_t_test"
    assert result.statistics["t"] == pytest.approx(7.197247, abs=TOL)
    assert result.df["df"] == pytest.approx(18.0)
    assert result.p_value == pytest.approx(1.0678e-06, rel=1e-3)
    assert result.statistics["mean_difference"] == pytest.approx(13.7, abs=TOL)
    assert result.effect_size.value == pytest.approx(3.218707, abs=TOL)
    assert result.effect_size.band.value == "large"
    assert result.n_total == 20

    d1, d2 = result.descriptives
    assert (d1.label, d1.n) == ("Deney", 10)
    assert d1.mean == pytest.approx(84.0, abs=TOL)
    assert d1.sd == pytest.approx(5.011099, abs=TOL)
    assert d2.mean == pytest.approx(70.3, abs=TOL)
    assert d2.sd == pytest.approx(3.335000, abs=TOL)


def test_welch_t_test_uses_satterthwaite_df(reference):
    """Welch's df must be the Satterthwaite value, not the pooled df=18.

    var1 = 226/9 = 25.111111, var2 = 100.1/9 = 11.122222
    v1 = var1/10 = 2.5111111, v2 = var2/10 = 1.1122222
    df = (v1+v2)^2 / (v1^2/9 + v2^2/9)
       = 13.128545 / 0.838080 = 15.665031
    """
    frame = reference("ttest_independent.csv")
    result = independent_t_test(
        frame[frame.yontem == "Deney"].basari_puani,
        frame[frame.yontem == "Kontrol"].basari_puani,
        equal_var=False,
    )
    assert result.analysis_type == "welch_t_test"
    assert result.df["df"] == pytest.approx(15.665031, abs=1e-4)
    assert result.extra["equal_variance_assumed"] is False


# ---------------------------------------------------------------------------
# Paired samples t-test — ttest_paired.csv
#   n=12, M_pre=59.5833, M_post=70.6667
#   M_diff = -11.083333, SD_diff = 2.274696
#   t = -11.083333 / (2.274696/sqrt(12)) = -16.878647, df=11
#   d_z = -11.083333/2.274696 = -4.872446 -> "large"
# ---------------------------------------------------------------------------

def test_paired_t_test_matches_reference(reference):
    frame = reference("ttest_paired.csv")
    result = paired_t_test(frame.on_test, frame.son_test, labels=("Ön test", "Son test"))

    assert result.statistics["t"] == pytest.approx(-16.878647, abs=TOL)
    assert result.df["df"] == pytest.approx(11.0)
    assert result.p_value == pytest.approx(3.2718e-09, rel=1e-3)
    assert result.statistics["mean_difference"] == pytest.approx(-11.083333, abs=TOL)
    assert result.extra["sd_difference"] == pytest.approx(2.274696, abs=TOL)
    assert result.effect_size.value == pytest.approx(-4.872446, abs=TOL)
    assert result.effect_size.band.value == "large"
    assert result.n_total == 12


def test_paired_t_test_rejects_unequal_lengths():
    with pytest.raises(InsufficientDataError):
        paired_t_test([1, 2, 3], [1, 2])


# ---------------------------------------------------------------------------
# One-way ANOVA — anova_three_groups.csv
#   Doktora M=58.1667, Lisans M=42.1667, Yuksek Lisans M=50.1667 (n=6 each)
#   SS_between = 768.0, SS_within = 80.5
#   F = (768/2)/(80.5/15) = 71.552795, df=(2,15)
#   eta^2 = 768/848.5 = 0.905127 -> "large"
# ---------------------------------------------------------------------------

def test_one_way_anova_matches_reference(reference):
    frame = reference("anova_three_groups.csv")
    result = one_way_anova(frame.kaygi_puani, frame.sinif_duzeyi)

    assert result.statistics["F"] == pytest.approx(71.552795, abs=TOL)
    assert result.statistics["ss_between"] == pytest.approx(768.0, abs=TOL)
    assert result.statistics["ss_within"] == pytest.approx(80.5, abs=TOL)
    assert result.df["df_between"] == pytest.approx(2.0)
    assert result.df["df_within"] == pytest.approx(15.0)
    assert result.p_value == pytest.approx(2.131e-08, rel=1e-3)
    assert result.effect_size.value == pytest.approx(0.905127, abs=TOL)
    assert result.effect_size.band.value == "large"
    assert [d.label for d in result.descriptives] == ["Doktora", "Lisans", "Yuksek Lisans"]
    assert result.n_total == 18


def test_welch_anova_matches_reference(reference):
    """anova_unequal_variance.csv: normal within group, wildly unequal spreads."""
    frame = reference("anova_unequal_variance.csv")
    result = one_way_anova(frame.memnuniyet, frame.bolum, equal_var=False)

    assert result.analysis_type == "welch_anova"
    assert result.statistics["F"] == pytest.approx(66.523642, abs=1e-3)
    assert result.df["df_between"] == pytest.approx(2.0)
    assert result.df["df_within"] == pytest.approx(11.848525, abs=1e-3)
    # eta^2 still comes from the ordinary SS decomposition
    assert result.effect_size.value == pytest.approx(0.167224, abs=TOL)


def test_one_way_anova_requires_three_groups(reference):
    frame = reference("ttest_independent.csv")
    with pytest.raises(InsufficientDataError):
        one_way_anova(frame.basari_puani, frame.yontem)


# ---------------------------------------------------------------------------
# Mann-Whitney U — nonparametric_skewed.csv
#   n1=n2=10, U(group A)=16.0, p=0.011207
#   r_rb = 2*16/100 - 1 = -0.68 -> "large" magnitude, negative direction
# ---------------------------------------------------------------------------

def test_mann_whitney_matches_reference(reference):
    frame = reference("nonparametric_skewed.csv")
    a = frame[frame.grup == "A"].tepki_suresi
    b = frame[frame.grup == "B"].tepki_suresi

    result = mann_whitney_u(a, b, labels=("A", "B"))
    assert result.statistics["U"] == pytest.approx(16.0)
    assert result.p_value == pytest.approx(0.011207, abs=1e-5)
    assert result.effect_size.value == pytest.approx(-0.68, abs=TOL)
    assert result.effect_size.band.value == "large"
    # mean ranks must partition the 1..20 rank sum of 210
    assert (result.descriptives[0].mean_rank * 10
            + result.descriptives[1].mean_rank * 10) == pytest.approx(210.0, abs=TOL)


def test_kruskal_wallis_matches_reference(reference):
    """anova_three_groups.csv has perfectly separated groups.

    All 6 Lisans scores rank below all 6 Yuksek Lisans, which rank below all 6
    Doktora, so H is at its maximum for k=3, n=18:
      H = 12/(N(N+1)) * sum(R_i^2/n_i) - 3(N+1)
        = 12/(18*19) * (21^2+57^2+93^2)/6 - 57 = 15.157895
      eps^2 = H*(N+1)/(N^2-1) = 15.157895*19/323 = 0.891641
    """
    frame = reference("anova_three_groups.csv")
    result = kruskal_wallis(frame.kaygi_puani, frame.sinif_duzeyi)

    assert result.statistics["H"] == pytest.approx(15.157895, abs=TOL)
    assert result.df["df"] == pytest.approx(2.0)
    assert result.effect_size.value == pytest.approx(0.891641, abs=TOL)
    assert result.effect_size.band.value == "large"


def test_wilcoxon_signed_rank_matches_reference(reference):
    """ttest_paired.csv: every post score exceeds its pre score, so all 12
    signed ranks are negative -> W = 0 and r_rb = -1 (a perfect shift)."""
    frame = reference("ttest_paired.csv")
    result = wilcoxon_signed_rank(frame.on_test, frame.son_test)

    assert result.statistics["W"] == pytest.approx(0.0)
    assert result.statistics["W_positive"] == pytest.approx(0.0)
    assert result.statistics["W_negative"] == pytest.approx(78.0)  # 1+2+...+12
    assert result.effect_size.value == pytest.approx(-1.0, abs=TOL)
    assert result.p_value < 0.05


# ---------------------------------------------------------------------------
# Correlation — correlation_regression.csv
#   n=12, r = 0.997798, df=10, p = 4.06e-13
# ---------------------------------------------------------------------------

def test_pearson_correlation_matches_reference(reference):
    frame = reference("correlation_regression.csv")
    result = correlation(frame.calisma_saati, frame.sinav_puani,
                         labels=("Çalışma saati", "Sınav puanı"))

    assert result.analysis_type == "pearson_correlation"
    assert result.statistics["r"] == pytest.approx(0.997798, abs=TOL)
    assert result.df["df"] == pytest.approx(10.0)
    assert result.p_value == pytest.approx(4.0601e-13, rel=1e-2)
    # §3.5: r is itself the effect size
    assert result.effect_size.value == pytest.approx(result.statistics["r"], abs=1e-12)
    assert result.effect_size.band.value == "large"


def test_spearman_correlation_matches_reference(reference):
    """calisma_saati is strictly increasing with sinav_puani, so rho = 1.0."""
    frame = reference("correlation_regression.csv")
    result = correlation(frame.calisma_saati, frame.sinav_puani, method="spearman")

    assert result.analysis_type == "spearman_correlation"
    assert result.statistics["rho"] == pytest.approx(1.0, abs=TOL)


# ---------------------------------------------------------------------------
# Simple linear regression — correlation_regression.csv
#   b = Sxy/Sxx = 4.059441, a = 44.137529
#   R^2 = r^2 = 0.995601, adj R^2 = 0.995161, F(1,10) = 2263.384641
# ---------------------------------------------------------------------------

def test_simple_linear_regression_matches_reference(reference):
    frame = reference("correlation_regression.csv")
    result = linear_regression(frame.sinav_puani, frame[["calisma_saati"]],
                               dv_label="sinav_puani")

    assert result.analysis_type == "simple_linear_regression"
    assert result.statistics["intercept"] == pytest.approx(44.137529, abs=TOL)
    assert result.statistics["r_squared"] == pytest.approx(0.995601, abs=TOL)
    assert result.statistics["adjusted_r_squared"] == pytest.approx(0.995161, abs=TOL)
    assert result.statistics["F"] == pytest.approx(2263.384641, abs=1e-3)
    assert result.df["df_model"] == pytest.approx(1.0)
    assert result.df["df_residual"] == pytest.approx(10.0)

    coefficient = result.extra["coefficients"][0]
    assert coefficient["predictor"] == "calisma_saati"
    assert coefficient["b"] == pytest.approx(4.059441, abs=TOL)
    # with a single predictor the standardised beta equals Pearson r
    assert coefficient["beta"] == pytest.approx(0.997798, abs=TOL)

    # §3.5: R^2 is reported, never banded
    assert result.effect_size.band.value == "not_banded"
    # §3.4 regression diagnostics must be present and non-blocking
    kinds = {a.assumption for a in result.assumption_results}
    assert {"linearity", "homoscedasticity", "multicollinearity"} <= kinds
    assert all(not a.blocking for a in result.assumption_results)


# ---------------------------------------------------------------------------
# Multiple linear regression — multiple_regression.csv (solved via normal
# equations: b = (X'X)^-1 X'y)
#   intercept = 26.072403, b_calisma = 3.878496, b_uyku = 2.756450
#   R^2 = 0.996865, adj = 0.996342, F(2,12) = 1907.806086
#   VIF = 1/(1-r12^2) with r12 = 0.387825 -> 1.177036
# ---------------------------------------------------------------------------

def test_multiple_linear_regression_matches_reference(reference):
    frame = reference("multiple_regression.csv")
    result = linear_regression(frame.sinav_puani,
                               frame[["calisma_saati", "uyku_saati"]],
                               dv_label="sinav_puani")

    assert result.analysis_type == "multiple_linear_regression"
    assert result.statistics["intercept"] == pytest.approx(26.072403, abs=TOL)
    assert result.statistics["r_squared"] == pytest.approx(0.996865, abs=TOL)
    assert result.statistics["adjusted_r_squared"] == pytest.approx(0.996342, abs=TOL)
    assert result.statistics["F"] == pytest.approx(1907.806086, abs=1e-2)
    assert result.df["df_model"] == pytest.approx(2.0)
    assert result.df["df_residual"] == pytest.approx(12.0)
    assert result.statistics["std_error_of_estimate"] == pytest.approx(0.877606, abs=TOL)

    by_name = {c["predictor"]: c for c in result.extra["coefficients"]}
    assert by_name["calisma_saati"]["b"] == pytest.approx(3.878496, abs=TOL)
    assert by_name["uyku_saati"]["b"] == pytest.approx(2.756450, abs=TOL)
    assert by_name["calisma_saati"]["se"] == pytest.approx(0.075524, abs=TOL)
    assert by_name["calisma_saati"]["beta"] == pytest.approx(0.900548, abs=TOL)
    assert by_name["uyku_saati"]["beta"] == pytest.approx(0.205593, abs=TOL)

    vifs = [a for a in result.assumption_results if a.assumption == "multicollinearity"]
    assert len(vifs) == 2
    assert all(v.statistic == pytest.approx(1.177036, abs=1e-3) for v in vifs)
    assert all(v.status.value == "met" for v in vifs)


# ---------------------------------------------------------------------------
# Chi-square — chi_square.csv
#   2x2 table, all four expected counts = 15, n = 60
#   chi2 = 4 * (5^2/15) = 6.666667, df = 1, p = 0.009823
#   V = sqrt(6.666667/(60*1)) = 0.333333 -> "medium" (df* = 1 -> .1/.3/.5)
# ---------------------------------------------------------------------------

def test_chi_square_matches_reference(reference):
    frame = reference("chi_square.csv")
    result = chi_square_independence(frame.cinsiyet, frame.tercih,
                                     labels=("cinsiyet", "tercih"))

    assert result.statistics["chi2"] == pytest.approx(6.666667, abs=TOL)
    assert result.df["df"] == pytest.approx(1.0)
    assert result.p_value == pytest.approx(0.009823, abs=1e-5)
    assert result.n_total == 60
    assert result.effect_size.value == pytest.approx(0.333333, abs=TOL)
    assert result.effect_size.band.value == "medium"
    assert result.extra["yates_correction_applied"] is False

    cells = result.assumption_results[0]
    assert cells.assumption == "expected_cell_count"
    assert cells.status.value == "met"
    assert cells.detail["min_expected"] == pytest.approx(15.0)


def test_chi_square_flags_sparse_cells_without_blocking():
    """§3.4: an expected count below 5 is a flag, not a blocker."""
    rows = ["A"] * 10 + ["B"] * 4
    cols = ["X"] * 5 + ["Y"] * 5 + ["X"] * 2 + ["Y"] * 2
    result = chi_square_independence(rows, cols)

    cells = result.assumption_results[0]
    assert cells.status.value == "violated"
    assert cells.blocking is False
    assert "Fisher" in cells.message_tr


# ---------------------------------------------------------------------------
# Cronbach's alpha — reliability_scale.csv
#   k=5, n=15, sum of item variances = 7.123810, variance of totals = 31.066667
#   alpha = 5/4 * (1 - 7.123810/31.066667) = 0.963366
# ---------------------------------------------------------------------------

def test_cronbachs_alpha_matches_reference(reference):
    frame = reference("reliability_scale.csv")
    items = frame[[f"madde{i}" for i in range(1, 6)]]
    result = cronbachs_alpha(items)

    assert result.statistics["alpha"] == pytest.approx(0.963366, abs=TOL)
    assert result.statistics["n_items"] == pytest.approx(5.0)
    assert result.n_total == 15
    assert result.effect_size.label_tr == "mükemmel"

    by_item = {s["item"]: s for s in result.extra["item_statistics"]}
    assert by_item["madde1"]["alpha_if_deleted"] == pytest.approx(0.939924, abs=TOL)
    assert by_item["madde2"]["alpha_if_deleted"] == pytest.approx(0.965022, abs=TOL)
    assert by_item["madde1"]["corrected_item_total_correlation"] == pytest.approx(0.982046, abs=TOL)


def test_cronbachs_alpha_has_no_p_value(reference):
    """Reliability is a coefficient, not a hypothesis test — the result must not
    carry a fabricated significance value."""
    frame = reference("reliability_scale.csv")
    result = cronbachs_alpha(frame[[f"madde{i}" for i in range(1, 6)]])
    assert np.isnan(result.p_value)
    assert result.to_dict()["p_value"] is None


def test_cronbachs_alpha_requires_two_items(reference):
    frame = reference("reliability_scale.csv")
    with pytest.raises(InsufficientDataError):
        cronbachs_alpha(frame[["madde1"]])


# ---------------------------------------------------------------------------
# Cross-cutting: every procedure must attach an effect size (§3.5 is mandatory)
# ---------------------------------------------------------------------------

def test_every_procedure_reports_an_effect_size(reference):
    frame = reference("ttest_independent.csv")
    a = frame[frame.yontem == "Deney"].basari_puani
    b = frame[frame.yontem == "Kontrol"].basari_puani
    anova_frame = reference("anova_three_groups.csv")
    paired = reference("ttest_paired.csv")
    corr = reference("correlation_regression.csv")

    results = [
        independent_t_test(a, b),
        independent_t_test(a, b, equal_var=False),
        paired_t_test(paired.on_test, paired.son_test),
        one_way_anova(anova_frame.kaygi_puani, anova_frame.sinif_duzeyi),
        mann_whitney_u(a, b),
        wilcoxon_signed_rank(paired.on_test, paired.son_test),
        kruskal_wallis(anova_frame.kaygi_puani, anova_frame.sinif_duzeyi),
        correlation(corr.calisma_saati, corr.sinav_puani),
        linear_regression(corr.sinav_puani, corr[["calisma_saati"]]),
        chi_square_independence(reference("chi_square.csv").cinsiyet,
                                reference("chi_square.csv").tercih),
        cronbachs_alpha(reference("reliability_scale.csv")[[f"madde{i}" for i in range(1, 6)]]),
    ]
    for result in results:
        assert result.effect_size is not None, result.analysis_type
        assert np.isfinite(result.effect_size.value), result.analysis_type
        assert result.effect_size.label_tr, result.analysis_type
