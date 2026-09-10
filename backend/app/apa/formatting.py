"""APA 7th-edition number formatting (§3.7).

Deterministic string rendering, used by the APA tables, the Turkish
interpretation templates and the exports alike — so the same number never
appears with two different roundings across the preview, the Word file and the
PDF. It is also what the §3.6 numeric-token validator builds its whitelist
from, so every rule here widens the set of renderings the validator accepts.

Turkish output uses a comma as the decimal separator, which is the convention
in Turkish theses; the validator is aware of both separators.
"""

from __future__ import annotations

import math
from typing import Optional

#: Statistics that cannot exceed 1 in absolute value drop the leading zero
#: (APA 7th ed., §6.36): p, r, R^2, eta^2, Cramer's V, alpha...
BOUNDED_STATISTICS = {
    "p", "r", "rho", "r_squared", "adjusted_r_squared", "eta_squared",
    "partial_eta_squared", "epsilon_squared", "cramers_v", "rank_biserial_r",
    "alpha", "beta", "R",
}


def strip_leading_zero(text: str) -> str:
    """'0.35' -> '.35', '-0.35' -> '-.35'. Leaves '10.35' alone."""
    if text.startswith("0."):
        return text[1:]
    if text.startswith("-0."):
        return "-" + text[2:]
    return text


def fmt(value: Optional[float], decimals: int = 2, *, bounded: bool = False) -> str:
    """Format one number APA-style. Returns an em dash for missing values."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"

    text = f"{number:.{decimals}f}"
    if text.startswith("-") and float(text) == 0.0:
        text = text[1:]  # avoid "-0.00"
    return strip_leading_zero(text) if bounded else text


def fmt_p(p_value: Optional[float]) -> str:
    """APA p-value convention: three decimals, no leading zero, '< .001' floor.

    Returns an em dash when there is no p value at all (Cronbach's alpha), so a
    table never implies a significance test that was not run.
    """
    if p_value is None:
        return "—"
    try:
        number = float(p_value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    if number < 0.001:
        return "< .001"
    return strip_leading_zero(f"{number:.3f}")


def fmt_df(value: Optional[float]) -> str:
    """Integer df prints without decimals; Welch/Satterthwaite df keeps two."""
    if value is None:
        return "—"
    number = float(value)
    if not math.isfinite(number):
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.2f}"


#: Per-statistic decimal precision. APA allows two or three decimals as
#: appropriate; coefficients bounded by 1 get three, because at two decimals a
#: correlation of .9978 would print as "1.00" and read as a perfect
#: relationship that the data does not show.
DEFAULT_DECIMALS = {
    "r": 3, "rho": 3, "r_squared": 3, "adjusted_r_squared": 3,
    "eta_squared": 3, "partial_eta_squared": 3, "epsilon_squared": 3,
    "cramers_v": 3, "rank_biserial_r": 3, "alpha": 3, "beta": 3, "R": 3,
}


def fmt_statistic(name: str, value: Optional[float], decimals: Optional[int] = None) -> str:
    """Format by statistic name, applying the leading-zero and precision rules."""
    if decimals is None:
        decimals = DEFAULT_DECIMALS.get(name, 2)
    return fmt(value, decimals, bounded=name in BOUNDED_STATISTICS)


def significance_stars(p_value: Optional[float]) -> str:
    """The *, **, *** markers explained in every APA table note."""
    if p_value is None:
        return ""
    try:
        number = float(p_value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    if number < 0.001:
        return "***"
    if number < 0.01:
        return "**"
    if number < 0.05:
        return "*"
    return ""


def to_turkish_decimal(text: str) -> str:
    """Swap the decimal point for a comma, the Turkish thesis convention."""
    return text.replace(".", ",")
