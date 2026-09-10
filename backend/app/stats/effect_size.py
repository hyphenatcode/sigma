"""Effect size calculation and band lookup (§3.5).

Mandatory for every test — §3.5 is explicit that this is a product requirement,
not an option. Each function returns an `EffectSize` carrying the value, the
metric name, the band it falls in, and the thresholds used, so the report can
show the reader *why* an effect was called "orta düzeyde".

All formulas are written out explicitly rather than delegated, so the unit
tests in tests/test_effect_size.py can check them against hand computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

from app.stats.enums import EffectSizeBand

#: §3.5 threshold tables, keyed by metric. Ordered (small, medium, large).
BANDS: dict[str, tuple[float, float, float]] = {
    "cohens_d": (0.2, 0.5, 0.8),
    "eta_squared": (0.01, 0.06, 0.14),
    "partial_eta_squared": (0.01, 0.06, 0.14),
    "epsilon_squared": (0.01, 0.06, 0.14),
    "r": (0.1, 0.3, 0.5),
    "rho": (0.1, 0.3, 0.5),
    "rank_biserial_r": (0.1, 0.3, 0.5),
    "cramers_v": (0.1, 0.3, 0.5),  # df-adjusted at call time, see cramers_v()
}

#: Metrics §3.5 says to report without a band.
UNBANDED = {"r_squared", "adjusted_r_squared", "alpha"}

BAND_LABEL_TR: dict[EffectSizeBand, str] = {
    EffectSizeBand.NEGLIGIBLE: "çok küçük",
    EffectSizeBand.SMALL: "küçük",
    EffectSizeBand.MEDIUM: "orta",
    EffectSizeBand.LARGE: "büyük",
    EffectSizeBand.NOT_BANDED: "bantlandırılmamış",
}


@dataclass
class EffectSize:
    metric: str
    value: float
    band: EffectSizeBand
    label_tr: str
    thresholds: Optional[tuple[float, float, float]] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": float(self.value),
            "band": self.band.value,
            "label_tr": self.label_tr,
            "thresholds": list(self.thresholds) if self.thresholds else None,
            "extra": self.extra,
        }


def band_for(metric: str, value: float, thresholds: Optional[tuple[float, float, float]] = None) -> EffectSizeBand:
    """Look up the §3.5 band. Magnitude only — direction is carried separately."""
    if metric in UNBANDED:
        return EffectSizeBand.NOT_BANDED
    cuts = thresholds or BANDS.get(metric)
    if cuts is None:
        return EffectSizeBand.NOT_BANDED

    magnitude = abs(float(value))
    small, medium, large = cuts
    if magnitude >= large:
        return EffectSizeBand.LARGE
    if magnitude >= medium:
        return EffectSizeBand.MEDIUM
    if magnitude >= small:
        return EffectSizeBand.SMALL
    return EffectSizeBand.NEGLIGIBLE


def _make(metric: str, value: float, thresholds=None, **extra) -> EffectSize:
    cuts = thresholds or BANDS.get(metric)
    band = band_for(metric, value, cuts)
    return EffectSize(
        metric=metric,
        value=float(value),
        band=band,
        label_tr=BAND_LABEL_TR[band],
        thresholds=cuts if band is not EffectSizeBand.NOT_BANDED else None,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# t-test family — Cohen's d (§3.5: 0.2 / 0.5 / 0.8)
# ---------------------------------------------------------------------------

def cohens_d_independent(group1: Sequence[float], group2: Sequence[float]) -> EffectSize:
    """d = (M1 - M2) / SD_pooled, with the (n-1)-weighted pooled SD.

        SD_pooled = sqrt( ((n1-1)*s1^2 + (n2-1)*s2^2) / (n1 + n2 - 2) )

    Sign is positive when group 1 has the larger mean.
    """
    x1 = np.asarray(group1, dtype=float)
    x2 = np.asarray(group2, dtype=float)
    n1, n2 = x1.size, x2.size
    s1, s2 = np.var(x1, ddof=1), np.var(x2, ddof=1)
    pooled = np.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    d = (x1.mean() - x2.mean()) / pooled if pooled > 0 else 0.0
    return _make("cohens_d", d, pooled_sd=float(pooled), n1=int(n1), n2=int(n2),
                 formulation="pooled SD (independent samples)")


def cohens_d_paired(before: Sequence[float], after: Sequence[float]) -> EffectSize:
    """d_z = M_diff / SD_diff, the standard paired-samples Cohen's d.

    Sign is positive when `before` exceeds `after`, matching the direction of
    the paired t statistic computed on `before - after`.
    """
    diff = np.asarray(before, dtype=float) - np.asarray(after, dtype=float)
    sd = np.std(diff, ddof=1)
    d = diff.mean() / sd if sd > 0 else 0.0
    return _make("cohens_d", d, sd_diff=float(sd), n_pairs=int(diff.size),
                 formulation="d_z (mean difference / SD of differences)")


# ---------------------------------------------------------------------------
# ANOVA family — eta squared (§3.5: 0.01 / 0.06 / 0.14)
# ---------------------------------------------------------------------------

def eta_squared(ss_between: float, ss_total: float) -> EffectSize:
    """η² = SS_between / SS_total. For a one-way design η² == partial η²."""
    value = float(ss_between) / float(ss_total) if ss_total > 0 else 0.0
    return _make("eta_squared", value, ss_between=float(ss_between), ss_total=float(ss_total))


def partial_eta_squared(ss_effect: float, ss_error: float) -> EffectSize:
    """partial η² = SS_effect / (SS_effect + SS_error)."""
    denominator = float(ss_effect) + float(ss_error)
    value = float(ss_effect) / denominator if denominator > 0 else 0.0
    return _make("partial_eta_squared", value, ss_effect=float(ss_effect), ss_error=float(ss_error))


# ---------------------------------------------------------------------------
# Correlation — r is itself the effect size (§3.5: 0.1 / 0.3 / 0.5)
# ---------------------------------------------------------------------------

def correlation_effect(r: float, *, metric: str = "r") -> EffectSize:
    return _make(metric, float(r), direction="pozitif" if r >= 0 else "negatif")


# ---------------------------------------------------------------------------
# Regression — R² / adjusted R², reported but NOT banded (§3.5)
# ---------------------------------------------------------------------------

def r_squared_effect(r_squared: float, adjusted: float) -> EffectSize:
    effect = _make("r_squared", float(r_squared), adjusted_r_squared=float(adjusted))
    effect.label_tr = f"açıklanan varyans %{100 * float(r_squared):.1f}"
    return effect


# ---------------------------------------------------------------------------
# Chi-square — Cramér's V (§3.5: 0.1 / 0.3 / 0.5, "df-dependent, standard table")
# ---------------------------------------------------------------------------

def cramers_v(chi2: float, n: int, n_rows: int, n_cols: int) -> EffectSize:
    """V = sqrt( chi2 / (n * df*) ) where df* = min(rows, cols) - 1.

    §3.5 asks for the df-dependent standard table. Cohen's (1988) table is
    generated by dividing the 0.1/0.3/0.5 benchmarks by sqrt(df*), which is
    what we do here — for a 2x2 table (df* = 1) this reproduces the plain
    0.1/0.3/0.5 cuts, for df* = 2 it gives .07/.21/.35, and so on.
    """
    df_star = max(min(int(n_rows), int(n_cols)) - 1, 1)
    value = float(np.sqrt(float(chi2) / (int(n) * df_star))) if n > 0 else 0.0
    scale = float(np.sqrt(df_star))
    thresholds = (0.1 / scale, 0.3 / scale, 0.5 / scale)
    return _make("cramers_v", value, thresholds=thresholds,
                 df_star=df_star, n=int(n), n_rows=int(n_rows), n_cols=int(n_cols))


# ---------------------------------------------------------------------------
# Non-parametric equivalents (§3.5: rank-biserial r / epsilon-squared)
# ---------------------------------------------------------------------------

def rank_biserial_mann_whitney(u1: float, n1: int, n2: int) -> EffectSize:
    """r_rb = 2*U1/(n1*n2) - 1, positive when group 1 tends to rank higher.

    `u1` is the U statistic computed for group 1 (scipy's `mannwhitneyu`
    returns exactly this when group 1 is passed first).
    """
    denominator = int(n1) * int(n2)
    value = (2.0 * float(u1) / denominator) - 1.0 if denominator else 0.0
    return _make("rank_biserial_r", value, u1=float(u1), n1=int(n1), n2=int(n2))


def rank_biserial_wilcoxon(w_positive: float, w_negative: float) -> EffectSize:
    """r_rb = (W+ - W-) / (W+ + W-) for the signed-rank test."""
    total = float(w_positive) + float(w_negative)
    value = (float(w_positive) - float(w_negative)) / total if total > 0 else 0.0
    return _make("rank_biserial_r", value, w_positive=float(w_positive), w_negative=float(w_negative))


def epsilon_squared_kruskal(h: float, n: int) -> EffectSize:
    """ε² = H / ((n^2 - 1)/(n + 1)) = H*(n+1)/(n^2-1), the standard KW effect size."""
    n = int(n)
    value = float(h) * (n + 1) / (n ** 2 - 1) if n > 1 else 0.0
    return _make("epsilon_squared", value, h=float(h), n=n)


def alpha_effect(alpha: float) -> EffectSize:
    """Cronbach's alpha reports itself; §3.5 gives no band, so we label by the
    conventional reliability floor rather than inventing a small/medium/large
    reading of a reliability coefficient."""
    value = float(alpha)
    if value >= 0.90:
        label = "mükemmel"
    elif value >= 0.80:
        label = "iyi"
    elif value >= 0.70:
        label = "kabul edilebilir"
    elif value >= 0.60:
        label = "sınırda"
    else:
        label = "yetersiz"
    effect = EffectSize(
        metric="alpha", value=value, band=EffectSizeBand.NOT_BANDED,
        label_tr=label, thresholds=None,
        extra={"convention": "Nunnally (1978) reliability floor of .70"},
    )
    return effect
