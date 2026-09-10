"""Post-generation numeric-token validation (§3.6).

The hard constraint of this product: the LLM phrases a sentence around numbers
the statistics engine computed, and may not introduce a number of its own.
This module enforces that mechanically.

    Every numeric token in the LLM's output must exactly match a value from the
    input JSON. If mismatch -> reject and re-render from template without the
    LLM, log the failure for review.

Approach: extract every numeric token from the generated text, then check each
against a whitelist built from the payload. The whitelist holds *rendered
forms*, not floats, because "t = 7.20" and "t = 7.197" are both faithful
renderings of the same computed value and both must pass, while "t = 7.42"
must not.

Being wrong in the permissive direction is the dangerous one here, so the
whitelist is built only from values actually present in the payload plus a
small set of reporting conventions (alpha, the .001/.01/.05 thresholds, effect
size band cut-offs) that a template legitimately mentions.

Known limitation, inherent to the check §3.6 specifies: this is a *membership*
test, not a *binding* test. If the model writes "M = 84.50" where 84.50 is the
group's median rather than its mean, every token still traces to a computed
value and the text passes. The check catches fabricated numbers, which is the
hallucination risk it is aimed at; it does not catch a correct number attached
to the wrong label.

TODO(spec-gap): §3.6 specifies only the numeric-token match. Binding each
number to the statistic it is labelled with would need a label-aware grammar
per template, which the requirements doc does not define. The mitigation in
place is that the deterministic template (which cannot mislabel) is what ships
whenever validation fails, and the LLM is given the exact sentence shape to
fill.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

#: A numeric token: an optional sign, then digits with an optional decimal
#: part, or a bare decimal fraction (".05", ",05"). Percent signs and the
#: surrounding text are not part of the token.
NUMERIC_TOKEN = re.compile(r"-?(?:\d+(?:[.,]\d+)?|[.,]\d+)")

#: Decimal precisions a faithful rendering may use.
_PRECISIONS = (0, 1, 2, 3, 4)

#: Conventions a template may state without them appearing in the payload:
#: the significance thresholds of the APA note row and the alpha level.
_REPORTING_CONSTANTS = (0.05, 0.01, 0.001)


@dataclass
class ValidationResult:
    valid: bool
    offending_tokens: list[str] = field(default_factory=list)
    checked_tokens: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "offending_tokens": self.offending_tokens,
            "checked_tokens": self.checked_tokens,
            "reason": self.reason,
        }


def _renderings(value: float) -> set[str]:
    """Every string form in which `value` may legitimately appear in prose."""
    forms: set[str] = set()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return forms
    if not math.isfinite(number):
        return forms

    for precision in _PRECISIONS:
        text = f"{number:.{precision}f}"
        # Guard against "-0.00" style artefacts of rounding a tiny negative.
        if text.startswith("-") and float(text) == 0.0:
            text = text[1:]
        forms.add(text)
        # APA drops the leading zero on statistics bounded by 1 (§6.36).
        if text.startswith("0."):
            forms.add(text[1:])
        elif text.startswith("-0."):
            forms.add("-" + text[2:])

    # A whole number may be written without a decimal part ("18", not "18.00").
    if abs(number - round(number)) < 1e-9:
        forms.add(str(int(round(number))))

    # Percentages: R^2 = .432 may be phrased as "%43.2".
    percent = number * 100
    if 0 <= percent <= 100:
        for precision in (0, 1, 2):
            forms.add(f"{percent:.{precision}f}")

    # Turkish decimal comma.
    forms |= {form.replace(".", ",") for form in list(forms) if "." in form}
    return forms


def _walk(value: Any) -> Iterable[float]:
    """Yield every numeric leaf of the payload."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)
    elif isinstance(value, str):
        # Group labels and variable names may legitimately contain digits
        # ("8. sınıf", "Grup 2"), and a sentence naming the group has to be
        # able to repeat them.
        for match in NUMERIC_TOKEN.finditer(value):
            try:
                yield float(match.group().replace(",", "."))
            except ValueError:  # pragma: no cover — regex guarantees parseability
                continue


def build_whitelist(payload: dict[str, Any]) -> set[str]:
    """All numeric strings the interpretation is allowed to contain."""
    whitelist: set[str] = set()
    for number in _walk(payload):
        whitelist |= _renderings(number)
    for constant in _REPORTING_CONSTANTS:
        whitelist |= _renderings(constant)
    return whitelist


def normalise(token: str) -> str:
    """Canonicalise a token for comparison: strip a trailing separator."""
    return token.rstrip(".,")


def validate_numeric_tokens(text: str, payload: dict[str, Any]) -> ValidationResult:
    """§3.6's check. Returns a rejection listing the tokens that failed."""
    whitelist = build_whitelist(payload)
    checked: list[str] = []
    offending: list[str] = []

    for match in NUMERIC_TOKEN.finditer(text):
        token = normalise(match.group())
        if not token or token in {"-", ""}:
            continue
        checked.append(token)
        if token in whitelist:
            continue
        # A token written with the other decimal separator is still the same
        # number; compare both ways before rejecting.
        swapped = token.replace(",", ".") if "," in token else token.replace(".", ",")
        if swapped in whitelist:
            continue
        offending.append(token)

    if offending:
        return ValidationResult(
            valid=False,
            offending_tokens=offending,
            checked_tokens=checked,
            reason=(
                "Üretilen metinde hesaplama sonuçlarıyla eşleşmeyen sayısal "
                f"değer(ler) bulundu: {', '.join(offending)}"
            ),
        )
    return ValidationResult(valid=True, checked_tokens=checked)
