"""Analysis pipeline: recommend (§3.3) -> check assumptions (§3.4) -> execute -> effect size (§3.5).

This is the only place that decides to swap a parametric test for its
non-parametric fallback or its unequal-variance variant, and it always records
why — §3.4 requires that the assumption tests run and their results be reported,
never silently skipped.

Still deterministic: no LLM, no network. The interpretation layer (§3.6) runs
downstream of this module and only ever sees its output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.stats import assumptions as assump
from app.stats import registry
from app.stats.assumptions import AssumptionResult
from app.stats.enums import AssumptionStatus, MeasurementLevel, ResearchTask
from app.stats.procedures import associations, comparisons
from app.stats.recommendation import (
    Recommendation,
    RecommendationInput,
    VariableSpec,
    recommend_test,
)
from app.stats.registry import TestFamily
from app.stats.results import InsufficientDataError, TestResult


class UnsupportedAnalysisError(ValueError):
    """§3.3: an explicit refusal, never a best-guess substitute test."""

    def __init__(self, message_tr: str, *, recommendation: Optional[Recommendation] = None):
        super().__init__(message_tr)
        self.message_tr = message_tr
        self.recommendation = recommendation


@dataclass
class AnalysisRequest:
    """The `variable_config` of §4, typed.

    `paired_measurements` carries the two wide-format columns of a
    within-subjects design; `independent_variables` carries the between-subjects
    IV(s) or the continuous predictors.
    """

    task: ResearchTask
    dependent_variable: Optional[str] = None
    independent_variables: list[str] = field(default_factory=list)
    paired_measurements: list[str] = field(default_factory=list)
    scale_items: list[str] = field(default_factory=list)
    is_paired: bool = False
    #: column name -> measurement level, as confirmed by the user in §3.2
    measurement_levels: dict[str, MeasurementLevel] = field(default_factory=dict)

    def level_of(self, column: str) -> MeasurementLevel:
        try:
            return self.measurement_levels[column]
        except KeyError as exc:
            raise UnsupportedAnalysisError(
                f"'{column}' değişkeni için ölçüm düzeyi belirtilmemiş."
            ) from exc


@dataclass
class PipelineOutcome:
    recommendation: Recommendation
    executed_analysis_type: str
    result: TestResult
    assumption_results: list[AssumptionResult]
    substituted: bool
    substitution_reason_tr: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_analysis_type": self.recommendation.candidate,
            "executed_analysis_type": self.executed_analysis_type,
            "rule_path": list(self.recommendation.rule_path),
            "substituted": self.substituted,
            "substitution_reason_tr": self.substitution_reason_tr,
            "result": self.result.to_dict(),
        }


# ---------------------------------------------------------------------------
# Step 1 — build the §3.3 input from the user's variable configuration
# ---------------------------------------------------------------------------

#: Label for the synthetic within-subjects factor of a paired design. The §3.3
#: tree branches on a categorical IV with n_groups levels; in a wide-format
#: repeated-measures layout that factor is the measurement occasion itself.
WITHIN_SUBJECT_FACTOR = "Ölçüm"


def build_recommendation_input(request: AnalysisRequest, frame: pd.DataFrame) -> RecommendationInput:
    if request.task is ResearchTask.SCALE_RELIABILITY:
        return RecommendationInput(
            task=request.task,
            scale_items=tuple(
                VariableSpec(name, request.level_of(name)) for name in request.scale_items
            ),
        )

    if request.is_paired:
        if len(request.paired_measurements) < 2:
            raise UnsupportedAnalysisError(
                "Bağımlı (eşleştirilmiş) bir tasarım için en az iki ölçüm sütunu seçilmelidir."
            )
        levels = {request.level_of(c) for c in request.paired_measurements}
        if not all(level.is_continuous for level in levels):
            raise UnsupportedAnalysisError(
                "Eşleştirilmiş ölçümler sürekli (eşit aralıklı/oranlı) olmalıdır."
            )
        first = request.paired_measurements[0]
        return RecommendationInput(
            task=request.task,
            dv=VariableSpec(first, request.level_of(first)),
            ivs=(VariableSpec(WITHIN_SUBJECT_FACTOR, MeasurementLevel.NOMINAL),),
            n_groups=len(request.paired_measurements),
            is_paired=True,
        )

    dv = (
        VariableSpec(request.dependent_variable, request.level_of(request.dependent_variable))
        if request.dependent_variable else None
    )
    ivs = tuple(VariableSpec(name, request.level_of(name)) for name in request.independent_variables)

    n_groups: Optional[int] = None
    categorical_ivs = [iv for iv in ivs if iv.is_categorical]
    if len(categorical_ivs) == 1:
        column = categorical_ivs[0].name
        if column not in frame.columns:
            raise UnsupportedAnalysisError(f"'{column}' sütunu veri setinde bulunamadı.")
        n_groups = int(frame[column].dropna().nunique())

    return RecommendationInput(
        task=request.task,
        dv=dv,
        ivs=ivs,
        n_groups=n_groups,
        is_paired=False,
    )


# ---------------------------------------------------------------------------
# Step 2/3 — assumption checks and the resulting test choice
# ---------------------------------------------------------------------------

@dataclass
class _Decision:
    analysis_type: str
    results: list[AssumptionResult]
    substituted: bool = False
    reason_tr: Optional[str] = None


def _decide_group_comparison(
    candidate: str,
    samples: list[np.ndarray],
    labels: list[str],
) -> _Decision:
    """§3.4 for the t-test and ANOVA families.

    Order of operations: normality first, homogeneity second. A normality
    violation sends us to the non-parametric fallback of §3.3, which makes no
    equal-variance assumption, so Levene's verdict cannot then change the
    choice — but it is still run and reported, because §3.4 requires that the
    system always report which assumption tests ran.
    """
    spec = registry.get(candidate)
    results: list[AssumptionResult] = []

    for label, sample in zip(labels, samples):
        results.append(assump.check_normality(sample, group_label=label))
    normality_violated = any(r.status is not AssumptionStatus.MET for r in results)

    homogeneity = assump.check_homogeneity(samples)
    results.append(homogeneity)

    if normality_violated:
        fallback = spec.nonparametric_fallback
        if fallback is None:  # pragma: no cover — every parametric spec defines one
            return _Decision(candidate, results)
        failing = [r.group for r in results if r.assumption == "normality"
                   and r.status is not AssumptionStatus.MET and r.group]
        where = f" ({', '.join(failing)})" if failing else ""
        return _Decision(
            fallback, results, substituted=True,
            reason_tr=(
                f"Normallik varsayımı{where} karşılanmadığı için "
                f"{spec.label_tr} yerine parametrik olmayan {registry.get(fallback).label_tr} "
                f"uygulanmıştır."
            ),
        )

    if homogeneity.status is AssumptionStatus.VIOLATED and spec.unequal_variance_variant:
        variant = spec.unequal_variance_variant
        return _Decision(
            variant, results, substituted=True,
            reason_tr=(
                f"Varyansların homojenliği varsayımı karşılanmadığı için "
                f"{spec.label_tr} yerine {registry.get(variant).label_tr} uygulanmıştır."
            ),
        )

    return _Decision(candidate, results)


def _decide_paired(candidate: str, differences: np.ndarray) -> _Decision:
    """§3.4 normality for a paired design.

    The paired t-test's normality assumption is about the *differences*, not the
    two measurements separately, so that is what we test.
    """
    spec = registry.get(candidate)
    result = assump.check_normality(differences, group_label="Fark puanları")
    if result.status is AssumptionStatus.MET:
        return _Decision(candidate, [result])
    fallback = spec.nonparametric_fallback
    return _Decision(
        fallback, [result], substituted=True,
        reason_tr=(
            f"Fark puanları normal dağılmadığı için {spec.label_tr} yerine "
            f"parametrik olmayan {registry.get(fallback).label_tr} uygulanmıştır."
        ),
    )


def _decide_correlation(candidate: str, x: np.ndarray, y: np.ndarray,
                        labels: tuple[str, str]) -> _Decision:
    """§3.3 gives Pearson a Spearman fallback, but §3.4's table does not name the
    check that triggers it.

    TODO(spec-gap): §3.4 lists normality checks only for the t-test/ANOVA
    families. We apply the same §3.4 rule (Shapiro-Wilk under n=50,
    Kolmogorov-Smirnov at or above it) to each of the two variables and switch
    to Spearman if either fails, which is the standard basis for that choice —
    rather than inventing a different criterion.
    """
    spec = registry.get(candidate)
    results = [
        assump.check_normality(x, group_label=labels[0]),
        assump.check_normality(y, group_label=labels[1]),
    ]
    if all(r.status is AssumptionStatus.MET for r in results):
        return _Decision(candidate, results)

    failing = [r.group for r in results if r.status is not AssumptionStatus.MET]
    return _Decision(
        spec.nonparametric_fallback, results, substituted=True,
        reason_tr=(
            f"{', '.join(failing)} değişken(ler)i normal dağılım göstermediği için "
            f"{spec.label_tr} yerine {registry.get(spec.nonparametric_fallback).label_tr} "
            f"uygulanmıştır."
        ),
    )


# ---------------------------------------------------------------------------
# Step 4 — execute
# ---------------------------------------------------------------------------

def run_analysis(frame: pd.DataFrame, request: AnalysisRequest) -> PipelineOutcome:
    """Full deterministic pipeline for one analysis."""
    recommendation = recommend_test(build_recommendation_input(request, frame))
    if not recommendation.supported:
        raise UnsupportedAnalysisError(recommendation.reason_tr or "Bu analiz desteklenmiyor.",
                                       recommendation=recommendation)

    candidate = recommendation.candidate
    family = registry.get(candidate).family

    if family is TestFamily.RELIABILITY:
        result = associations.cronbachs_alpha(frame[request.scale_items])
        result.assumption_results = [AssumptionResult(
            assumption="not_applicable",
            test_name="—",
            status=AssumptionStatus.NOT_APPLICABLE,
            message_tr="Cronbach alfa için §3.4 kapsamında bir varsayım testi tanımlanmamıştır.",
        )]
        return PipelineOutcome(recommendation, result.analysis_type, result,
                              result.assumption_results, substituted=False)

    if family is TestFamily.CATEGORICAL:
        dv, iv = request.dependent_variable, request.independent_variables[0]
        result = associations.chi_square_independence(frame[iv], frame[dv], labels=(iv, dv))
        return PipelineOutcome(recommendation, result.analysis_type, result,
                              result.assumption_results, substituted=False)

    if family is TestFamily.REGRESSION:
        dv = request.dependent_variable
        result = associations.linear_regression(
            frame[dv], frame[request.independent_variables], dv_label=dv
        )
        return PipelineOutcome(recommendation, result.analysis_type, result,
                              result.assumption_results, substituted=False)

    if family is TestFamily.CORRELATION:
        dv, iv = request.dependent_variable, request.independent_variables[0]
        x = pd.to_numeric(frame[iv], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(frame[dv], errors="coerce").to_numpy(dtype=float)
        keep = np.isfinite(x) & np.isfinite(y)
        decision = _decide_correlation(candidate, x[keep], y[keep], (iv, dv))
        method = "pearson" if decision.analysis_type == "pearson_correlation" else "spearman"
        result = associations.correlation(x[keep], y[keep], method=method, labels=(iv, dv))
        return _finish(recommendation, decision, result)

    # t-test / ANOVA / non-parametric families
    if request.is_paired:
        col1, col2 = request.paired_measurements[0], request.paired_measurements[1]
        v1 = pd.to_numeric(frame[col1], errors="coerce").to_numpy(dtype=float)
        v2 = pd.to_numeric(frame[col2], errors="coerce").to_numpy(dtype=float)
        keep = np.isfinite(v1) & np.isfinite(v2)
        v1, v2 = v1[keep], v2[keep]
        decision = _decide_paired(candidate, v1 - v2)
        if decision.analysis_type == "paired_t_test":
            result = comparisons.paired_t_test(v1, v2, labels=(col1, col2))
        else:
            result = comparisons.wilcoxon_signed_rank(v1, v2, labels=(col1, col2))
        return _finish(recommendation, decision, result)

    dv = request.dependent_variable
    iv = request.independent_variables[0]
    working = frame[[dv, iv]].copy()
    working[dv] = pd.to_numeric(working[dv], errors="coerce")
    working = working.dropna()
    if working.empty:
        raise InsufficientDataError("Analiz için geçerli gözlem bulunamadı.")

    grouped = [(str(label), chunk[dv].to_numpy(dtype=float))
               for label, chunk in working.groupby(iv, sort=True, observed=True)]
    labels = [label for label, _ in grouped]
    samples = [sample for _, sample in grouped]

    decision = _decide_group_comparison(candidate, samples, labels)
    executed = decision.analysis_type

    if executed == "independent_t_test":
        result = comparisons.independent_t_test(samples[0], samples[1],
                                                labels=(labels[0], labels[1]), equal_var=True)
    elif executed == "welch_t_test":
        result = comparisons.independent_t_test(samples[0], samples[1],
                                                labels=(labels[0], labels[1]), equal_var=False)
    elif executed == "mann_whitney_u":
        result = comparisons.mann_whitney_u(samples[0], samples[1], labels=(labels[0], labels[1]))
    elif executed == "one_way_anova":
        result = comparisons.one_way_anova(working[dv], working[iv], equal_var=True)
    elif executed == "welch_anova":
        result = comparisons.one_way_anova(working[dv], working[iv], equal_var=False)
    elif executed == "kruskal_wallis":
        result = comparisons.kruskal_wallis(working[dv], working[iv])
    else:  # pragma: no cover — registry and pipeline are kept in sync
        raise UnsupportedAnalysisError(
            f"'{executed}' analizi bu sürümde çalıştırılamıyor."
        )

    return _finish(recommendation, decision, result)


def _finish(recommendation: Recommendation, decision: _Decision, result: TestResult) -> PipelineOutcome:
    """Attach the §3.4 record to the result, keeping any diagnostics the
    procedure itself produced (regression, chi-square)."""
    result.assumption_results = decision.results + list(result.assumption_results)
    result.substitution_note_tr = decision.reason_tr
    return PipelineOutcome(
        recommendation=recommendation,
        executed_analysis_type=result.analysis_type,
        result=result,
        assumption_results=result.assumption_results,
        substituted=decision.substituted,
        substitution_reason_tr=decision.reason_tr,
    )
