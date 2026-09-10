"""Pluggable AnalysisType registry (§3.9, §4).

Adding a v2 analysis (mediation, moderation, SEM, ANCOVA...) means appending an
`AnalysisTypeSpec` here and registering a runner — the recommendation engine,
the pipeline, the API layer and the data model do not change. That is the
"architecture must not block adding them" requirement of §3.9.

`supported_in_v1` is the gate. §3.3 requires that any combination we cannot
serve produces an explicit "not supported in this version" message rather than
a best-guess fallback, so a spec'd-but-unimplemented test is registered here
with supported_in_v1=False and named in that message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class TestFamily(str, Enum):
    T_TEST = "t_test"
    ANOVA = "anova"
    NONPARAMETRIC = "nonparametric"
    CORRELATION = "correlation"
    REGRESSION = "regression"
    CATEGORICAL = "categorical"
    RELIABILITY = "reliability"
    FACTOR = "factor"


@dataclass(frozen=True)
class AnalysisTypeSpec:
    key: str
    family: TestFamily
    label_tr: str
    label_en: str
    #: non-parametric analysis this test degrades to when §3.4 normality fails
    nonparametric_fallback: Optional[str] = None
    #: variant used when §3.4 homogeneity-of-variance fails
    unequal_variance_variant: Optional[str] = None
    #: whether v1 can actually execute it. False => explicit "not supported yet".
    supported_in_v1: bool = True
    #: whether the analysis is a fallback/variant reachable only via §3.4
    recommendable: bool = True
    effect_size_metric: str = ""
    notes: str = ""


_REGISTRY: Dict[str, AnalysisTypeSpec] = {}


def register(spec: AnalysisTypeSpec) -> AnalysisTypeSpec:
    if spec.key in _REGISTRY:
        raise ValueError(f"AnalysisType {spec.key!r} already registered")
    _REGISTRY[spec.key] = spec
    return spec


def get(key: str) -> AnalysisTypeSpec:
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown analysis type {key!r}") from exc


def all_specs() -> Dict[str, AnalysisTypeSpec]:
    return dict(_REGISTRY)


def supported_keys() -> list[str]:
    return [k for k, v in _REGISTRY.items() if v.supported_in_v1]


# --------------------------------------------------------------------------
# v1 registry — exactly the tests named in §3.3 of the requirements doc.
# --------------------------------------------------------------------------

register(AnalysisTypeSpec(
    key="independent_t_test",
    family=TestFamily.T_TEST,
    label_tr="Bağımsız Örneklem t-Testi",
    label_en="Independent samples t-test",
    nonparametric_fallback="mann_whitney_u",
    unequal_variance_variant="welch_t_test",
    effect_size_metric="cohens_d",
))

register(AnalysisTypeSpec(
    key="welch_t_test",
    family=TestFamily.T_TEST,
    label_tr="Welch t-Testi",
    label_en="Welch's t-test",
    nonparametric_fallback="mann_whitney_u",
    recommendable=False,  # reached only via the §3.4 Levene branch
    effect_size_metric="cohens_d",
))

register(AnalysisTypeSpec(
    key="paired_t_test",
    family=TestFamily.T_TEST,
    label_tr="Bağımlı Örneklem t-Testi",
    label_en="Paired samples t-test",
    nonparametric_fallback="wilcoxon_signed_rank",
    effect_size_metric="cohens_d",
))

register(AnalysisTypeSpec(
    key="one_way_anova",
    family=TestFamily.ANOVA,
    label_tr="Tek Yönlü ANOVA",
    label_en="One-way ANOVA",
    nonparametric_fallback="kruskal_wallis",
    unequal_variance_variant="welch_anova",
    effect_size_metric="eta_squared",
))

register(AnalysisTypeSpec(
    key="welch_anova",
    family=TestFamily.ANOVA,
    label_tr="Welch ANOVA",
    label_en="Welch's ANOVA",
    nonparametric_fallback="kruskal_wallis",
    recommendable=False,  # reached only via the §3.4 Levene branch
    effect_size_metric="eta_squared",
))

register(AnalysisTypeSpec(
    key="mann_whitney_u",
    family=TestFamily.NONPARAMETRIC,
    label_tr="Mann-Whitney U Testi",
    label_en="Mann-Whitney U test",
    effect_size_metric="rank_biserial_r",
))

register(AnalysisTypeSpec(
    key="wilcoxon_signed_rank",
    family=TestFamily.NONPARAMETRIC,
    label_tr="Wilcoxon İşaretli Sıralar Testi",
    label_en="Wilcoxon signed-rank test",
    effect_size_metric="rank_biserial_r",
))

register(AnalysisTypeSpec(
    key="kruskal_wallis",
    family=TestFamily.NONPARAMETRIC,
    label_tr="Kruskal-Wallis H Testi",
    label_en="Kruskal-Wallis H test",
    effect_size_metric="epsilon_squared",
))

register(AnalysisTypeSpec(
    key="pearson_correlation",
    family=TestFamily.CORRELATION,
    label_tr="Pearson Korelasyon Analizi",
    label_en="Pearson correlation",
    nonparametric_fallback="spearman_correlation",
    effect_size_metric="r",
))

register(AnalysisTypeSpec(
    key="spearman_correlation",
    family=TestFamily.CORRELATION,
    label_tr="Spearman Sıra Farkları Korelasyonu",
    label_en="Spearman rank correlation",
    effect_size_metric="rho",
))

register(AnalysisTypeSpec(
    key="simple_linear_regression",
    family=TestFamily.REGRESSION,
    label_tr="Basit Doğrusal Regresyon",
    label_en="Simple linear regression",
    effect_size_metric="r_squared",
))

register(AnalysisTypeSpec(
    key="multiple_linear_regression",
    family=TestFamily.REGRESSION,
    label_tr="Çoklu Doğrusal Regresyon",
    label_en="Multiple linear regression",
    effect_size_metric="r_squared",
))

register(AnalysisTypeSpec(
    key="chi_square_independence",
    family=TestFamily.CATEGORICAL,
    label_tr="Ki-Kare Bağımsızlık Testi",
    label_en="Chi-square test of independence",
    effect_size_metric="cramers_v",
))

register(AnalysisTypeSpec(
    key="cronbachs_alpha",
    family=TestFamily.RELIABILITY,
    label_tr="Cronbach Alfa Güvenirlik Analizi",
    label_en="Cronbach's alpha",
    effect_size_metric="alpha",
))

# --------------------------------------------------------------------------
# Named by §3.3's decision tree but NOT in the Phase 1 execution list of the
# build brief. They stay registered so the recommendation engine can name them
# precisely ("Tekrarlı Ölçümler ANOVA henüz desteklenmiyor") instead of falling
# back to a nearby-but-wrong test, which §3.3 forbids.
#
# TODO(spec-gap): §3.3 lists repeated_measures_anova / friedman /
# exploratory_factor_analysis in the decision tree, but the build brief's
# Phase 1 execution list omits them. Implementing them would require spec
# detail the doc does not give (RM-ANOVA: long-vs-wide input shape and
# sphericity/Greenhouse-Geisser correction policy; EFA: extraction and
# rotation method, factor-retention rule). Left recommendable but not
# executable rather than guessed at.
# --------------------------------------------------------------------------

register(AnalysisTypeSpec(
    key="repeated_measures_anova",
    family=TestFamily.ANOVA,
    label_tr="Tekrarlı Ölçümler ANOVA",
    label_en="Repeated measures ANOVA",
    nonparametric_fallback="friedman",
    supported_in_v1=False,
    effect_size_metric="partial_eta_squared",
    notes="Sphericity correction policy unspecified in the requirements doc.",
))

register(AnalysisTypeSpec(
    key="friedman",
    family=TestFamily.NONPARAMETRIC,
    label_tr="Friedman Testi",
    label_en="Friedman test",
    supported_in_v1=False,
    effect_size_metric="kendalls_w",
))

register(AnalysisTypeSpec(
    key="exploratory_factor_analysis",
    family=TestFamily.FACTOR,
    label_tr="Açımlayıcı Faktör Analizi",
    label_en="Exploratory factor analysis",
    supported_in_v1=False,
    effect_size_metric="explained_variance",
    notes="Extraction/rotation/retention rules unspecified in the requirements doc.",
))
