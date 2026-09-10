"""Association procedures: correlation, linear regression, chi-square, reliability."""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as sps

from app.stats import assumptions as assump
from app.stats import effect_size as es
from app.stats.results import GroupDescriptive, InsufficientDataError, TestResult


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def _clean_xy(x: Sequence[float], y: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    if xa.size != ya.size:
        raise InsufficientDataError("İki değişkenin gözlem sayısı eşit olmalıdır.")
    keep = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[keep], ya[keep]
    if xa.size < 3:
        raise InsufficientDataError("Korelasyon analizi için en az üç geçerli gözlem çifti gerekir.")
    return xa, ya


def correlation(
    x: Sequence[float],
    y: Sequence[float],
    *,
    method: str = "pearson",
    labels: tuple[str, str] = ("X", "Y"),
) -> TestResult:
    """Pearson (§3.3 candidate) or Spearman (§3.3 non-parametric fallback).

    r is itself the effect size (§3.5), so the same number is reported in both
    the statistics block and the effect-size block.
    """
    xa, ya = _clean_xy(x, y)
    if method == "pearson":
        r, p_value = sps.pearsonr(xa, ya)
        analysis_type, metric, coefficient = "pearson_correlation", "r", "r"
    elif method == "spearman":
        r, p_value = sps.spearmanr(xa, ya)
        analysis_type, metric, coefficient = "spearman_correlation", "rho", "rho"
    else:
        raise ValueError(f"Unsupported correlation method: {method!r}")

    n = int(xa.size)
    return TestResult(
        analysis_type=analysis_type,
        statistics={coefficient: float(r), "r_squared": float(r) ** 2},
        p_value=float(p_value),
        df={"df": float(n - 2)},
        effect_size=es.correlation_effect(float(r), metric=metric),
        descriptives=[
            GroupDescriptive(labels[0], n, float(xa.mean()), float(xa.std(ddof=1)), float(np.median(xa))),
            GroupDescriptive(labels[1], n, float(ya.mean()), float(ya.std(ddof=1)), float(np.median(ya))),
        ],
        n_total=n,
        extra={"method": method, "variables": list(labels)},
    )


# ---------------------------------------------------------------------------
# Linear regression (simple and multiple)
# ---------------------------------------------------------------------------

def linear_regression(
    y: Sequence[float],
    predictors: pd.DataFrame,
    *,
    dv_label: str = "Y",
) -> TestResult:
    """OLS regression via statsmodels.

    Handles both §3.3 leaves: one predictor is simple linear regression, more
    than one is multiple linear regression. The §3.4 regression diagnostics
    (linearity, multicollinearity, homoscedasticity) are attached here because
    they are computed from the fitted model rather than from the raw inputs.
    """
    ya = np.asarray(y, dtype=float)
    design = predictors.apply(pd.to_numeric, errors="coerce")
    if len(design) != ya.size:
        raise InsufficientDataError("Bağımlı değişken ile yordayıcıların gözlem sayısı eşit olmalıdır.")

    keep = np.isfinite(ya) & design.notna().all(axis=1).to_numpy()
    ya, design = ya[keep], design.loc[keep].reset_index(drop=True)

    k = design.shape[1]
    if ya.size <= k + 1:
        raise InsufficientDataError(
            "Regresyon analizi için gözlem sayısı yordayıcı sayısından yeterince büyük olmalıdır."
        )

    exog = sm.add_constant(design.to_numpy(dtype=float), has_constant="add")
    model = sm.OLS(ya, exog).fit()

    coefficients = []
    # Standardised betas: beta_j = b_j * (SD_xj / SD_y)
    sd_y = float(np.std(ya, ddof=1))
    for idx, name in enumerate(design.columns, start=1):
        sd_x = float(design[name].std(ddof=1))
        coefficients.append({
            "predictor": str(name),
            "b": float(model.params[idx]),
            "se": float(model.bse[idx]),
            "beta": float(model.params[idx] * sd_x / sd_y) if sd_y > 0 else 0.0,
            "t": float(model.tvalues[idx]),
            "p": float(model.pvalues[idx]),
            "ci_low": float(model.conf_int()[idx][0]),
            "ci_high": float(model.conf_int()[idx][1]),
        })

    diagnostics = [
        assump.check_linearity(model.resid, model.fittedvalues),
        assump.check_homoscedasticity(model.resid, exog),
    ]
    diagnostics.extend(assump.check_multicollinearity(design))

    analysis_type = "simple_linear_regression" if k == 1 else "multiple_linear_regression"
    return TestResult(
        analysis_type=analysis_type,
        statistics={
            "F": float(model.fvalue),
            "R": float(np.sqrt(max(model.rsquared, 0.0))),
            "r_squared": float(model.rsquared),
            "adjusted_r_squared": float(model.rsquared_adj),
            "intercept": float(model.params[0]),
            "intercept_se": float(model.bse[0]),
            "std_error_of_estimate": float(np.sqrt(model.mse_resid)),
        },
        p_value=float(model.f_pvalue),
        df={"df_model": float(model.df_model), "df_residual": float(model.df_resid)},
        effect_size=es.r_squared_effect(model.rsquared, model.rsquared_adj),
        descriptives=[
            GroupDescriptive(dv_label, int(ya.size), float(ya.mean()), sd_y, float(np.median(ya)))
        ] + [
            GroupDescriptive(
                str(name), int(ya.size), float(design[name].mean()),
                float(design[name].std(ddof=1)), float(design[name].median()),
            )
            for name in design.columns
        ],
        assumption_results=diagnostics,
        n_total=int(ya.size),
        extra={
            "coefficients": coefficients,
            "predictors": [str(c) for c in design.columns],
            "dependent_variable": dv_label,
        },
    )


# ---------------------------------------------------------------------------
# Chi-square test of independence
# ---------------------------------------------------------------------------

def chi_square_independence(
    row_variable: Sequence[Any],
    column_variable: Sequence[Any],
    *,
    labels: tuple[str, str] = ("Satır", "Sütun"),
) -> TestResult:
    """Pearson chi-square on the contingency table of two categorical variables.

    Yates' continuity correction is deliberately NOT applied: §3.3/§3.5 specify
    a plain chi-square of independence with Cramér's V, and applying the
    correction only in the 2x2 case would make results inconsistent across table
    shapes. §3.4's expected-cell-count check is attached to the result.
    """
    frame = pd.DataFrame({"row": list(row_variable), "col": list(column_variable)}).dropna()
    if frame.empty:
        raise InsufficientDataError("Ki-kare testi için geçerli gözlem bulunamadı.")

    table = pd.crosstab(frame["row"], frame["col"])
    if table.shape[0] < 2 or table.shape[1] < 2:
        raise InsufficientDataError(
            "Ki-kare bağımsızlık testi için her iki değişkenin de en az iki düzeyi olmalıdır."
        )

    chi2, p_value, dof, expected = sps.chi2_contingency(table.to_numpy(), correction=False)
    n = int(table.to_numpy().sum())

    descriptives = [
        GroupDescriptive(label=f"{row_label} — {col_label}", n=int(table.loc[row_label, col_label]))
        for row_label in table.index
        for col_label in table.columns
    ]

    return TestResult(
        analysis_type="chi_square_independence",
        statistics={"chi2": float(chi2)},
        p_value=float(p_value),
        df={"df": float(dof)},
        effect_size=es.cramers_v(float(chi2), n, table.shape[0], table.shape[1]),
        descriptives=descriptives,
        assumption_results=[assump.check_expected_cell_counts(expected)],
        n_total=n,
        extra={
            "observed": table.to_dict(orient="split"),
            "expected": [[float(v) for v in row] for row in expected],
            "row_labels": [str(i) for i in table.index],
            "column_labels": [str(c) for c in table.columns],
            "variables": list(labels),
            "yates_correction_applied": False,
        },
    )


# ---------------------------------------------------------------------------
# Cronbach's alpha
# ---------------------------------------------------------------------------

def cronbachs_alpha(items: pd.DataFrame) -> TestResult:
    """Cronbach's alpha with per-item "alpha if deleted", the standard companion
    column in a Turkish thesis reliability table.

        alpha = k/(k-1) * (1 - sum(item variances) / variance of total score)

    Written out explicitly rather than delegated so the unit test can check it
    against hand computation; pingouin's `cronbach_alpha` supplies the CI.
    """
    numeric = items.apply(pd.to_numeric, errors="coerce").dropna()
    k = numeric.shape[1]
    if k < 2:
        raise InsufficientDataError("Güvenirlik analizi için en az iki madde gerekir.")
    if numeric.shape[0] < 2:
        raise InsufficientDataError("Güvenirlik analizi için en az iki geçerli gözlem gerekir.")

    def _alpha(frame: pd.DataFrame) -> float:
        n_items = frame.shape[1]
        item_variance = frame.var(ddof=1).sum()
        total_variance = frame.sum(axis=1).var(ddof=1)
        if total_variance <= 0 or n_items < 2:
            return float("nan")
        return float(n_items / (n_items - 1) * (1 - item_variance / total_variance))

    alpha = _alpha(numeric)

    try:
        import pingouin as pg
        _, ci = pg.cronbach_alpha(data=numeric)
        ci_low, ci_high = float(ci[0]), float(ci[1])
    except Exception:  # pragma: no cover — CI is a nicety, alpha is the result
        ci_low = ci_high = float("nan")

    total_score = numeric.sum(axis=1)
    item_stats = []
    for column in numeric.columns:
        rest = numeric.drop(columns=[column])
        corrected_total = rest.sum(axis=1)
        item_stats.append({
            "item": str(column),
            "mean": float(numeric[column].mean()),
            "sd": float(numeric[column].std(ddof=1)),
            "corrected_item_total_correlation": (
                float(numeric[column].corr(corrected_total))
                if corrected_total.std(ddof=1) > 0 else float("nan")
            ),
            "alpha_if_deleted": _alpha(rest) if rest.shape[1] >= 2 else float("nan"),
        })

    return TestResult(
        analysis_type="cronbachs_alpha",
        statistics={
            "alpha": alpha,
            "n_items": float(k),
            "ci_low": ci_low,
            "ci_high": ci_high,
            "scale_mean": float(total_score.mean()),
            "scale_sd": float(total_score.std(ddof=1)),
        },
        # Reliability is a coefficient, not a hypothesis test: there is no p.
        # We surface NaN rather than a fabricated 1.0 so the APA table and the
        # §3.6 validator never present a significance claim that does not exist.
        p_value=float("nan"),
        df={},
        effect_size=es.alpha_effect(alpha),
        descriptives=[
            GroupDescriptive(str(c), int(numeric.shape[0]), float(numeric[c].mean()),
                             float(numeric[c].std(ddof=1)), float(numeric[c].median()))
            for c in numeric.columns
        ],
        n_total=int(numeric.shape[0]),
        extra={"item_statistics": item_stats, "items": [str(c) for c in numeric.columns]},
    )
