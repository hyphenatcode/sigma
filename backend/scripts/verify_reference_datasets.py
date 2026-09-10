#!/usr/bin/env python
"""Run the full pipeline over every reference dataset and print the output.

This is step 3 of §8's validation strategy: before any real-user pilot, run all
reference datasets end to end and manually read every generated Turkish
interpretation sentence and APA table. The unit tests check the numbers; this
script exists so a human can check the *prose* and the table layout, which no
assertion can judge.

    cd backend && python scripts/verify_reference_datasets.py
    cd backend && python scripts/verify_reference_datasets.py --llm

Without --llm the deterministic templates are shown. With --llm the Claude call
runs and the script reports, per analysis, whether the generated text passed
the §3.6 numeric-token validation or was rejected and replaced.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

import pandas as pd  # noqa: E402

from app.apa.tables import build_tables  # noqa: E402
from app.interpretation.service import interpret  # noqa: E402
from app.stats.enums import MeasurementLevel as ML  # noqa: E402
from app.stats.enums import ResearchTask as RT  # noqa: E402
from app.stats.pipeline import (  # noqa: E402
    AnalysisRequest,
    UnsupportedAnalysisError,
    run_analysis,
)

FIXTURES = BACKEND_ROOT / "tests" / "fixtures"

RATIO, NOMINAL, ORDINAL = ML.RATIO, ML.NOMINAL, ML.ORDINAL

CASES: list[tuple[str, str, dict]] = [
    ("Bağımsız örneklem t-testi", "ttest_independent.csv", dict(
        task=RT.COMPARISON, dependent_variable="basari_puani",
        independent_variables=["yontem"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL})),
    ("Bağımlı örneklem t-testi", "ttest_paired.csv", dict(
        task=RT.COMPARISON, is_paired=True,
        paired_measurements=["on_test", "son_test"],
        measurement_levels={"on_test": RATIO, "son_test": RATIO})),
    ("Tek yönlü ANOVA", "anova_three_groups.csv", dict(
        task=RT.COMPARISON, dependent_variable="kaygi_puani",
        independent_variables=["sinif_duzeyi"],
        measurement_levels={"kaygi_puani": RATIO, "sinif_duzeyi": NOMINAL})),
    ("Welch ANOVA (varyans homojenliği ihlali)", "anova_unequal_variance.csv", dict(
        task=RT.COMPARISON, dependent_variable="memnuniyet",
        independent_variables=["bolum"],
        measurement_levels={"memnuniyet": RATIO, "bolum": NOMINAL})),
    ("Mann-Whitney U (normallik ihlali)", "nonparametric_skewed.csv", dict(
        task=RT.COMPARISON, dependent_variable="tepki_suresi",
        independent_variables=["grup"],
        measurement_levels={"tepki_suresi": RATIO, "grup": NOMINAL})),
    ("Pearson korelasyon", "correlation_regression.csv", dict(
        task=RT.RELATIONSHIP, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO})),
    ("Basit doğrusal regresyon", "correlation_regression.csv", dict(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO})),
    ("Çoklu doğrusal regresyon", "multiple_regression.csv", dict(
        task=RT.PREDICTION, dependent_variable="sinav_puani",
        independent_variables=["calisma_saati", "uyku_saati"],
        measurement_levels={"sinav_puani": RATIO, "calisma_saati": RATIO,
                            "uyku_saati": RATIO})),
    ("Ki-kare bağımsızlık testi", "chi_square.csv", dict(
        task=RT.COMPARISON, dependent_variable="tercih",
        independent_variables=["cinsiyet"],
        measurement_levels={"tercih": NOMINAL, "cinsiyet": NOMINAL})),
    ("Cronbach alfa", "reliability_scale.csv", dict(
        task=RT.SCALE_RELIABILITY,
        scale_items=[f"madde{i}" for i in range(1, 6)],
        measurement_levels={f"madde{i}": ORDINAL for i in range(1, 6)})),
]

#: Combinations §3.3 must refuse. Printed so a reviewer can read the wording of
#: every refusal a user might actually hit.
REFUSALS: list[tuple[str, str, dict]] = [
    ("Kategorik BD + sürekli BĞD (lojistik regresyon)", "ttest_independent.csv", dict(
        task=RT.COMPARISON, dependent_variable="yontem",
        independent_variables=["basari_puani"],
        measurement_levels={"basari_puani": RATIO, "yontem": NOMINAL})),
    ("Tekrarlı ölçümler ANOVA (3 ölçüm)", "reliability_scale.csv", dict(
        task=RT.COMPARISON, is_paired=True,
        paired_measurements=["madde1", "madde2", "madde3"],
        measurement_levels={f"madde{i}": RATIO for i in range(1, 6)})),
]


def rule(char: str = "=") -> str:
    return char * 78


def render_table(table) -> str:
    widths = [len(str(c)) for c in table.columns]
    for row in table.rows:
        widths = [max(w, len(str(cell))) for w, cell in zip(widths, row)]

    def line(cells) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    out = [f"{table.label}", f"{table.title}", rule("-"), line(table.columns), rule("-")]
    out.extend(line(row) for row in table.rows)
    out.append(rule("-"))
    if table.note:
        out.append(f"Not. {table.note}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true",
                        help="call the Claude API instead of using the templates")
    args = parser.parse_args()

    failures = 0
    rejected = 0

    for title, filename, config in CASES:
        frame = pd.read_csv(FIXTURES / filename)
        print(f"\n{rule()}\n{title}  [{filename}]\n{rule()}")
        try:
            outcome = run_analysis(frame, AnalysisRequest(**config))
        except Exception as exc:  # noqa: BLE001 — this script reports, not raises
            failures += 1
            print(f"!! BAŞARISIZ: {type(exc).__name__}: {exc}")
            continue

        print(f"Önerilen: {outcome.recommendation.candidate}")
        print(f"Uygulanan: {outcome.executed_analysis_type}")
        if outcome.substituted:
            print(f"Değiştirme gerekçesi: {outcome.substitution_reason_tr}")

        interpretation = interpret(outcome.result, use_llm=args.llm)
        print(f"\nYorum kaynağı: {interpretation.source}")
        if interpretation.source == "template_after_rejection":
            rejected += 1
            print(f"  REDDEDİLEN SAYILAR: {interpretation.validation.offending_tokens}")
            print(f"  REDDEDİLEN METİN: {interpretation.rejected_text}")
        if interpretation.llm_error:
            print(f"  LLM notu: {interpretation.llm_error}")
        print(f"\n{interpretation.text_tr}\n")

        for table in build_tables(outcome.result):
            print(render_table(table))
            print()

    print(f"\n{rule()}\nDESTEKLENMEYEN KOMBİNASYONLAR (§3.3)\n{rule()}")
    for title, filename, config in REFUSALS:
        frame = pd.read_csv(FIXTURES / filename)
        try:
            run_analysis(frame, AnalysisRequest(**config))
        except UnsupportedAnalysisError as exc:
            print(f"\n{title}\n  -> {exc.message_tr}")
        else:
            failures += 1
            print(f"\n{title}\n  !! BEKLENEN RET GERÇEKLEŞMEDİ")

    print(f"\n{rule()}")
    print(f"{len(CASES)} analiz çalıştırıldı, {failures} hata, "
          f"{rejected} yorum doğrulamadan geçemedi.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
