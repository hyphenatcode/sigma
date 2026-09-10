"""§3.3 decision-tree tests.

The tree is the core IP: every branch gets a case, and — just as importantly —
the combinations the spec does NOT cover get a case asserting an explicit
refusal rather than a best-guess neighbouring test.
"""

import pytest

from app.stats.enums import MeasurementLevel as ML
from app.stats.enums import ResearchTask as RT
from app.stats.recommendation import (
    RecommendationInput,
    VariableSpec,
    recommend_test,
)


def cont(name="dv"):
    return VariableSpec(name, ML.RATIO)


def interval(name="dv"):
    return VariableSpec(name, ML.INTERVAL)


def cat(name="iv"):
    return VariableSpec(name, ML.NOMINAL)


def ordinal(name="iv"):
    return VariableSpec(name, ML.ORDINAL)


# ---------------------------------------------------------------------------
# Continuous DV x categorical IV
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_groups,is_paired,expected,fallback", [
    (2, False, "independent_t_test", "mann_whitney_u"),
    (2, True, "paired_t_test", "wilcoxon_signed_rank"),
    (3, False, "one_way_anova", "kruskal_wallis"),
    (5, False, "one_way_anova", "kruskal_wallis"),
])
def test_categorical_iv_branches(n_groups, is_paired, expected, fallback):
    rec = recommend_test(RecommendationInput(
        task=RT.COMPARISON, dv=cont(), ivs=(cat(),),
        n_groups=n_groups, is_paired=is_paired,
    ))
    assert rec.supported
    assert rec.candidate == expected
    assert rec.fallback == fallback


def test_interval_dv_is_treated_as_continuous():
    rec = recommend_test(RecommendationInput(
        task=RT.COMPARISON, dv=interval(), ivs=(cat(),), n_groups=2,
    ))
    assert rec.candidate == "independent_t_test"


def test_ordinal_iv_counts_as_categorical():
    rec = recommend_test(RecommendationInput(
        task=RT.COMPARISON, dv=cont(), ivs=(ordinal(),), n_groups=3,
    ))
    assert rec.candidate == "one_way_anova"


def test_repeated_measures_is_named_but_refused_in_v1():
    """§3.3 puts RM-ANOVA in the tree; the v1 build does not execute it.

    The refusal must NAME the test rather than degrade to one-way ANOVA.
    """
    rec = recommend_test(RecommendationInput(
        task=RT.COMPARISON, dv=cont(), ivs=(cat(),), n_groups=3, is_paired=True,
    ))
    assert not rec.supported
    assert rec.candidate == "repeated_measures_anova"
    assert "Tekrarlı Ölçümler ANOVA" in rec.reason_tr


# ---------------------------------------------------------------------------
# Continuous DV x continuous IV
# ---------------------------------------------------------------------------

def test_single_continuous_iv_relationship_gives_pearson():
    rec = recommend_test(RecommendationInput(
        task=RT.RELATIONSHIP, dv=cont(), ivs=(cont("x"),),
    ))
    assert rec.candidate == "pearson_correlation"
    assert rec.fallback == "spearman_correlation"


def test_single_continuous_iv_prediction_gives_simple_regression():
    rec = recommend_test(RecommendationInput(
        task=RT.PREDICTION, dv=cont(), ivs=(cont("x"),),
    ))
    assert rec.candidate == "simple_linear_regression"


def test_multiple_continuous_ivs_give_multiple_regression():
    rec = recommend_test(RecommendationInput(
        task=RT.PREDICTION, dv=cont(), ivs=(cont("x1"), cont("x2"), cont("x3")),
    ))
    assert rec.candidate == "multiple_linear_regression"


# ---------------------------------------------------------------------------
# Categorical DV, and the task-keyed branches
# ---------------------------------------------------------------------------

def test_categorical_dv_and_iv_give_chi_square():
    rec = recommend_test(RecommendationInput(
        task=RT.COMPARISON, dv=cat("pass"), ivs=(cat("sex"),),
    ))
    assert rec.candidate == "chi_square_independence"


def test_scale_reliability_gives_cronbach():
    rec = recommend_test(RecommendationInput(
        task=RT.SCALE_RELIABILITY,
        scale_items=(cont("i1"), cont("i2"), cont("i3")),
    ))
    assert rec.candidate == "cronbachs_alpha"


def test_factor_structure_is_refused_in_v1():
    rec = recommend_test(RecommendationInput(task=RT.FACTOR_STRUCTURE))
    assert not rec.supported
    assert rec.candidate == "exploratory_factor_analysis"


# ---------------------------------------------------------------------------
# §3.3: "Any input combination not matching a rule -> explicit 'not supported'"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    # categorical DV with a continuous IV — logistic regression, not in v1
    dict(task=RT.COMPARISON, dv=cat("pass"), ivs=(cont("score"),)),
    # mixed IV types — ANCOVA, explicitly v2 per §3.9
    dict(task=RT.COMPARISON, dv=cont(), ivs=(cat("sex"), cont("age")), n_groups=2),
    # two categorical IVs — factorial ANOVA, not in the tree
    dict(task=RT.COMPARISON, dv=cont(), ivs=(cat("a"), cat("b")), n_groups=2),
    # a grouping variable with a single level
    dict(task=RT.COMPARISON, dv=cont(), ivs=(cat(),), n_groups=1),
    # no DV at all
    dict(task=RT.COMPARISON, ivs=(cat(),), n_groups=2),
    # no IV at all
    dict(task=RT.COMPARISON, dv=cont()),
    # reliability with a single item
    dict(task=RT.SCALE_RELIABILITY, scale_items=(cont("i1"),)),
])
def test_uncovered_combinations_are_refused_not_guessed(payload):
    rec = recommend_test(RecommendationInput(**payload))
    assert not rec.supported
    assert rec.reason_tr, "a refusal must carry a Turkish explanation"


def test_recommendation_is_pure_and_deterministic():
    payload = RecommendationInput(task=RT.COMPARISON, dv=cont(), ivs=(cat(),), n_groups=2)
    assert recommend_test(payload) == recommend_test(payload)
