"""Assumption checking layer (§3.4).

Pure functions over numeric arrays. The pipeline (§3.3 -> §3.4 -> execution)
calls into here to decide between a parametric test and its non-parametric
fallback, and to decide between the pooled-variance and Welch variants.

Per §3.4's closing line the system ALWAYS reports which assumption tests were
run and what they found — every checker returns a record even when the result
does not change the test choice, and `AssumptionStatus.NOT_RUN` is used (with a
reason) rather than silently omitting a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats as sps
from statsmodels.stats.diagnostic import het_breuschpagan, lilliefors
from statsmodels.stats.outliers_influence import variance_inflation_factor

from app.stats.enums import AssumptionStatus

#: §3.4 uses the conventional α = .05 for assumption tests.
ALPHA = 0.05

#: §3.4: Shapiro-Wilk below this n, Kolmogorov-Smirnov at or above it.
SHAPIRO_MAX_N = 50

#: §3.4: flag a predictor when VIF exceeds this.
VIF_THRESHOLD = 10.0

#: §3.4: chi-square expected cell counts must all reach this.
MIN_EXPECTED_CELL_COUNT = 5


@dataclass
class AssumptionResult:
    """One assumption check, in a shape that serialises straight to JSON.

    `blocking` marks a check whose violation changes the test choice (normality,
    homogeneity). A non-blocking violation is reported but does not stop the
    analysis — §3.4 is explicit that linearity, homoscedasticity,
    multicollinearity and the chi-square cell rule are flags, not blockers.
    """

    assumption: str            # e.g. "normality"
    test_name: str             # e.g. "Shapiro-Wilk"
    status: AssumptionStatus
    blocking: bool = False
    statistic: Optional[float] = None
    p_value: Optional[float] = None
    group: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)
    message_tr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption": self.assumption,
            "test_name": self.test_name,
            "status": self.status.value,
            "blocking": self.blocking,
            "statistic": _clean(self.statistic),
            "p_value": _clean(self.p_value),
            "group": self.group,
            "detail": self.detail,
            "message_tr": self.message_tr,
        }


def _clean(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return None if not np.isfinite(value) else value


# ---------------------------------------------------------------------------
# Normality
# ---------------------------------------------------------------------------

def check_normality(values: Sequence[float], *, group_label: Optional[str] = None) -> AssumptionResult:
    """§3.4: Shapiro-Wilk for n<50, Kolmogorov-Smirnov for n>=50, per group.

    The KS branch uses the Lilliefors correction (statsmodels `lilliefors`),
    which is the form that applies when the mean and SD are estimated from the
    sample rather than known a priori — a plain one-sample KS against an
    estimated normal is anti-conservative. This is the same test SPSS reports
    as "Kolmogorov-Smirnov (Lilliefors Significance Correction)".
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size

    if n < 3:
        return AssumptionResult(
            assumption="normality",
            test_name="Shapiro-Wilk",
            status=AssumptionStatus.NOT_RUN,
            blocking=True,
            group=group_label,
            detail={"n": int(n)},
            message_tr="Normallik testi için yeterli gözlem yok (n < 3).",
        )
    if np.allclose(arr, arr[0]):
        return AssumptionResult(
            assumption="normality",
            test_name="Shapiro-Wilk",
            status=AssumptionStatus.NOT_RUN,
            blocking=True,
            group=group_label,
            detail={"n": int(n), "reason": "zero_variance"},
            message_tr="Değişkenin varyansı sıfır olduğu için normallik testi yapılamadı.",
        )

    if n < SHAPIRO_MAX_N:
        test_name = "Shapiro-Wilk"
        statistic, p_value = sps.shapiro(arr)
    else:
        test_name = "Kolmogorov-Smirnov (Lilliefors düzeltmeli)"
        statistic, p_value = lilliefors(arr, dist="norm", pvalmethod="table")

    met = bool(p_value > ALPHA)
    where = f" ({group_label})" if group_label else ""
    return AssumptionResult(
        assumption="normality",
        test_name=test_name,
        status=AssumptionStatus.MET if met else AssumptionStatus.VIOLATED,
        blocking=True,
        statistic=float(statistic),
        p_value=float(p_value),
        group=group_label,
        detail={"n": int(n), "alpha": ALPHA},
        message_tr=(
            f"Normallik varsayımı{where} karşılanmaktadır ({test_name}, p = {p_value:.3f} > .05)."
            if met else
            f"Normallik varsayımı{where} karşılanmamaktadır ({test_name}, p = {p_value:.3f} < .05)."
        ),
    )


def check_normality_by_group(
    values: Sequence[float], groups: Sequence[Any]
) -> list[AssumptionResult]:
    """Run the normality check separately in each group, as §3.4 requires."""
    frame = pd.DataFrame({"value": np.asarray(values, dtype=float), "group": list(groups)})
    results: list[AssumptionResult] = []
    for label, chunk in frame.groupby("group", sort=True, observed=True):
        results.append(check_normality(chunk["value"].to_numpy(), group_label=str(label)))
    return results


# ---------------------------------------------------------------------------
# Homogeneity of variance
# ---------------------------------------------------------------------------

def check_homogeneity(samples: Sequence[Sequence[float]]) -> AssumptionResult:
    """§3.4: Levene's test.

    `center="median"` (the Brown-Forsythe form) is used, matching scipy's and
    R `car::leveneTest`'s default. It is the robust variant and is what
    pingouin's `homoscedasticity` helper reports.
    """
    cleaned = [np.asarray(s, dtype=float) for s in samples]
    cleaned = [s[np.isfinite(s)] for s in cleaned]

    if len(cleaned) < 2 or any(s.size < 2 for s in cleaned):
        return AssumptionResult(
            assumption="homogeneity_of_variance",
            test_name="Levene",
            status=AssumptionStatus.NOT_RUN,
            blocking=True,
            message_tr="Varyans homojenliği testi için her grupta en az iki gözlem gerekir.",
        )
    if all(np.allclose(s, s[0]) for s in cleaned):
        return AssumptionResult(
            assumption="homogeneity_of_variance",
            test_name="Levene",
            status=AssumptionStatus.NOT_RUN,
            blocking=True,
            detail={"reason": "zero_variance"},
            message_tr="Tüm grupların varyansı sıfır olduğu için Levene testi yapılamadı.",
        )

    statistic, p_value = sps.levene(*cleaned, center="median")
    met = bool(p_value > ALPHA)
    return AssumptionResult(
        assumption="homogeneity_of_variance",
        test_name="Levene",
        status=AssumptionStatus.MET if met else AssumptionStatus.VIOLATED,
        blocking=True,
        statistic=float(statistic),
        p_value=float(p_value),
        detail={"center": "median", "k_groups": len(cleaned), "alpha": ALPHA},
        message_tr=(
            f"Varyansların homojenliği varsayımı karşılanmaktadır "
            f"(Levene F = {statistic:.3f}, p = {p_value:.3f} > .05)."
            if met else
            f"Varyansların homojenliği varsayımı karşılanmamaktadır "
            f"(Levene F = {statistic:.3f}, p = {p_value:.3f} < .05)."
        ),
    )


# ---------------------------------------------------------------------------
# Regression diagnostics
# ---------------------------------------------------------------------------

def check_multicollinearity(design: pd.DataFrame) -> list[AssumptionResult]:
    """§3.4: VIF per predictor, flagged above 10. `design` excludes the intercept."""
    if design.shape[1] < 2:
        return [AssumptionResult(
            assumption="multicollinearity",
            test_name="VIF",
            status=AssumptionStatus.NOT_APPLICABLE,
            message_tr="Tek yordayıcılı modelde çoklu bağlantı sorunu tanımlı değildir.",
        )]

    with_const = np.column_stack([np.ones(len(design)), design.to_numpy(dtype=float)])
    results: list[AssumptionResult] = []
    for idx, column in enumerate(design.columns, start=1):
        vif = float(variance_inflation_factor(with_const, idx))
        violated = np.isfinite(vif) and vif > VIF_THRESHOLD
        results.append(AssumptionResult(
            assumption="multicollinearity",
            test_name="VIF",
            status=AssumptionStatus.VIOLATED if violated else AssumptionStatus.MET,
            blocking=False,  # §3.4: flag only
            statistic=vif,
            group=str(column),
            detail={"threshold": VIF_THRESHOLD},
            message_tr=(
                f"{column} için çoklu bağlantı sorunu bulunmamaktadır (VIF = {vif:.2f} < 10)."
                if not violated else
                f"{column} için çoklu bağlantı riski vardır (VIF = {vif:.2f} > 10); "
                f"bu yordayıcının katsayısı dikkatle yorumlanmalıdır."
            ),
        ))
    return results


def check_homoscedasticity(residuals: Sequence[float], design_with_const: np.ndarray) -> AssumptionResult:
    """§3.4: Breusch-Pagan. Flagged in the report, never blocking."""
    resid = np.asarray(residuals, dtype=float)
    lm_stat, lm_p, _f_stat, _f_p = het_breuschpagan(resid, design_with_const)
    met = bool(lm_p > ALPHA)
    return AssumptionResult(
        assumption="homoscedasticity",
        test_name="Breusch-Pagan",
        status=AssumptionStatus.MET if met else AssumptionStatus.VIOLATED,
        blocking=False,  # §3.4: flag only
        statistic=float(lm_stat),
        p_value=float(lm_p),
        detail={"alpha": ALPHA},
        message_tr=(
            f"Hata varyanslarının sabitliği (homoskedastisite) varsayımı karşılanmaktadır "
            f"(Breusch-Pagan LM = {lm_stat:.3f}, p = {lm_p:.3f} > .05)."
            if met else
            f"Hata varyanslarının sabitliği varsayımı karşılanmamaktadır "
            f"(Breusch-Pagan LM = {lm_stat:.3f}, p = {lm_p:.3f} < .05); "
            f"standart hatalar dikkatle yorumlanmalıdır."
        ),
    )


def check_linearity(residuals: Sequence[float], fitted: Sequence[float]) -> AssumptionResult:
    """§3.4: residual-vs-fitted pattern. Visual flag in v1, never auto-blocking.

    We quantify the flag with the correlation between the fitted values and the
    squared residuals: a systematic relationship there is the numeric shadow of
    the curvature a reader would see in the plot. This only ever sets a flag —
    §3.4 says linearity does not block in v1.
    """
    resid = np.asarray(residuals, dtype=float)
    fit = np.asarray(fitted, dtype=float)

    if resid.size < 3 or np.allclose(fit, fit[0]):
        return AssumptionResult(
            assumption="linearity",
            test_name="Artık-tahmin grafiği (görsel kontrol)",
            status=AssumptionStatus.NOT_RUN,
            message_tr="Doğrusallık için görsel kontrol yapılamadı.",
        )

    corr = float(np.corrcoef(fit, resid ** 2)[0, 1]) if np.std(resid ** 2) > 0 else 0.0
    suspicious = abs(corr) > 0.5
    return AssumptionResult(
        assumption="linearity",
        test_name="Artık-tahmin grafiği (görsel kontrol)",
        status=AssumptionStatus.VIOLATED if suspicious else AssumptionStatus.MET,
        blocking=False,  # §3.4: "visual flag, not auto-blocking in v1"
        statistic=corr,
        detail={"metric": "corr(fitted, squared_residuals)", "flag_threshold": 0.5},
        message_tr=(
            "Artıkların dağılımında belirgin bir örüntü gözlenmemiştir; doğrusallık "
            "varsayımı için engelleyici bir bulgu yoktur."
            if not suspicious else
            "Artık-tahmin grafiğinde olası bir örüntü tespit edilmiştir; doğrusallık "
            "varsayımı görsel olarak incelenmelidir (bu sürümde analiz durdurulmaz)."
        ),
    )


# ---------------------------------------------------------------------------
# Chi-square
# ---------------------------------------------------------------------------

def check_expected_cell_counts(expected: np.ndarray) -> AssumptionResult:
    """§3.4: all expected counts >= 5, else flag Fisher's exact (v2) as an option."""
    expected = np.asarray(expected, dtype=float)
    minimum = float(expected.min())
    below = int((expected < MIN_EXPECTED_CELL_COUNT).sum())
    total = int(expected.size)
    met = below == 0
    share = 100.0 * below / total if total else 0.0
    return AssumptionResult(
        assumption="expected_cell_count",
        test_name="Beklenen göz frekansı kontrolü",
        status=AssumptionStatus.MET if met else AssumptionStatus.VIOLATED,
        blocking=False,  # §3.4: flag only
        statistic=minimum,
        detail={
            "min_expected": minimum,
            "cells_below_threshold": below,
            "total_cells": total,
            "share_below_threshold_pct": share,
            "threshold": MIN_EXPECTED_CELL_COUNT,
        },
        message_tr=(
            f"Tüm gözlerin beklenen frekansı 5'in üzerindedir (en küçük beklenen "
            f"frekans = {minimum:.2f}); ki-kare testinin varsayımı karşılanmaktadır."
            if met else
            f"{below}/{total} gözde beklenen frekans 5'in altındadır (en küçük beklenen "
            f"frekans = {minimum:.2f}). Ki-kare sonucu dikkatle yorumlanmalı; Fisher'ın "
            f"kesin testi düşünülebilir (bu sürümde desteklenmiyor)."
        ),
    )
