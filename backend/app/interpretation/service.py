"""Interpretation orchestration (§3.6): generate, validate, fall back.

This is the module that makes the product's central safety claim true. The
order of operations is fixed and must not be rearranged:

    1. Build the payload from the engine's result (computed values only).
    2. Render the deterministic template — this is the guaranteed-correct text.
    3. Ask the LLM to phrase it more naturally.
    4. Validate every numeric token in the LLM's text against the payload.
    5. If validation fails, discard the LLM text, keep the template text, and
       log the failure for review.

A user therefore never sees a number the statistics engine did not compute,
whatever the model returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.interpretation.llm import generate_interpretation
from app.interpretation.payload import build_payload
from app.interpretation.templates import render_from_template
from app.interpretation.validator import ValidationResult, validate_numeric_tokens
from app.stats.results import TestResult

logger = logging.getLogger(__name__)


@dataclass
class Interpretation:
    text_tr: str
    source: str            # "llm" | "template" | "template_after_rejection"
    validation: Optional[ValidationResult] = None
    llm_error: Optional[str] = None
    rejected_text: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_tr": self.text_tr,
            "source": self.source,
            "validation": self.validation.to_dict() if self.validation else None,
            "llm_error": self.llm_error,
            # The rejected text is kept for the review log of §3.6, never shown.
            "rejected_text": self.rejected_text,
        }


def interpret(result: TestResult, *, use_llm: bool = True) -> Interpretation:
    """Produce the Turkish interpretation for one analysis result."""
    payload = build_payload(result)
    template_text = render_from_template(payload)

    if not use_llm:
        return Interpretation(text_tr=template_text, source="template", payload=payload)

    response = generate_interpretation(payload)
    if not response.used_llm or not response.text:
        return Interpretation(
            text_tr=template_text,
            source="template",
            llm_error=response.error,
            payload=payload,
        )

    validation = validate_numeric_tokens(response.text, payload)
    if not validation.valid:
        # §3.6: reject, re-render from template, log the failure for review.
        logger.warning(
            "LLM interpretation rejected for %s: offending tokens %s",
            result.analysis_type, validation.offending_tokens,
        )
        return Interpretation(
            text_tr=template_text,
            source="template_after_rejection",
            validation=validation,
            rejected_text=response.text,
            payload=payload,
        )

    return Interpretation(
        text_tr=response.text,
        source="llm",
        validation=validation,
        payload=payload,
    )
