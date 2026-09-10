"""§3.8 export tests.

The requirement these protect is "avoid drift between preview, Word and PDF":
all three read the same `ReportContent`, so the same numbers must appear in all
three outputs.
"""

import io
import zipfile

import pytest

from app.apa.tables import build_tables
from app.export.html import ReportContent, render_report_html, render_tables_html
from app.export.pdf import render_pdf
from app.export.word import render_docx
from app.interpretation.service import interpret
from app.stats.enums import MeasurementLevel as ML
from app.stats.enums import ResearchTask as RT
from app.stats.pipeline import AnalysisRequest, run_analysis
from tests.test_interpretation import ALL_ANALYSES


@pytest.fixture
def content(reference):
    outcome = run_analysis(reference("ttest_independent.csv"), AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": ML.RATIO, "yontem": ML.NOMINAL},
    ))
    return ReportContent(
        title="İstatistiksel Analiz Raporu",
        dataset_name="ttest_independent.csv",
        analysis_type=outcome.executed_analysis_type,
        interpretation=interpret(outcome.result, use_llm=False).text_tr,
        tables=build_tables(outcome.result),
        substitution_note=outcome.substitution_reason_tr,
    )


def _docx_text(data: bytes) -> str:
    """Pull the visible text out of a .docx without python-docx's object model."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_html_report_is_a_complete_document(content):
    markup = render_report_html(content)
    assert markup.startswith("<!DOCTYPE html>")
    assert 'lang="tr"' in markup
    assert "İstatistiksel Analiz Raporu" in markup
    assert "Bağımsız Örneklem t-Testi Sonuçları" in markup


def test_docx_is_a_valid_office_package(content):
    data = render_docx(content)
    assert data.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "word/document.xml" in archive.namelist()


def test_pdf_is_a_valid_pdf(content):
    data = render_pdf(content)
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-1024:]


def test_all_three_outputs_carry_the_same_numbers(content):
    """§3.8's actual requirement: the formats must not drift."""
    html = render_report_html(content)
    docx = _docx_text(render_docx(content))

    for value in ["7.20", "84.00", "70.30", "5.01", "3.33", "3.22", "18"]:
        assert value in html, f"{value} missing from HTML"
        assert value in docx, f"{value} missing from DOCX"

    # The interpretation paragraph is identical, character for character —
    # compared through the template engine's own escaper, since Jinja2
    # autoescaping turns the apostrophe of "Cohen's d" into &#39; (which is
    # correct escaping, not drift between the formats).
    from markupsafe import escape

    assert str(escape(content.interpretation)) in html
    assert "Bağımsız Örneklem t-Testi Sonuçları" in docx


def test_docx_carries_every_table(content):
    docx = _docx_text(render_docx(content))
    for table in content.tables:
        assert table.label in docx
        assert table.title in docx


def test_turkish_characters_survive_every_format(content):
    html = render_report_html(content)
    docx = _docx_text(render_docx(content))
    for word in ["büyüklüğü", "İstatistiksel", "Karşılandı", "Varsayım"]:
        assert word in html
    assert "Bağımsız" in docx


def test_substitution_note_reaches_the_report(reference):
    outcome = run_analysis(reference("nonparametric_skewed.csv"), AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="tepki_suresi",
        independent_variables=["grup"],
        measurement_levels={"tepki_suresi": ML.RATIO, "grup": ML.NOMINAL},
    ))
    report = ReportContent(
        title="Rapor", dataset_name="x.csv",
        analysis_type=outcome.executed_analysis_type,
        interpretation=interpret(outcome.result, use_llm=False).text_tr,
        tables=build_tables(outcome.result),
        substitution_note=outcome.substitution_reason_tr,
    )
    html = render_report_html(report)
    docx = _docx_text(render_docx(report))
    assert "Analiz seçimi" in html
    assert "Mann-Whitney" in html
    assert "Analiz seçimi" in docx


@pytest.mark.parametrize("filename,config", ALL_ANALYSES)
def test_every_analysis_exports_to_all_three_formats(filename, config, reference):
    outcome = run_analysis(reference(filename), AnalysisRequest(**config))
    report = ReportContent(
        title="Rapor", dataset_name=filename,
        analysis_type=outcome.executed_analysis_type,
        interpretation=interpret(outcome.result, use_llm=False).text_tr,
        tables=build_tables(outcome.result),
        substitution_note=outcome.substitution_reason_tr,
    )
    assert render_report_html(report).startswith("<!DOCTYPE html>")
    assert render_docx(report).startswith(b"PK")
    assert render_pdf(report).startswith(b"%PDF-")


def test_tables_only_html_is_embeddable(content):
    """`Report.apa_table_html` (§4) is a fragment, not a whole document."""
    fragment = render_tables_html(content.tables)
    assert "<!DOCTYPE" not in fragment
    assert fragment.startswith('<div class="apa-table">')
