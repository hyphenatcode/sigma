"""The single result shape every statistical procedure returns.

This is the contract that keeps the LLM out of the numbers: `TestResult` is
produced only by deterministic Python, and everything downstream (APA tables in
§3.7, the Turkish interpretation in §3.6, the exports in §3.8) reads from it.
The interpretation layer's numeric-token validator (§3.6) whitelists exactly
the values reachable from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from app.stats.assumptions import AssumptionResult
from app.stats.effect_size import EffectSize


@dataclass
class GroupDescriptive:
    """Per-group descriptives, shown in APA tables and given to the LLM (§3.6)."""

    label: str
    n: int
    mean: Optional[float] = None
    sd: Optional[float] = None
    median: Optional[float] = None
    mean_rank: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n": int(self.n),
            "mean": _num(self.mean),
            "sd": _num(self.sd),
            "median": _num(self.median),
            "mean_rank": _num(self.mean_rank),
        }


@dataclass
class TestResult:
    """Output of one statistical procedure.

    `statistics` holds the test-specific numbers (t, F, U, H, chi2, B, beta...).
    `df` is a dict because tests differ in shape (one df for t, two for F).
    """

    analysis_type: str
    statistics: dict[str, float]
    p_value: float
    df: dict[str, float] = field(default_factory=dict)
    effect_size: Optional[EffectSize] = None
    descriptives: list[GroupDescriptive] = field(default_factory=list)
    assumption_results: list[AssumptionResult] = field(default_factory=list)
    n_total: int = 0
    alpha: float = 0.05
    #: filled in by the pipeline when §3.4 changed the test away from §3.3's pick
    substitution_note_tr: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_significant(self) -> bool:
        return bool(self.p_value < self.alpha)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type,
            "statistics": {k: _num(v) for k, v in self.statistics.items()},
            "p_value": _num(self.p_value),
            "df": {k: _num(v) for k, v in self.df.items()},
            "effect_size": self.effect_size.to_dict() if self.effect_size else None,
            "descriptives": [d.to_dict() for d in self.descriptives],
            "assumption_results": [a.to_dict() for a in self.assumption_results],
            "n_total": int(self.n_total),
            "alpha": self.alpha,
            "is_significant": self.is_significant,
            "substitution_note_tr": self.substitution_note_tr,
            "extra": self.extra,
        }


def _num(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [_num(v) for v in value]
    try:
        out = float(value)
    except (TypeError, ValueError):
        return value
    return None if not np.isfinite(out) else out


class InsufficientDataError(ValueError):
    """Raised when a procedure cannot run on the data it was handed.

    Surfaces to the user as an explicit Turkish message — never as a silently
    substituted different test (§3.3).
    """

    def __init__(self, message_tr: str):
        super().__init__(message_tr)
        self.message_tr = message_tr
