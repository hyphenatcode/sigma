"""§3.7 APA table generation tests."""

import pytest

from app.apa.formatting import fmt, fmt_df, fmt_p, fmt_statistic, significance_stars
from app.apa.tables import APATable, build_tables
from app.stats.enums import MeasurementLevel as ML
from app.stats.enums import ResearchTask as RT
from app.stats.pipeline import AnalysisRequest, run_analysis
from tests.test_interpretation import ALL_ANALYSES

RATIO, NOMINAL = ML.RATIO, ML.NOMINAL


# ---------------------------------------------------------------------------
# APA number formatting (APA 7th ed.)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (0.0004, "< .001"), (0.001, ".001"), (0.009823, ".010"),
    (0.05, ".050"), (0.5, ".500"), (None, "—"),
])
def test_p_value_formatting(value, expected):
    assert fmt_p(value) == expected


def test_bounded_statistics_drop_the_leading_zero():
    """APA 7th ed. §6.36: statistics that cannot exceed 1 omit the leading 0."""
    assert fmt_statistic("r", 0.427) == ".427"
    assert fmt_statistic("cramers_v", 0.333333) == ".333"
    assert fmt_statistic("rank_biserial_r", -0.68) == "-.680"
    # t and F can exceed 1 and keep theirs
    assert fmt(7.197247) == "7.20"


def test_correlations_use_three_decimals():
    """At two decimals, r = .9978 would print as '1.00' and read as perfect."""
    assert fmt_statistic("r", 0.997798) == ".998"


def test_df_formatting_keeps_welch_decimals():
    assert fmt_df(18.0) == "18"
    assert fmt_df(15.665031) == "15.67"


@pytest.mark.parametrize("p_value,stars", [
    (0.0001, "***"), (0.005, "**"), (0.03, "*"), (0.20, ""), (None, ""),
])
def test_significance_stars(p_value, stars):
    assert significance_stars(p_value) == stars


# ---------------------------------------------------------------------------
# Table structure
# ---------------------------------------------------------------------------

def test_t_test_table_shape(reference):
    frame = reference("ttest_independent.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
    ))
    table = build_tables(outcome.result)[0]

    assert table.label == "Tablo 1"
    assert table.title == "Bağımsız Örneklem t-Testi Sonuçları"
    assert table.columns == ["Grup", "n", "M", "SS", "t", "sd", "p", "Cohen's d"]
    assert table.rows[0] == ["Deney", "10", "84.00", "5.01", "7.20", "18", "< .001", "3.22"]
    assert table.rows[1][:4] == ["Kontrol", "10", "70.30", "3.33"]
    # §3.7 requires a note row explaining significance markers and effect size
    assert "* p < .05" in table.note
    assert "Cohen's d" in table.note
    assert "büyük etki" in table.note


def test_anova_source_table_shape(reference):
    frame = reference("anova_three_groups.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="kaygi_puani",
        independent_variables=["sinif_duzeyi"],
        measurement_levels={"kaygi_puani": RATIO, "sinif_duzeyi": NOMINAL},
    ))
    tables = build_tables(outcome.result)
    source = tables[0]

    assert source.columns == ["Varyansın kaynağı", "KT", "sd", "KO", "F", "p", "η²"]
    assert [row[0] for row in source.rows] == ["Gruplar arası", "Gruplar içi", "Toplam"]
    assert source.rows[0][1] == "768.00"
    assert source.rows[1][1] == "80.50"
    assert source.rows[0][4] == "71.55"
    assert source.rows[0][6] == ".905"
    # ANOVA gets a companion descriptives table
    assert tables[1].title == "Gruplara Göre Betimsel İstatistikler"
    assert len(tables[1].rows) == 3


def test_chi_square_table_is_the_contingency_table(reference):
    frame = reference("chi_square.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="tercih",
        independent_variables=["cinsiyet"],
        measurement_levels={"tercih": NOMINAL, "cinsiyet": NOMINAL},
    ))
    table = build_tables(outcome.result)[0]

    assert table.rows[-1][0] == "Toplam"
    assert table.rows[-1][-1] == "60"
    assert "χ²(1, N = 60) = 6.67" in table.note
    assert "Cramér's V" in table.note


def test_regression_table_reports_model_fit_in_the_note(reference):
    frame = reference("multiple_regression.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati", "uyku_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO,
                            "uyku_saati": RATIO},
    ))
    table = build_tables(outcome.result)[0]

    assert table.columns == ["Yordayıcı", "B", "SH", "β", "t", "p"]
    assert table.rows[0][0] == "Sabit"
    assert [row[0] for row in table.rows[1:]] == ["calisma_saati", "uyku_saati"]
    assert "R² = .997" in table.note
    assert "F(2, 12) = 1907.81" in table.note


def test_reliability_table_lists_alpha_if_deleted(reference):
    frame = reference("reliability_scale.csv")
    items = [f"madde{i}" for i in range(1, 6)]
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.SCALE_RELIABILITY, scale_items=items,
        measurement_levels={item: ML.ORDINAL for item in items},
    ))
    table = build_tables(outcome.result)[0]

    assert "Madde silindiğinde α" in table.columns
    assert len(table.rows) == 5
    assert "Cronbach α = .963" in table.note


# ---------------------------------------------------------------------------
# §3.4: the assumption table is always produced
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,config", ALL_ANALYSES)
def test_every_analysis_gets_an_assumption_table(filename, config, reference):
    outcome = run_analysis(reference(filename), AnalysisRequest(**config))
    tables = build_tables(outcome.result)
    titles = [t.title for t in tables]
    assert "Varsayım Kontrolleri" in titles


@pytest.mark.parametrize("filename,config", ALL_ANALYSES)
def test_every_analysis_produces_renderable_tables(filename, config, reference):
    outcome = run_analysis(reference(filename), AnalysisRequest(**config))
    tables = build_tables(outcome.result)

    assert tables
    for index, table in enumerate(tables, start=1):
        assert table.number == index
        assert table.columns
        assert table.rows
        assert all(len(row) == len(table.columns) for row in table.rows), table.title
        markup = table.to_html()
        assert "<table>" in markup and "</table>" in markup
        assert f"Tablo {index}" in markup


def test_table_numbering_can_start_anywhere(reference):
    frame = reference("ttest_independent.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
    ))
    tables = build_tables(outcome.result, start_number=4)
    assert [t.label for t in tables] == ["Tablo 4", "Tablo 5"]


def test_html_escapes_user_supplied_labels():
    """Column names come from an uploaded file and must not inject markup."""
    table = APATable(
        number=1, title="Test", columns=["Grup", "n"],
        rows=[["<script>alert(1)</script>", "10"]],
    )
    markup = table.to_html()
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


def test_substitution_note_appears_in_the_table(reference):
    """When §3.4 changed the test, the table says so too."""
    frame = reference("nonparametric_skewed.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="tepki_suresi",
        independent_variables=["grup"],
        measurement_levels={"tepki_suresi": RATIO, "grup": NOMINAL},
    ))
    table = build_tables(outcome.result)[0]
    assert "Mann-Whitney" in table.note
    assert "Normallik varsayımı" in table.note


def test_assumption_note_does_not_describe_tests_that_never_ran(reference):
    """Cronbach's alpha has no §3.4 assumption test; the section still appears
    but must not claim normality tests informed the choice."""
    frame = reference("reliability_scale.csv")
    items = [f"madde{i}" for i in range(1, 6)]
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.SCALE_RELIABILITY, scale_items=items,
        measurement_levels={item: ML.ORDINAL for item in items},
    ))
    table = [t for t in build_tables(outcome.result)
             if t.title == "Varsayım Kontrolleri"][0]
    assert "Normallik" not in table.note
    assert "uygulanabilir bir varsayım testi bulunmamaktadır" in table.note


def test_assumption_note_describes_the_tests_when_they_did_run(reference):
    frame = reference("ttest_independent.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL},
    ))
    table = [t for t in build_tables(outcome.result)
             if t.title == "Varsayım Kontrolleri"][0]
    assert "Normallik" in table.note


def test_welch_anova_is_not_reported_as_a_source_table(reference):
    """Welch's test adjusts denominator df rather than partitioning sums of
    squares, so an SS/MS source table beside Welch's F and df does not
    reconcile: a reader recomputing F from the mean squares gets a different
    number from the one reported."""
    frame = reference("anova_unequal_variance.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="memnuniyet",
        independent_variables=["bolum"],
        measurement_levels={"memnuniyet": RATIO, "bolum": NOMINAL},
    ))
    assert outcome.executed_analysis_type == "welch_anova"
    table = build_tables(outcome.result)[0]

    assert table.title == "Welch ANOVA Sonuçları"
    assert table.columns == ["Karşılaştırma", "F", "sd1", "sd2", "p", "η²"]
    # no sum-of-squares or mean-square columns
    assert "KT" not in table.columns
    assert "KO" not in table.columns
    assert len(table.rows) == 1
    assert "kareler toplamı ayrıştırması raporlanmaz" in table.note
    # the effect size is still reported, and its provenance explained
    assert table.rows[0][5] == ".167"
    assert "η²" in table.note


def test_pooled_anova_still_gets_its_source_table(reference):
    """The SS decomposition is correct for the pooled one-way ANOVA and must
    stay — only Welch's variant drops it."""
    frame = reference("anova_three_groups.csv")
    outcome = run_analysis(frame, AnalysisRequest(
        task=RT.COMPARISON, dependent_variable="kaygi_puani",
        independent_variables=["sinif_duzeyi"],
        measurement_levels={"kaygi_puani": RATIO, "sinif_duzeyi": NOMINAL},
    ))
    table = build_tables(outcome.result)[0]
    assert table.columns == ["Varyansın kaynağı", "KT", "sd", "KO", "F", "p", "η²"]

    # and the table reconciles: F equals MS_between / MS_within, to within the
    # rounding the cells themselves carry (two decimals).
    ms_between = float(table.rows[0][3])
    ms_within = float(table.rows[1][3])
    assert ms_between / ms_within == pytest.approx(float(table.rows[0][4]), abs=0.1)
