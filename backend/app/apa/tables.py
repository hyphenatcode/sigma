"""APA 7th-edition table generation (§3.7).

Deterministic Python, one generator per test family. The LLM is never involved
in building a table — it only ever phrases the sentence beside it (§3.6).

An `APATable` is a structural description (title, headers, rows, note), not a
rendering. The HTML preview, the Word table and the PDF all render this same
object, which is how §3.8's "avoid drift between preview, Word and PDF"
requirement is met.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.apa.formatting import fmt, fmt_df, fmt_p, fmt_statistic
from app.stats.enums import AssumptionStatus
from app.stats.registry import TestFamily, get as get_spec
from app.stats.results import TestResult


@dataclass
class APATable:
    """One APA-formatted table.

    `number` is the table's position in the report ("Tablo 1"). `align` marks
    which columns are numeric so renderers can right-align them.
    """

    number: int
    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""
    align: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"Tablo {self.number}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "label": self.label,
            "title": self.title,
            "columns": list(self.columns),
            "rows": [list(r) for r in self.rows],
            "note": self.note,
            "align": self.align or self._default_align(),
        }

    def _default_align(self) -> list[str]:
        return ["left"] + ["right"] * (len(self.columns) - 1)

    def to_html(self) -> str:
        """Render the APA table as HTML.

        This same markup is what the in-app preview shows and what WeasyPrint
        turns into the PDF (§3.8).
        """
        alignment = self.align or self._default_align()
        header = "".join(
            f'<th class="align-{a}" scope="col">{html.escape(c)}</th>'
            for c, a in zip(self.columns, alignment)
        )
        body = "".join(
            "<tr>" + "".join(
                f'<td class="align-{a}">{html.escape(str(cell))}</td>'
                for cell, a in zip(row, alignment)
            ) + "</tr>"
            for row in self.rows
        )
        note = (
            f'<p class="apa-note"><em>Not.</em> {html.escape(self.note)}</p>'
            if self.note else ""
        )
        return (
            f'<div class="apa-table">'
            f'<p class="apa-table-number">{html.escape(self.label)}</p>'
            f'<p class="apa-table-title"><em>{html.escape(self.title)}</em></p>'
            f'<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
            f"{note}</div>"
        )


#: Note text shared by every table that reports a significance test.
_SIG_NOTE = "* p < .05, ** p < .01, *** p < .001."


def _effect_note(result: TestResult) -> str:
    """Explain the effect size and its band, as §3.7 requires of the note row."""
    effect = result.effect_size
    if effect is None:
        return ""
    thresholds = effect.thresholds
    if thresholds:
        small, medium, large = thresholds
        bands = (
            f" Etki büyüklüğü sınırları: {fmt(small, 2, bounded=True)} küçük, "
            f"{fmt(medium, 2, bounded=True)} orta, {fmt(large, 2, bounded=True)} büyük."
        )
    else:
        bands = ""
    return (
        f"{_METRIC_LABELS.get(effect.metric, effect.metric)} = "
        f"{fmt_statistic(effect.metric, effect.value)} ({effect.label_tr} etki).{bands}"
    )


_METRIC_LABELS = {
    "cohens_d": "Cohen's d",
    "eta_squared": "η²",
    "partial_eta_squared": "kısmi η²",
    "epsilon_squared": "ε²",
    "r": "r",
    "rho": "ρ",
    "rank_biserial_r": "sıra-çift serili r",
    "cramers_v": "Cramér's V",
    "r_squared": "R²",
    "alpha": "α",
}


def _substitution_note(result: TestResult) -> str:
    """Surface a §3.4 test swap in the table note as well as in the narrative."""
    return f" {result.substitution_note_tr}" if result.substitution_note_tr else ""


# ---------------------------------------------------------------------------
# t-test family
# ---------------------------------------------------------------------------

def t_test_table(result: TestResult, number: int = 1) -> APATable:
    spec = get_spec(result.analysis_type)
    rows = [
        [d.label, str(d.n), fmt(d.mean), fmt(d.sd), "", "", "", ""]
        for d in result.descriptives
    ]
    if rows:
        rows[0][4] = fmt(result.statistics.get("t"))
        rows[0][5] = fmt_df(result.df.get("df"))
        rows[0][6] = fmt_p(result.p_value)
        rows[0][7] = fmt_statistic("cohens_d", result.effect_size.value) if result.effect_size else "—"

    return APATable(
        number=number,
        title=f"{spec.label_tr} Sonuçları",
        columns=["Grup", "n", "M", "SS", "t", "sd", "p", "Cohen's d"],
        rows=rows,
        note=(
            f"M = ortalama, SS = standart sapma, sd = serbestlik derecesi. "
            f"{_effect_note(result)} {_SIG_NOTE}{_substitution_note(result)}"
        ).strip(),
    )


# ---------------------------------------------------------------------------
# ANOVA family — the conventional source table
# ---------------------------------------------------------------------------

def anova_table(result: TestResult, number: int = 1) -> APATable:
    spec = get_spec(result.analysis_type)
    stats = result.statistics
    df_between = result.df.get("df_between")
    df_within = result.df.get("df_within")

    rows = [
        ["Gruplar arası", fmt(stats.get("ss_between")), fmt_df(df_between),
         fmt(stats.get("ms_between")), fmt(stats.get("F")), fmt_p(result.p_value),
         fmt_statistic("eta_squared", result.effect_size.value) if result.effect_size else "—"],
        ["Gruplar içi", fmt(stats.get("ss_within")), fmt_df(df_within),
         fmt(stats.get("ms_within")), "", "", ""],
        ["Toplam", fmt(stats.get("ss_total")),
         fmt_df((df_between or 0) + (df_within or 0)), "", "", "", ""],
    ]

    table = APATable(
        number=number,
        title=f"{spec.label_tr} Sonuçları",
        columns=["Varyansın kaynağı", "KT", "sd", "KO", "F", "p", "η²"],
        rows=rows,
        note=(
            f"KT = kareler toplamı, KO = kareler ortalaması, "
            f"sd = serbestlik derecesi. {_effect_note(result)} "
            f"{_SIG_NOTE}{_substitution_note(result)}"
        ).strip(),
    )
    return table


def descriptives_table(result: TestResult, number: int = 1) -> APATable:
    """Companion group-descriptives table for ANOVA-family results."""
    return APATable(
        number=number,
        title="Gruplara Göre Betimsel İstatistikler",
        columns=["Grup", "n", "M", "SS"],
        rows=[[d.label, str(d.n), fmt(d.mean), fmt(d.sd)] for d in result.descriptives],
        note="M = ortalama, SS = standart sapma.",
    )


# ---------------------------------------------------------------------------
# Non-parametric family
# ---------------------------------------------------------------------------

def mann_whitney_table(result: TestResult, number: int = 1) -> APATable:
    stats = result.statistics
    rows = []
    for index, d in enumerate(result.descriptives):
        row = [d.label, str(d.n), fmt(d.mean_rank),
               fmt(stats.get(f"rank_sum_{index + 1}")), "", "", "", ""]
        rows.append(row)
    if rows:
        rows[0][4] = fmt(stats.get("U"))
        rows[0][5] = fmt(stats.get("z"))
        rows[0][6] = fmt_p(result.p_value)
        rows[0][7] = fmt_statistic("rank_biserial_r", result.effect_size.value) if result.effect_size else "—"

    return APATable(
        number=number,
        title="Mann-Whitney U Testi Sonuçları",
        columns=["Grup", "n", "Sıra ortalaması", "Sıra toplamı", "U", "z", "p", "r"],
        rows=rows,
        note=(
            f"r = sıra-çift serili korelasyon. {_effect_note(result)} "
            f"{_SIG_NOTE}{_substitution_note(result)}"
        ).strip(),
    )


def wilcoxon_table(result: TestResult, number: int = 1) -> APATable:
    stats = result.statistics
    rows = [[d.label, str(d.n), fmt(d.median), fmt(d.mean), fmt(d.sd), "", "", ""]
            for d in result.descriptives]
    if rows:
        rows[0][5] = fmt(stats.get("W"))
        rows[0][6] = fmt_p(result.p_value)
        rows[0][7] = fmt_statistic("rank_biserial_r", result.effect_size.value) if result.effect_size else "—"

    return APATable(
        number=number,
        title="Wilcoxon İşaretli Sıralar Testi Sonuçları",
        columns=["Ölçüm", "n", "Medyan", "M", "SS", "W", "p", "r"],
        rows=rows,
        note=(
            f"W = Wilcoxon istatistiği, r = sıra-çift serili korelasyon. "
            f"{_effect_note(result)} {_SIG_NOTE}{_substitution_note(result)}"
        ).strip(),
    )


def kruskal_wallis_table(result: TestResult, number: int = 1) -> APATable:
    rows = [[d.label, str(d.n), fmt(d.mean_rank), "", "", "", ""]
            for d in result.descriptives]
    if rows:
        rows[0][3] = fmt(result.statistics.get("H"))
        rows[0][4] = fmt_df(result.df.get("df"))
        rows[0][5] = fmt_p(result.p_value)
        rows[0][6] = fmt_statistic("epsilon_squared", result.effect_size.value) if result.effect_size else "—"

    return APATable(
        number=number,
        title="Kruskal-Wallis H Testi Sonuçları",
        columns=["Grup", "n", "Sıra ortalaması", "H", "sd", "p", "ε²"],
        rows=rows,
        note=(
            f"sd = serbestlik derecesi, ε² = epsilon kare. {_effect_note(result)} "
            f"{_SIG_NOTE}{_substitution_note(result)}"
        ).strip(),
    )


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def correlation_table(result: TestResult, number: int = 1) -> APATable:
    spec = get_spec(result.analysis_type)
    coefficient = "r" if result.analysis_type == "pearson_correlation" else "rho"
    symbol = "r" if coefficient == "r" else "ρ"
    first, second = result.descriptives[0], result.descriptives[1]

    return APATable(
        number=number,
        title=f"{spec.label_tr} Sonuçları",
        columns=["Değişken", "n", "M", "SS", symbol, "sd", "p"],
        rows=[
            [first.label, str(first.n), fmt(first.mean), fmt(first.sd),
             fmt_statistic(coefficient, result.statistics.get(coefficient)),
             fmt_df(result.df.get("df")), fmt_p(result.p_value)],
            [second.label, str(second.n), fmt(second.mean), fmt(second.sd), "", "", ""],
        ],
        note=(
            f"M = ortalama, SS = standart sapma. {_effect_note(result)} "
            f"{_SIG_NOTE}{_substitution_note(result)}"
        ).strip(),
    )


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

def regression_table(result: TestResult, number: int = 1) -> APATable:
    spec = get_spec(result.analysis_type)
    stats = result.statistics
    rows = [["Sabit", fmt(stats.get("intercept")), fmt(stats.get("intercept_se")),
             "", "", ""]]
    for coefficient in result.extra.get("coefficients", []):
        rows.append([
            coefficient["predictor"],
            fmt(coefficient["b"]),
            fmt(coefficient["se"]),
            fmt_statistic("beta", coefficient["beta"]),
            fmt(coefficient["t"]),
            fmt_p(coefficient["p"]),
        ])

    model_line = (
        f"R² = {fmt_statistic('r_squared', stats.get('r_squared'))}, "
        f"düzeltilmiş R² = {fmt_statistic('adjusted_r_squared', stats.get('adjusted_r_squared'))}, "
        f"F({fmt_df(result.df.get('df_model'))}, {fmt_df(result.df.get('df_residual'))}) = "
        f"{fmt(stats.get('F'))}, p {'< .001' if result.p_value < 0.001 else '= ' + fmt_p(result.p_value)}."
    )

    return APATable(
        number=number,
        title=f"{spec.label_tr} Sonuçları",
        columns=["Yordayıcı", "B", "SH", "β", "t", "p"],
        rows=rows,
        note=(
            f"B = standartlaştırılmamış katsayı, SH = standart hata, "
            f"β = standartlaştırılmış katsayı. {model_line} "
            f"Bağımlı değişken: {result.extra.get('dependent_variable', '—')}. "
            f"{_SIG_NOTE}"
        ).strip(),
    )


# ---------------------------------------------------------------------------
# Chi-square — the contingency table itself is the APA table
# ---------------------------------------------------------------------------

def chi_square_table(result: TestResult, number: int = 1) -> APATable:
    observed = result.extra["observed"]
    row_labels = result.extra["row_labels"]
    column_labels = result.extra["column_labels"]
    counts = observed["data"]

    rows = []
    for label, line in zip(row_labels, counts):
        total = sum(line)
        rows.append([label] + [str(int(v)) for v in line] + [str(int(total))])
    column_totals = [sum(line[i] for line in counts) for i in range(len(column_labels))]
    rows.append(["Toplam"] + [str(int(v)) for v in column_totals] + [str(result.n_total)])

    test_line = (
        f"χ²({fmt_df(result.df.get('df'))}, N = {result.n_total}) = "
        f"{fmt(result.statistics.get('chi2'))}, p = {fmt_p(result.p_value)}."
    )
    return APATable(
        number=number,
        title=(
            f"{result.extra['variables'][0]} ve {result.extra['variables'][1]} "
            f"Değişkenlerine İlişkin Çapraz Tablo"
        ),
        columns=[result.extra["variables"][0]] + list(column_labels) + ["Toplam"],
        rows=rows,
        note=f"{test_line} {_effect_note(result)} {_SIG_NOTE}".strip(),
    )


# ---------------------------------------------------------------------------
# Reliability
# ---------------------------------------------------------------------------

def reliability_table(result: TestResult, number: int = 1) -> APATable:
    rows = []
    for item in result.extra.get("item_statistics", []):
        rows.append([
            item["item"],
            fmt(item["mean"]),
            fmt(item["sd"]),
            fmt_statistic("r", item["corrected_item_total_correlation"]),
            fmt_statistic("alpha", item["alpha_if_deleted"]),
        ])

    stats = result.statistics
    summary = (
        f"Ölçeğin geneli için Cronbach α = "
        f"{fmt_statistic('alpha', stats.get('alpha'))} "
        f"({int(stats.get('n_items', 0))} madde, n = {result.n_total})."
    )
    return APATable(
        number=number,
        title="Madde Analizi ve Güvenirlik Sonuçları",
        columns=["Madde", "M", "SS", "Düzeltilmiş madde-toplam korelasyonu",
                 "Madde silindiğinde α"],
        rows=rows,
        note=(
            f"M = ortalama, SS = standart sapma. {summary} "
            f"Güvenirlik düzeyi: {result.effect_size.label_tr}."
        ).strip(),
    )


# ---------------------------------------------------------------------------
# Assumption reporting — §3.4 requires the checks always be shown
# ---------------------------------------------------------------------------

def assumption_table(result: TestResult, number: int = 1) -> Optional[APATable]:
    if not result.assumption_results:
        return None
    rows = []
    for check in result.assumption_results:
        rows.append([
            _ASSUMPTION_LABELS.get(check.assumption, check.assumption),
            check.group or "—",
            check.test_name,
            fmt(check.statistic) if check.statistic is not None else "—",
            fmt_p(check.p_value),
            _STATUS_LABELS.get(check.status.value, check.status.value),
        ])
    # §3.4 still requires the section to appear when no assumption applies
    # (Cronbach's alpha), but the note should not then describe tests that were
    # never run.
    any_test_ran = any(
        check.status is not AssumptionStatus.NOT_APPLICABLE
        for check in result.assumption_results
    )
    note = (
        "Varsayım testlerinde α = .05 kullanılmıştır. Normallik ve varyans "
        "homojenliği testleri, uygulanacak analizin belirlenmesinde kullanılmıştır."
        if any_test_ran else
        "Bu analiz için §3.4 kapsamında uygulanabilir bir varsayım testi "
        "bulunmamaktadır."
    )
    return APATable(
        number=number,
        title="Varsayım Kontrolleri",
        columns=["Varsayım", "Grup/Değişken", "Test", "İstatistik", "p", "Sonuç"],
        rows=rows,
        note=note,
        align=["left", "left", "left", "right", "right", "left"],
    )


_ASSUMPTION_LABELS = {
    "normality": "Normallik",
    "homogeneity_of_variance": "Varyansların homojenliği",
    "multicollinearity": "Çoklu bağlantı",
    "homoscedasticity": "Hata varyanslarının sabitliği",
    "linearity": "Doğrusallık",
    "expected_cell_count": "Beklenen göz frekansı",
    "not_applicable": "Uygulanabilir varsayım yok",
}

_STATUS_LABELS = {
    "met": "Karşılandı",
    "violated": "Karşılanmadı",
    "not_applicable": "Uygulanamaz",
    "not_run": "Uygulanamadı",
}


# ---------------------------------------------------------------------------
# Dispatch — one generator per family (§3.7)
# ---------------------------------------------------------------------------

_GENERATORS: dict[str, Callable[[TestResult, int], APATable]] = {
    "independent_t_test": t_test_table,
    "welch_t_test": t_test_table,
    "paired_t_test": t_test_table,
    "one_way_anova": anova_table,
    "welch_anova": anova_table,
    "mann_whitney_u": mann_whitney_table,
    "wilcoxon_signed_rank": wilcoxon_table,
    "kruskal_wallis": kruskal_wallis_table,
    "pearson_correlation": correlation_table,
    "spearman_correlation": correlation_table,
    "simple_linear_regression": regression_table,
    "multiple_linear_regression": regression_table,
    "chi_square_independence": chi_square_table,
    "cronbachs_alpha": reliability_table,
}


def build_tables(result: TestResult, *, start_number: int = 1) -> list[APATable]:
    """Build the full table set for a result: the main table, a descriptives
    table where the main table has no room for it, and the §3.4 assumption
    table."""
    generator = _GENERATORS.get(result.analysis_type)
    if generator is None:  # pragma: no cover — registry and dispatch stay in sync
        raise KeyError(f"No APA table generator for {result.analysis_type!r}")

    number = start_number
    tables = [generator(result, number)]
    number += 1

    if get_spec(result.analysis_type).family is TestFamily.ANOVA:
        tables.append(descriptives_table(result, number))
        number += 1

    assumptions = assumption_table(result, number)
    if assumptions is not None:
        tables.append(assumptions)
    return tables
