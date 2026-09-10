"""Mean-comparison procedures: t-tests, ANOVA, and their non-parametric peers.

Every function here is deterministic and takes plain arrays — no dataframes,
no database, no LLM. Effect sizes come from `app.stats.effect_size` (§3.5) and
are attached to every result, because §3.5 makes them mandatory.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.stats import effect_size as es
from app.stats.results import GroupDescriptive, InsufficientDataError, TestResult


def _clean_pair(group1: Sequence[float], group2: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    x1 = np.asarray(group1, dtype=float)
    x2 = np.asarray(group2, dtype=float)
    x1, x2 = x1[np.isfinite(x1)], x2[np.isfinite(x2)]
    if x1.size < 2 or x2.size < 2:
        raise InsufficientDataError(
            "Her grupta en az iki geçerli gözlem bulunmalıdır."
        )
    return x1, x2


def _descriptive(label: str, values: np.ndarray) -> GroupDescriptive:
    return GroupDescriptive(
        label=label,
        n=int(values.size),
        mean=float(np.mean(values)),
        sd=float(np.std(values, ddof=1)) if values.size > 1 else None,
        median=float(np.median(values)),
    )


# ---------------------------------------------------------------------------
# Independent samples t-test / Welch's t-test
# ---------------------------------------------------------------------------

def independent_t_test(
    group1: Sequence[float],
    group2: Sequence[float],
    *,
    labels: tuple[str, str] = ("Grup 1", "Grup 2"),
    equal_var: bool = True,
) -> TestResult:
    """Student's t (equal_var=True) or Welch's t (equal_var=False, §3.4)."""
    x1, x2 = _clean_pair(group1, group2)
    t_stat, p_value = sps.ttest_ind(x1, x2, equal_var=equal_var)

    if equal_var:
        df = float(x1.size + x2.size - 2)
    else:
        # Welch-Satterthwaite degrees of freedom
        v1, v2 = np.var(x1, ddof=1) / x1.size, np.var(x2, ddof=1) / x2.size
        df = float((v1 + v2) ** 2 / (v1 ** 2 / (x1.size - 1) + v2 ** 2 / (x2.size - 1)))

    return TestResult(
        analysis_type="independent_t_test" if equal_var else "welch_t_test",
        statistics={"t": float(t_stat), "mean_difference": float(x1.mean() - x2.mean())},
        p_value=float(p_value),
        df={"df": df},
        effect_size=es.cohens_d_independent(x1, x2),
        descriptives=[_descriptive(labels[0], x1), _descriptive(labels[1], x2)],
        n_total=int(x1.size + x2.size),
        extra={"equal_variance_assumed": bool(equal_var)},
    )


# ---------------------------------------------------------------------------
# Paired samples t-test
# ---------------------------------------------------------------------------

def paired_t_test(
    before: Sequence[float],
    after: Sequence[float],
    *,
    labels: tuple[str, str] = ("Ölçüm 1", "Ölçüm 2"),
) -> TestResult:
    """t on the pairwise differences (`before - after`); pairs with a missing
    value on either side are dropped listwise."""
    x1 = np.asarray(before, dtype=float)
    x2 = np.asarray(after, dtype=float)
    if x1.size != x2.size:
        raise InsufficientDataError(
            "Bağımlı örneklem t-testi için iki ölçümün gözlem sayısı eşit olmalıdır."
        )
    keep = np.isfinite(x1) & np.isfinite(x2)
    x1, x2 = x1[keep], x2[keep]
    if x1.size < 2:
        raise InsufficientDataError("Bağımlı örneklem t-testi için en az iki eşleşmiş gözlem gerekir.")

    t_stat, p_value = sps.ttest_rel(x1, x2)
    diff = x1 - x2
    return TestResult(
        analysis_type="paired_t_test",
        statistics={"t": float(t_stat), "mean_difference": float(diff.mean())},
        p_value=float(p_value),
        df={"df": float(x1.size - 1)},
        effect_size=es.cohens_d_paired(x1, x2),
        descriptives=[_descriptive(labels[0], x1), _descriptive(labels[1], x2)],
        n_total=int(x1.size),
        extra={"n_pairs": int(x1.size), "sd_difference": float(np.std(diff, ddof=1))},
    )


# ---------------------------------------------------------------------------
# One-way ANOVA / Welch's ANOVA
# ---------------------------------------------------------------------------

def one_way_anova(
    values: Sequence[float],
    groups: Sequence[Any],
    *,
    equal_var: bool = True,
) -> TestResult:
    """One-way ANOVA (equal_var=True) or Welch's ANOVA (equal_var=False, §3.4).

    η² is always computed from the ordinary sum-of-squares decomposition, so it
    stays comparable across the two variants (§3.5 asks for η² for "ANOVA",
    without distinguishing them).
    """
    frame = pd.DataFrame({"value": np.asarray(values, dtype=float), "group": list(groups)})
    frame = frame[np.isfinite(frame["value"])]
    samples, descriptives = [], []
    for label, chunk in frame.groupby("group", sort=True, observed=True):
        arr = chunk["value"].to_numpy(dtype=float)
        if arr.size < 2:
            raise InsufficientDataError(
                f"'{label}' grubunda en az iki geçerli gözlem bulunmalıdır."
            )
        samples.append(arr)
        descriptives.append(_descriptive(str(label), arr))

    k = len(samples)
    if k < 3:
        raise InsufficientDataError("Tek yönlü ANOVA için en az üç grup gerekir.")

    all_values = np.concatenate(samples)
    n_total = all_values.size
    grand_mean = all_values.mean()
    ss_between = float(sum(s.size * (s.mean() - grand_mean) ** 2 for s in samples))
    ss_within = float(sum(((s - s.mean()) ** 2).sum() for s in samples))
    ss_total = ss_between + ss_within

    if equal_var:
        f_stat, p_value = sps.f_oneway(*samples)
        df1, df2 = float(k - 1), float(n_total - k)
        analysis_type = "one_way_anova"
    else:
        # Welch's ANOVA — statsmodels' implementation, with its own df2.
        from statsmodels.stats.oneway import anova_oneway

        welch = anova_oneway(samples, use_var="unequal", welch_correction=True)
        f_stat, p_value = float(welch.statistic), float(welch.pvalue)
        df1, df2 = float(welch.df_num), float(welch.df_denom)
        analysis_type = "welch_anova"

    return TestResult(
        analysis_type=analysis_type,
        statistics={
            "F": float(f_stat),
            "ss_between": ss_between,
            "ss_within": ss_within,
            "ss_total": ss_total,
            "ms_between": ss_between / (k - 1) if k > 1 else float("nan"),
            "ms_within": ss_within / (n_total - k) if n_total > k else float("nan"),
        },
        p_value=float(p_value),
        df={"df_between": df1, "df_within": df2},
        effect_size=es.eta_squared(ss_between, ss_total),
        descriptives=descriptives,
        n_total=int(n_total),
        extra={"k_groups": k, "equal_variance_assumed": bool(equal_var)},
    )


# ---------------------------------------------------------------------------
# Mann-Whitney U
# ---------------------------------------------------------------------------

def mann_whitney_u(
    group1: Sequence[float],
    group2: Sequence[float],
    *,
    labels: tuple[str, str] = ("Grup 1", "Grup 2"),
) -> TestResult:
    """Non-parametric fallback for the independent t-test (§3.3)."""
    x1, x2 = _clean_pair(group1, group2)
    u_stat, p_value = sps.mannwhitneyu(x1, x2, alternative="two-sided")

    ranks = sps.rankdata(np.concatenate([x1, x2]))
    mean_rank_1 = float(ranks[: x1.size].mean())
    mean_rank_2 = float(ranks[x1.size:].mean())

    d1, d2 = _descriptive(labels[0], x1), _descriptive(labels[1], x2)
    d1.mean_rank, d2.mean_rank = mean_rank_1, mean_rank_2

    return TestResult(
        analysis_type="mann_whitney_u",
        statistics={
            "U": float(u_stat),
            "z": float(_mwu_z(float(u_stat), x1.size, x2.size)),
            "rank_sum_1": float(ranks[: x1.size].sum()),
            "rank_sum_2": float(ranks[x1.size:].sum()),
        },
        p_value=float(p_value),
        df={},
        effect_size=es.rank_biserial_mann_whitney(float(u_stat), x1.size, x2.size),
        descriptives=[d1, d2],
        n_total=int(x1.size + x2.size),
    )


def _mwu_z(u: float, n1: int, n2: int) -> float:
    """Normal approximation of U, reported alongside U as APA convention expects."""
    mean_u = n1 * n2 / 2.0
    sd_u = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
    return (u - mean_u) / sd_u if sd_u > 0 else 0.0


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank
# ---------------------------------------------------------------------------

def wilcoxon_signed_rank(
    before: Sequence[float],
    after: Sequence[float],
    *,
    labels: tuple[str, str] = ("Ölçüm 1", "Ölçüm 2"),
) -> TestResult:
    """Non-parametric fallback for the paired t-test (§3.3)."""
    x1 = np.asarray(before, dtype=float)
    x2 = np.asarray(after, dtype=float)
    if x1.size != x2.size:
        raise InsufficientDataError("Wilcoxon testi için iki ölçümün gözlem sayısı eşit olmalıdır.")
    keep = np.isfinite(x1) & np.isfinite(x2)
    x1, x2 = x1[keep], x2[keep]
    diff = x1 - x2
    nonzero = diff[diff != 0]
    if nonzero.size < 1:
        raise InsufficientDataError(
            "Wilcoxon testi için sıfırdan farklı en az bir fark bulunmalıdır."
        )

    w_stat, p_value = sps.wilcoxon(x1, x2)

    # Split the signed ranks so the rank-biserial effect size (§3.5) has both
    # halves; scipy returns only the smaller of the two sums.
    abs_ranks = sps.rankdata(np.abs(nonzero))
    w_pos = float(abs_ranks[nonzero > 0].sum())
    w_neg = float(abs_ranks[nonzero < 0].sum())

    d1, d2 = _descriptive(labels[0], x1), _descriptive(labels[1], x2)
    return TestResult(
        analysis_type="wilcoxon_signed_rank",
        statistics={"W": float(w_stat), "W_positive": w_pos, "W_negative": w_neg},
        p_value=float(p_value),
        df={},
        effect_size=es.rank_biserial_wilcoxon(w_pos, w_neg),
        descriptives=[d1, d2],
        n_total=int(x1.size),
        extra={"n_pairs": int(x1.size), "n_nonzero_differences": int(nonzero.size)},
    )


# ---------------------------------------------------------------------------
# Kruskal-Wallis H
# ---------------------------------------------------------------------------

def kruskal_wallis(values: Sequence[float], groups: Sequence[Any]) -> TestResult:
    """Non-parametric fallback for the one-way ANOVA (§3.3)."""
    frame = pd.DataFrame({"value": np.asarray(values, dtype=float), "group": list(groups)})
    frame = frame[np.isfinite(frame["value"])]
    frame["rank"] = sps.rankdata(frame["value"].to_numpy())

    samples, descriptives = [], []
    for label, chunk in frame.groupby("group", sort=True, observed=True):
        arr = chunk["value"].to_numpy(dtype=float)
        if arr.size < 1:
            raise InsufficientDataError(f"'{label}' grubunda geçerli gözlem bulunmuyor.")
        samples.append(arr)
        descriptive = _descriptive(str(label), arr)
        descriptive.mean_rank = float(chunk["rank"].mean())
        descriptives.append(descriptive)

    if len(samples) < 3:
        raise InsufficientDataError("Kruskal-Wallis testi için en az üç grup gerekir.")

    h_stat, p_value = sps.kruskal(*samples)
    n_total = int(sum(s.size for s in samples))

    return TestResult(
        analysis_type="kruskal_wallis",
        statistics={"H": float(h_stat)},
        p_value=float(p_value),
        df={"df": float(len(samples) - 1)},
        effect_size=es.epsilon_squared_kruskal(float(h_stat), n_total),
        descriptives=descriptives,
        n_total=n_total,
        extra={"k_groups": len(samples)},
    )
