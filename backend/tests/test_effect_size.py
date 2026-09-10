"""§3.5 effect-size tests, including the small/medium/large band lookup."""

import numpy as np
import pytest

from app.stats import effect_size as es
from app.stats.enums import EffectSizeBand


# ---------------------------------------------------------------------------
# Band lookup — the thresholds are lifted straight from the §3.5 table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (0.19, "negligible"), (0.2, "small"), (0.49, "small"),
    (0.5, "medium"), (0.79, "medium"), (0.8, "large"), (1.5, "large"),
    (-0.9, "large"),  # bands are about magnitude, not direction
])
def test_cohens_d_bands(value, expected):
    assert es.band_for("cohens_d", value).value == expected


@pytest.mark.parametrize("value,expected", [
    (0.005, "negligible"), (0.01, "small"), (0.06, "medium"), (0.14, "large"),
])
def test_eta_squared_bands(value, expected):
    assert es.band_for("eta_squared", value).value == expected


@pytest.mark.parametrize("value,expected", [
    (0.05, "negligible"), (0.1, "small"), (0.3, "medium"), (0.5, "large"),
])
def test_correlation_bands(value, expected):
    assert es.band_for("r", value).value == expected


@pytest.mark.parametrize("metric", ["r_squared", "adjusted_r_squared", "alpha"])
def test_unbanded_metrics_are_never_banded(metric):
    """§3.5: R^2 is 'reported, not banded'."""
    assert es.band_for(metric, 0.99) is EffectSizeBand.NOT_BANDED


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------

def test_cohens_d_independent_hand_computation():
    """g1=[5,6,7,8,9] M=7 s2=2.5; g2=[1,2,3,4,5] M=3 s2=2.5
    SD_pooled = sqrt((4*2.5+4*2.5)/8) = sqrt(2.5) = 1.5811388
    d = (7-3)/1.5811388 = 2.5298221"""
    effect = es.cohens_d_independent([5, 6, 7, 8, 9], [1, 2, 3, 4, 5])
    assert effect.value == pytest.approx(2.5298221, abs=1e-6)
    assert effect.extra["pooled_sd"] == pytest.approx(1.5811388, abs=1e-6)
    assert effect.band is EffectSizeBand.LARGE
    assert effect.label_tr == "büyük"


def test_cohens_d_paired_is_d_z():
    """differences = [2,3,1,1,2]; M = 1.8; var = 2.8/4 = 0.7
    SD = sqrt(0.7) = 0.8366600 -> d_z = 1.8/0.8366600 = 2.1514115"""
    effect = es.cohens_d_paired([10, 12, 14, 11, 13], [8, 9, 13, 10, 11])
    assert effect.value == pytest.approx(2.1514115, abs=1e-6)
    assert "d_z" in effect.extra["formulation"]


def test_eta_squared_is_ss_between_over_ss_total():
    effect = es.eta_squared(768.0, 848.5)
    assert effect.value == pytest.approx(0.9051267, abs=1e-6)
    assert effect.band is EffectSizeBand.LARGE


def test_partial_eta_squared_uses_effect_plus_error():
    effect = es.partial_eta_squared(20.0, 80.0)
    assert effect.value == pytest.approx(0.2)


def test_cramers_v_2x2_uses_plain_bands():
    """df* = 1, so the thresholds stay at .1/.3/.5"""
    effect = es.cramers_v(6.666667, 60, 2, 2)
    assert effect.value == pytest.approx(0.3333333, abs=1e-6)
    assert effect.thresholds == pytest.approx((0.1, 0.3, 0.5))
    assert effect.band is EffectSizeBand.MEDIUM


def test_cramers_v_bands_are_df_adjusted():
    """§3.5: 'df-dependent, use standard table'. For df* = 2 Cohen's table gives
    .07/.21/.35, i.e. the .1/.3/.5 benchmarks divided by sqrt(2)."""
    effect = es.cramers_v(10.0, 100, 3, 3)
    assert effect.extra["df_star"] == 2
    assert effect.thresholds == pytest.approx((0.0707107, 0.2121320, 0.3535534), abs=1e-6)
    assert effect.value == pytest.approx(0.2236068, abs=1e-6)
    assert effect.band is EffectSizeBand.MEDIUM  # would be "small" on the 2x2 table


def test_rank_biserial_mann_whitney_spans_minus_one_to_one():
    assert es.rank_biserial_mann_whitney(0, 10, 10).value == pytest.approx(-1.0)
    assert es.rank_biserial_mann_whitney(50, 10, 10).value == pytest.approx(0.0)
    assert es.rank_biserial_mann_whitney(100, 10, 10).value == pytest.approx(1.0)


def test_rank_biserial_wilcoxon():
    assert es.rank_biserial_wilcoxon(0.0, 78.0).value == pytest.approx(-1.0)
    assert es.rank_biserial_wilcoxon(39.0, 39.0).value == pytest.approx(0.0)


def test_epsilon_squared_kruskal():
    """eps^2 = H*(n+1)/(n^2-1) = 15.157895*19/323"""
    effect = es.epsilon_squared_kruskal(15.157895, 18)
    assert effect.value == pytest.approx(0.8916409, abs=1e-6)
    assert effect.band is EffectSizeBand.LARGE


def test_r_squared_reports_percentage_of_variance():
    effect = es.r_squared_effect(0.4321, 0.4102)
    assert effect.band is EffectSizeBand.NOT_BANDED
    assert "43.2" in effect.label_tr
    assert effect.extra["adjusted_r_squared"] == pytest.approx(0.4102)


@pytest.mark.parametrize("alpha,label", [
    (0.95, "mükemmel"), (0.85, "iyi"), (0.72, "kabul edilebilir"),
    (0.65, "sınırda"), (0.4, "yetersiz"),
])
def test_alpha_labels_follow_the_reliability_convention(alpha, label):
    assert es.alpha_effect(alpha).label_tr == label


def test_every_effect_size_serialises():
    effect = es.cohens_d_independent([1, 2, 3, 4], [5, 6, 7, 8])
    payload = effect.to_dict()
    assert set(payload) == {"metric", "value", "band", "label_tr", "thresholds", "extra"}
    assert np.isfinite(payload["value"])
