"""Core vocabulary of the statistics engine.

Everything in this module is deterministic and free of I/O. The values here are
the contract between the API layer, the recommendation engine (§3.3) and the
test procedures (§3.4-§3.7).
"""

from __future__ import annotations

from enum import Enum


class MeasurementLevel(str, Enum):
    """Stevens' levels of measurement, as confirmed by the user in §3.2."""

    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    INTERVAL = "interval"
    RATIO = "ratio"

    @property
    def is_continuous(self) -> bool:
        """§3.3 treats interval and ratio as 'continuous'."""
        return self in (MeasurementLevel.INTERVAL, MeasurementLevel.RATIO)

    @property
    def is_categorical(self) -> bool:
        """§3.3 treats nominal and ordinal as 'categorical'.

        Note that ordinal counts as categorical when it plays the *independent*
        role (it defines groups) and is deliberately NOT accepted as a
        continuous dependent variable — the parametric tests in §3.3 assume an
        interval/ratio DV.
        """
        return self in (MeasurementLevel.NOMINAL, MeasurementLevel.ORDINAL)


class VariableRole(str, Enum):
    """§3.2 variable roles. COVARIATE is v2 but is accepted as a stored role."""

    DEPENDENT = "dependent"
    INDEPENDENT = "independent"
    GROUPING = "grouping"
    COVARIATE = "covariate"  # v2 — accepted in the data model, not used by v1 analyses
    SCALE_ITEM = "scale_item"


class DetectedType(str, Enum):
    """§3.1 column data types inferred at upload time."""

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATE = "date"  # informational only in v1, never used to pick a test


class ResearchTask(str, Enum):
    """What the user is trying to do.

    §3.3's pseudocode branches on a `task` for the reliability and factor
    structure paths. We make the same switch explicit for the continuous-IV
    branch, where the pseudocode is ambiguous between correlation and simple
    linear regression (see recommendation.py).
    """

    COMPARISON = "comparison"          # group differences
    RELATIONSHIP = "relationship"      # association between continuous variables
    PREDICTION = "prediction"          # regression
    SCALE_RELIABILITY = "scale_reliability"
    FACTOR_STRUCTURE = "factor_structure"


class AssumptionStatus(str, Enum):
    MET = "met"
    VIOLATED = "violated"
    NOT_APPLICABLE = "not_applicable"
    NOT_RUN = "not_run"


class EffectSizeBand(str, Enum):
    """§3.5 interpretation bands."""

    NEGLIGIBLE = "negligible"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    NOT_BANDED = "not_banded"  # e.g. R², reported but not banded per §3.5
