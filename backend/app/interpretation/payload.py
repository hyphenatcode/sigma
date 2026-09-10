"""The §3.6 interpretation payload.

This is the ONLY thing the LLM ever sees about an analysis: computed values,
never raw data. Building it here (rather than handing the LLM a `TestResult`)
makes the boundary explicit and auditable — there is no code path from an
uploaded dataset's rows to the Anthropic API, which is also what §5's KVKK
requirement demands.

The same payload is what the numeric-token validator whitelists against, so the
rule "the LLM may only restate numbers it was given" is enforced against
exactly the numbers it was given.
"""

from __future__ import annotations

from typing import Any, Optional

from app.stats.registry import get as get_spec
from app.stats.results import TestResult


def build_payload(result: TestResult, *, variable_labels: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Reduce a TestResult to the fixed JSON payload described in §3.6."""
    spec = get_spec(result.analysis_type)
    effect = result.effect_size

    payload: dict[str, Any] = {
        "analysis_type": result.analysis_type,
        "test_name_tr": spec.label_tr,
        "statistics": {k: v for k, v in result.statistics.items() if _is_number(v)},
        "df": dict(result.df),
        "p_value": result.p_value,
        "alpha": result.alpha,
        "is_significant": result.is_significant,
        "n_total": result.n_total,
        "effect_size": (
            {
                "metric": effect.metric,
                "value": effect.value,
                "band": effect.band.value,
                "band_label_tr": effect.label_tr,
                "thresholds": list(effect.thresholds) if effect.thresholds else None,
            }
            if effect else None
        ),
        "group_descriptives": [
            {k: v for k, v in d.to_dict().items() if v is not None}
            for d in result.descriptives
        ],
        "substitution_note_tr": result.substitution_note_tr,
        "assumptions": [
            {
                "assumption": a.assumption,
                "test_name": a.test_name,
                "status": a.status.value,
                "group": a.group,
                # Computed values, so the narrative may legitimately cite them
                # ("normallik varsayimi karsilanmistir, p = .883").
                "statistic": a.statistic,
                "p_value": a.p_value,
            }
            for a in result.assumption_results
        ],
    }

    # Test-specific extras the narrative needs, kept to computed values only.
    if result.analysis_type in ("simple_linear_regression", "multiple_linear_regression"):
        payload["coefficients"] = result.extra.get("coefficients", [])
        payload["dependent_variable"] = result.extra.get("dependent_variable")
        payload["predictors"] = result.extra.get("predictors", [])
    if result.analysis_type == "chi_square_independence":
        payload["variables"] = result.extra.get("variables", [])
        payload["row_labels"] = result.extra.get("row_labels", [])
        payload["column_labels"] = result.extra.get("column_labels", [])
    if result.analysis_type == "cronbachs_alpha":
        payload["items"] = result.extra.get("items", [])
    if result.analysis_type in ("pearson_correlation", "spearman_correlation"):
        payload["variables"] = result.extra.get("variables", [])

    if variable_labels:
        payload["variable_labels"] = dict(variable_labels)
    return payload


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
