#!/usr/bin/env python
"""Generate the sample datasets in this directory.

These are NOT the reference datasets in backend/tests/fixtures — those are tiny
and hand-verifiable, and exist to pin the engine's numbers. These are
thesis-sized, Turkish, and deliberately messy in the ways real uploads are:
missing cells, coded categories, skewed distributions, a semicolon-separated
export from a Turkish Excel install.

Each file is built to exercise a specific path through the engine, including
the paths where §3.4 overrides §3.3's first choice. Seeds are fixed, so
re-running this reproduces the files byte for byte.

    python sample-data/generate.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent


def write_csv(frame: pd.DataFrame, name: str, **kwargs) -> None:
    frame.to_csv(OUT / name, index=False, **kwargs)
    print(f"  {name:44s} {frame.shape[0]:>4} satır × {frame.shape[1]} sütun")


# ---------------------------------------------------------------------------
# 01 — independent samples t-test
# ---------------------------------------------------------------------------

def dataset_01() -> None:
    """Two teaching methods, normally distributed, equal variances.

    Expected: §3.3 picks the independent t-test, §3.4 keeps it (normality and
    Levene both hold). Significant, medium-to-large Cohen's d.
    """
    rng = np.random.default_rng(101)
    n = 60
    frame = pd.DataFrame({
        "ogrenci_no": range(1, 2 * n + 1),
        "cinsiyet": rng.choice(["Kadın", "Erkek"], 2 * n),
        "yontem": ["Deney"] * n + ["Kontrol"] * n,
        "basari_puani": np.r_[
            rng.normal(73, 9, n), rng.normal(66, 9, n)
        ].round(0).astype(int),
    })
    write_csv(frame, "01_ogretim_yontemi_basari.csv")


# ---------------------------------------------------------------------------
# 02 — paired samples t-test
# ---------------------------------------------------------------------------

def dataset_02() -> None:
    """One group measured twice. Expected: paired t-test, large effect."""
    rng = np.random.default_rng(202)
    n = 80
    before = rng.normal(54, 11, n)
    frame = pd.DataFrame({
        "ogrenci_no": range(1, n + 1),
        "on_test": before.round(0).astype(int),
        "son_test": (before + rng.normal(9, 6.5, n)).round(0).astype(int),
    })
    write_csv(frame, "02_ontest_sontest.csv")


# ---------------------------------------------------------------------------
# 03 — one-way ANOVA
# ---------------------------------------------------------------------------

def dataset_03() -> None:
    """Four year groups, equal variances.

    The group labels contain digits ("1. sınıf"), which also exercises the
    §3.6 validator's handling of numbers inside category names.
    """
    rng = np.random.default_rng(303)
    n = 40
    levels = ["1. sınıf", "2. sınıf", "3. sınıf", "4. sınıf"]
    means = [44, 48, 53, 57]
    frame = pd.DataFrame({
        "ogrenci_no": range(1, n * 4 + 1),
        "sinif_duzeyi": np.repeat(levels, n),
        "kaygi_puani": np.concatenate(
            [rng.normal(m, 8, n) for m in means]
        ).round(0).astype(int),
    })
    write_csv(frame, "03_sinif_duzeyi_kaygi.csv")


# ---------------------------------------------------------------------------
# 04 — Welch's ANOVA (§3.4 substitution: Levene violated)
# ---------------------------------------------------------------------------

def dataset_04() -> None:
    """Three departments, normal within group but wildly unequal spreads.

    Expected: §3.3 picks one-way ANOVA, §3.4 substitutes Welch's ANOVA and the
    report explains why.
    """
    rng = np.random.default_rng(404)
    n = 45
    frame = pd.DataFrame({
        "katilimci_no": range(1, n * 3 + 1),
        "bolum": np.repeat(["Eğitim Bilimleri", "İşletme", "Psikoloji"], n),
        "memnuniyet_puani": np.concatenate([
            rng.normal(62, 4, n),    # tight
            rng.normal(58, 19, n),   # very wide
            rng.normal(66, 6, n),
        ]).round(1),
    })
    write_csv(frame, "04_bolum_memnuniyet_welch.csv")


# ---------------------------------------------------------------------------
# 05 — Mann-Whitney U (§3.4 substitution: normality violated)
# ---------------------------------------------------------------------------

def dataset_05() -> None:
    """Reaction times: right-skewed, as reaction times always are.

    Expected: §3.3 picks the independent t-test, §3.4 substitutes Mann-Whitney U.
    """
    rng = np.random.default_rng(505)
    n = 55
    frame = pd.DataFrame({
        "katilimci_no": range(1, 2 * n + 1),
        "arayuz": ["Klasik"] * n + ["Yenilenmiş"] * n,
        "tepki_suresi_sn": np.r_[
            rng.lognormal(0.95, 0.45, n), rng.lognormal(0.50, 0.45, n)
        ].round(2),
    })
    write_csv(frame, "05_arayuz_tepki_suresi.csv")


# ---------------------------------------------------------------------------
# 06 — correlation and multiple regression
# ---------------------------------------------------------------------------

def dataset_06() -> None:
    """Continuous predictors of a continuous outcome.

    Two analyses from one file: pick "İlişki" for a Pearson correlation with a
    single predictor, or "Yordama" with several for multiple regression.
    """
    rng = np.random.default_rng(606)
    n = 150
    # No .clip() anywhere: truncating the tails makes the variables non-normal,
    # which sends §3.4 to Spearman and defeats the point of this file. The
    # parameters are chosen so the values stay in plausible ranges on their own.
    calisma = rng.normal(14, 4.0, n)
    uyku = rng.normal(6.8, 1.0, n)
    motivasyon = rng.normal(0, 1, n) * 9 + 58 + calisma * 0.4
    ortalama = (
        0.58
        + 0.055 * calisma
        + 0.085 * uyku
        + 0.016 * motivasyon
        + rng.normal(0, 0.30, n)
    )
    frame = pd.DataFrame({
        "ogrenci_no": range(1, n + 1),
        "haftalik_calisma_saati": calisma.round(1),
        "gunluk_uyku_saati": uyku.round(1),
        "motivasyon_puani": motivasyon.round(0).astype(int),
        "akademik_ortalama": ortalama.round(2),
    })
    write_csv(frame, "06_akademik_basari_yordayicilari.csv")


# ---------------------------------------------------------------------------
# 07 — chi-square test of independence
# ---------------------------------------------------------------------------

def dataset_07() -> None:
    """Two categorical variables, 2 x 3 table. Expected: chi-square, Cramér's V
    banded against the df-adjusted thresholds (df* = 1 here)."""
    rng = np.random.default_rng(707)
    rows = []
    plan = {
        ("Kadın", "Nicel"): 52, ("Kadın", "Nitel"): 78, ("Kadın", "Karma"): 40,
        ("Erkek", "Nicel"): 84, ("Erkek", "Nitel"): 46, ("Erkek", "Karma"): 30,
    }
    for (cinsiyet, tercih), count in plan.items():
        rows.extend([(cinsiyet, tercih)] * count)
    rng.shuffle(rows)
    frame = pd.DataFrame(rows, columns=["cinsiyet", "arastirma_yontemi_tercihi"])
    frame.insert(0, "katilimci_no", range(1, len(frame) + 1))
    write_csv(frame, "07_cinsiyet_yontem_tercihi.csv")


# ---------------------------------------------------------------------------
# 08 — Cronbach's alpha
# ---------------------------------------------------------------------------

def dataset_08() -> None:
    """A 20-item 5-point Likert scale with one strong latent factor.

    Expected: alpha around .90, with a per-item "alpha if deleted" column.
    """
    rng = np.random.default_rng(808)
    n, k = 200, 20
    latent = rng.normal(0, 1, n)
    data = {}
    for item in range(1, k + 1):
        loading = rng.uniform(0.55, 0.8)
        raw = latent * loading + rng.normal(0, np.sqrt(1 - loading**2), n)
        data[f"madde_{item:02d}"] = np.clip(np.round(raw * 1.05 + 3.4), 1, 5).astype(int)
    frame = pd.DataFrame(data)
    frame.insert(0, "katilimci_no", range(1, n + 1))
    write_csv(frame, "08_olcek_guvenirlik.csv")


# ---------------------------------------------------------------------------
# 09 — Excel upload with missing cells
# ---------------------------------------------------------------------------

def dataset_09() -> None:
    """.xlsx with scattered blanks, to exercise the Excel reader and listwise
    deletion. Expected: the analysis runs on the complete cases and the report
    shows the reduced n."""
    rng = np.random.default_rng(909)
    n = 70
    puan = np.r_[rng.normal(71, 10, n), rng.normal(64, 10, n)]
    frame = pd.DataFrame({
        "katilimci_no": range(1, 2 * n + 1),
        "grup": ["Müdahale"] * n + ["Karşılaştırma"] * n,
        "yasam_doyumu": puan.round(1),
    })
    missing = rng.choice(frame.index, size=18, replace=False)
    frame.loc[missing, "yasam_doyumu"] = np.nan
    frame.to_excel(OUT / "09_eksik_veri.xlsx", index=False)
    print(f"  {'09_eksik_veri.xlsx':44s} {frame.shape[0]:>4} satır × {frame.shape[1]} sütun "
          f"({len(missing)} eksik hücre)")


# ---------------------------------------------------------------------------
# 10 — a CSV as a Turkish Excel install actually exports it
# ---------------------------------------------------------------------------

def dataset_10() -> None:
    """Semicolon separator, cp1254 encoding, comma as the decimal separator.

    This is what "Save as CSV" produces on a Turkish-locale Windows Excel, and
    it is the format most likely to arrive from a real user.
    """
    rng = np.random.default_rng(1002)
    n = 50
    frame = pd.DataFrame({
        "katilimci_no": range(1, 2 * n + 1),
        "grup": ["Çevrimiçi"] * n + ["Yüz yüze"] * n,
        "sinav_puani": np.r_[
            rng.normal(68.5, 8.0, n), rng.normal(74.2, 8.0, n)
        ].round(2),
    })
    frame.to_csv(
        OUT / "10_turkce_excel_ciktisi.csv",
        index=False, sep=";", decimal=",", encoding="cp1254",
    )
    print(f"  {'10_turkce_excel_ciktisi.csv':44s} {frame.shape[0]:>4} satır × "
          f"{frame.shape[1]} sütun (noktalı virgül, cp1254, ondalık virgül)")


if __name__ == "__main__":
    print("Örnek veri setleri oluşturuluyor:\n")
    for builder in [dataset_01, dataset_02, dataset_03, dataset_04, dataset_05,
                    dataset_06, dataset_07, dataset_08, dataset_09, dataset_10]:
        builder()
    print("\nTamamlandı.")
