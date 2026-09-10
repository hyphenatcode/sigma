"""§3.6 tests — the hallucination-safety layer.

The centrepiece is `test_corrupted_llm_output_is_rejected`: the brief requires
that the validator be fed intentionally corrupted LLM output and be shown to
reject it. Every corruption below is one a language model plausibly produces.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from app.interpretation.llm import LLMResponse
from app.interpretation.payload import build_payload
from app.interpretation.service import interpret
from app.interpretation.templates import render_from_template
from app.interpretation.validator import (
    build_whitelist,
    validate_numeric_tokens,
)
from app.stats.enums import MeasurementLevel as ML
from app.stats.enums import ResearchTask as RT
from app.stats.pipeline import AnalysisRequest, run_analysis

RATIO, NOMINAL = ML.RATIO, ML.NOMINAL


@pytest.fixture
def t_test_result(reference):
    frame = reference("ttest_independent.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
    ))
    return outcome.result


@pytest.fixture
def t_test_payload(t_test_result):
    return build_payload(t_test_result)


#: What a well-behaved model returns for that analysis.
FAITHFUL = (
    "Deney (M = 84.00, SS = 5.01) ile Kontrol (M = 70.30, SS = 3.33) grupları "
    "arasında istatistiksel olarak anlamlı bir fark bulunmuştur, "
    "t(18) = 7.20, p < .001. Etki büyüklüğü büyük düzeydedir (Cohen's d = 3.22)."
)


# ---------------------------------------------------------------------------
# The payload boundary: computed values only (§3.6, §5 KVKK)
# ---------------------------------------------------------------------------

def test_payload_carries_only_computed_values(t_test_payload):
    assert set(t_test_payload) >= {
        "analysis_type", "test_name_tr", "statistics", "df", "p_value",
        "effect_size", "group_descriptives",
    }
    assert t_test_payload["effect_size"]["band"] == "large"
    assert [g["label"] for g in t_test_payload["group_descriptives"]] == ["Deney", "Kontrol"]


def test_payload_never_contains_raw_observations(reference, t_test_payload):
    """No individual respondent's score may appear in what we send to the API."""
    frame = reference("ttest_independent.csv")
    serialised = str(t_test_payload)

    # A student id is a value that exists only at the row level.
    for student_id in frame.ogrenci_id:
        assert f"'ogrenci_id': {student_id}" not in serialised
    assert "ogrenci_id" not in serialised
    # The payload has aggregates, not the 20 individual scores.
    assert "basari_puani" not in serialised


# ---------------------------------------------------------------------------
# Faithful output passes
# ---------------------------------------------------------------------------

def test_faithful_output_passes_validation(t_test_payload):
    result = validate_numeric_tokens(FAITHFUL, t_test_payload)
    assert result.valid
    assert result.offending_tokens == []
    assert result.checked_tokens


def test_alternative_roundings_of_the_same_value_pass(t_test_payload):
    """'t = 7.197' and 't = 7.20' are the same computed number."""
    for rendering in ["7.2", "7.20", "7.197", "7.1972"]:
        text = f"Fark anlamlıdır, t(18) = {rendering}, p < .001."
        assert validate_numeric_tokens(text, t_test_payload).valid, rendering


def test_turkish_decimal_comma_passes(t_test_payload):
    text = "Fark anlamlıdır, t(18) = 7,20, p < .001, d = 3,22."
    assert validate_numeric_tokens(text, t_test_payload).valid


def test_leading_zero_variants_pass(t_test_payload):
    """APA drops the leading zero on bounded statistics; both forms are the
    same number and both must pass."""
    for rendering in ["0.883", ".883"]:
        text = f"Normallik varsayımı karşılanmıştır (p = {rendering})."
        assert validate_numeric_tokens(text, t_test_payload).valid, rendering


# ---------------------------------------------------------------------------
# Corrupted output is rejected — the requirement from the build brief
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description,corrupted", [
    (
        "test statistic altered",
        FAITHFUL.replace("t(18) = 7.20", "t(18) = 7.42"),
    ),
    (
        "degrees of freedom altered",
        FAITHFUL.replace("t(18)", "t(19)"),
    ),
    (
        "effect size altered",
        FAITHFUL.replace("Cohen's d = 3.22", "Cohen's d = 0.82"),
    ),
    (
        # 84.50 would be a bad probe: it is the Deney group's median, so it is
        # genuinely a payload value. Use a number that is in the payload
        # nowhere at all.
        "group mean altered",
        FAITHFUL.replace("M = 84.00", "M = 84.73"),
    ),
    (
        "standard deviation altered",
        FAITHFUL.replace("SS = 5.01", "SS = 5.11"),
    ),
    (
        "invented confidence interval",
        FAITHFUL + " %95 güven aralığı [9.68, 17.72] olarak hesaplanmıştır.",
    ),
    (
        "invented citation year",
        FAITHFUL + " Bu bulgu Yılmaz (2019) ile tutarlıdır.",
    ),
    (
        "invented sample size",
        FAITHFUL + " Araştırmaya 250 öğrenci katılmıştır.",
    ),
    (
        "p value fabricated as a specific number",
        FAITHFUL.replace("p < .001", "p = .0004"),
    ),
    (
        "invented percentage",
        FAITHFUL + " Deney grubu %37 daha başarılıdır.",
    ),
    (
        "hallucinated post-hoc statistic",
        FAITHFUL + " Tukey testi sonucunda fark anlamlıdır (q = 4.51).",
    ),
])
def test_corrupted_llm_output_is_rejected(description, corrupted, t_test_payload):
    result = validate_numeric_tokens(corrupted, t_test_payload)
    assert not result.valid, f"validator failed to catch: {description}"
    assert result.offending_tokens, description
    assert result.reason


def test_rejection_names_the_offending_token(t_test_payload):
    corrupted = FAITHFUL.replace("7.20", "9.99")
    result = validate_numeric_tokens(corrupted, t_test_payload)
    assert "9.99" in result.offending_tokens
    assert "9.99" in result.reason


def test_whitelist_does_not_admit_arbitrary_numbers(t_test_payload):
    whitelist = build_whitelist(t_test_payload)
    for invented in ["7.42", "2019", "250", "0.82", "37"]:
        assert invented not in whitelist


def test_group_labels_containing_digits_are_allowed():
    """A group literally called '8. sınıf' must be repeatable in the sentence."""
    payload = {
        "analysis_type": "independent_t_test",
        "statistics": {"t": 2.5},
        "df": {"df": 30},
        "p_value": 0.018,
        "group_descriptives": [
            {"label": "8. sınıf", "n": 16, "mean": 70.0},
            {"label": "12. sınıf", "n": 16, "mean": 75.0},
        ],
    }
    text = "8. sınıf ve 12. sınıf grupları arasında fark vardır, t(30) = 2.50, p = .018."
    assert validate_numeric_tokens(text, payload).valid


# ---------------------------------------------------------------------------
# Every deterministic template passes its own validator (§3.6 fallback path)
# ---------------------------------------------------------------------------

ALL_ANALYSES = [
    ("ttest_independent.csv", dict(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL})),
    ("ttest_paired.csv", dict(
        task=RT.COMPARISON, is_paired=True,
        paired_measurements=["on_test", "son_test"],
        measurement_levels={"on_test": RATIO, "son_test": RATIO})),
    ("anova_three_groups.csv", dict(
        task=RT.COMPARISON, dependent_variable="kaygi_puani",
        independent_variables=["sinif_duzeyi"],
        measurement_levels={"kaygi_puani": RATIO, "sinif_duzeyi": NOMINAL})),
    ("anova_unequal_variance.csv", dict(
        task=RT.COMPARISON, dependent_variable="memnuniyet",
        independent_variables=["bolum"],
        measurement_levels={"memnuniyet": RATIO, "bolum": NOMINAL})),
    ("nonparametric_skewed.csv", dict(
        task=RT.COMPARISON, dependent_variable="tepki_suresi",
        independent_variables=["grup"],
        measurement_levels={"tepki_suresi": RATIO, "grup": NOMINAL})),
    ("correlation_regression.csv", dict(
        task=RT.RELATIONSHIP, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO})),
    ("correlation_regression.csv", dict(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO})),
    ("multiple_regression.csv", dict(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati", "uyku_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO,
                            "uyku_saati": RATIO})),
    ("chi_square.csv", dict(
        task=RT.COMPARISON, dependent_variable="tercih",
        independent_variables=["cinsiyet"],
        measurement_levels={"tercih": NOMINAL, "cinsiyet": NOMINAL})),
    ("reliability_scale.csv", dict(
        task=RT.SCALE_RELIABILITY,
        scale_items=[f"madde{i}" for i in range(1, 6)],
        measurement_levels={f"madde{i}": ML.ORDINAL for i in range(1, 6)})),
]


@pytest.mark.parametrize("filename,config", ALL_ANALYSES)
def test_template_output_passes_its_own_validator(filename, config, reference):
    """The fallback must never be rejected by the rule it exists to satisfy."""
    outcome = run_analysis(reference(filename), AnalysisRequest(**config))
    payload = build_payload(outcome.result)
    text = render_from_template(payload)

    validation = validate_numeric_tokens(text, payload)
    assert validation.valid, (
        f"{outcome.executed_analysis_type}: {validation.offending_tokens}"
    )
    assert text.endswith(".")
    assert len(text) > 60


@pytest.mark.parametrize("filename,config", ALL_ANALYSES)
def test_every_analysis_has_a_turkish_interpretation(filename, config, reference):
    outcome = run_analysis(reference(filename), AnalysisRequest(**config))
    interpretation = interpret(outcome.result, use_llm=False)
    assert interpretation.source == "template"
    assert interpretation.text_tr


# ---------------------------------------------------------------------------
# Service orchestration: generate -> validate -> fall back
# ---------------------------------------------------------------------------

def test_service_accepts_valid_llm_output(t_test_result):
    with patch("app.interpretation.service.generate_interpretation",
               return_value=LLMResponse(text=FAITHFUL, model="test", used_llm=True)):
        interpretation = interpret(t_test_result)

    assert interpretation.source == "llm"
    assert interpretation.text_tr == FAITHFUL
    assert interpretation.validation.valid


def test_service_falls_back_to_template_on_invalid_llm_output(t_test_result):
    """§3.6: reject, re-render from template, log the failure for review."""
    corrupted = FAITHFUL.replace("7.20", "7.42")
    with patch("app.interpretation.service.generate_interpretation",
               return_value=LLMResponse(text=corrupted, model="test", used_llm=True)):
        interpretation = interpret(t_test_result)

    assert interpretation.source == "template_after_rejection"
    assert "7.42" not in interpretation.text_tr
    assert "7.20" in interpretation.text_tr
    assert interpretation.validation.valid is False
    # the rejected text is retained for review, but never surfaced as the result
    assert interpretation.rejected_text == corrupted
    assert interpretation.to_dict()["text_tr"] != corrupted


def test_service_falls_back_when_the_api_is_unavailable(t_test_result):
    with patch("app.interpretation.service.generate_interpretation",
               return_value=LLMResponse(text="", model="", used_llm=False,
                                        error="no api key")):
        interpretation = interpret(t_test_result)

    assert interpretation.source == "template"
    assert interpretation.llm_error == "no api key"
    assert interpretation.text_tr


def test_service_logs_rejections_for_review(t_test_result, caplog):
    corrupted = FAITHFUL + " Ayrıca 2021 yılında benzer bulgular elde edilmiştir."
    with patch("app.interpretation.service.generate_interpretation",
               return_value=LLMResponse(text=corrupted, model="test", used_llm=True)):
        with caplog.at_level("WARNING"):
            interpret(t_test_result)

    assert any("rejected" in record.message for record in caplog.records)


def test_llm_is_never_required_for_a_result_to_be_reportable(t_test_result):
    """The deterministic path must stand alone — the LLM is a phrasing nicety."""
    interpretation = interpret(t_test_result, use_llm=False)
    assert interpretation.text_tr
    assert interpretation.source == "template"
    assert "t(18) = 7.20" in interpretation.text_tr


def test_validator_is_a_membership_check_not_a_binding_check(t_test_payload):
    """Documents a known, deliberate limit of the §3.6 rule.

    84.50 is the Deney group's median. A model that writes it as the *mean*
    produces text where every token still traces to a computed value, so the
    membership check passes. This is what §3.6 specifies; catching it would
    need a label-aware check the requirements doc does not define. Pinned here
    so the behaviour is a known property rather than a surprise.
    """
    mislabelled = FAITHFUL.replace("M = 84.00", "M = 84.50")
    assert validate_numeric_tokens(mislabelled, t_test_payload).valid
    # ...but 84.50 really is in the payload, as the median:
    assert any(g.get("median") == 84.5 for g in t_test_payload["group_descriptives"])


def test_assumption_p_values_are_available_to_the_narrative(t_test_payload):
    """A sentence may cite the assumption test it reports (§3.4 + §3.6)."""
    normality = [a for a in t_test_payload["assumptions"] if a["assumption"] == "normality"]
    assert normality
    assert all(a["p_value"] is not None for a in normality)

    text = "Normallik varsayımı karşılanmıştır (Shapiro-Wilk, p = .883)."
    assert validate_numeric_tokens(text, t_test_payload).valid
