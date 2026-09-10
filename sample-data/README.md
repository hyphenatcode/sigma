# Örnek veri setleri / Sample datasets

Ten thesis-sized datasets for exercising the app by hand. Regenerate with:

```bash
.venv/bin/python sample-data/generate.py
```

These are **not** the reference datasets in `backend/tests/fixtures/` — those
are tiny and hand-verifiable and exist to pin the engine's numbers. These are
realistic: Turkish column names and category labels, coded variables, skewed
distributions, missing cells, and one file in the format a Turkish-locale Excel
actually exports.

Upload a file, confirm the variable roles listed below, and pick the stated
research goal.

| # | File | n | Research goal | Dependent | Independent | Lands on |
|---|---|---|---|---|---|---|
| 01 | `01_ogretim_yontemi_basari.csv` | 120 | Gruplar arası fark | `basari_puani` | `yontem` | Independent t-test |
| 02 | `02_ontest_sontest.csv` | 80 | Gruplar arası fark *(tick "aynı kişiler")* | — | `on_test`, `son_test` | Paired t-test |
| 03 | `03_sinif_duzeyi_kaygi.csv` | 160 | Gruplar arası fark | `kaygi_puani` | `sinif_duzeyi` | One-way ANOVA |
| 04 | `04_bolum_memnuniyet_welch.csv` | 135 | Gruplar arası fark | `memnuniyet_puani` | `bolum` | **Welch ANOVA** |
| 05 | `05_arayuz_tepki_suresi.csv` | 110 | Gruplar arası fark | `tepki_suresi_sn` | `arayuz` | **Mann-Whitney U** |
| 06 | `06_akademik_basari_yordayicilari.csv` | 150 | İlişki | `akademik_ortalama` | `haftalik_calisma_saati` | Pearson correlation |
| 06 | *(same file)* | 150 | Yordama | `akademik_ortalama` | the three predictors | Multiple regression |
| 07 | `07_cinsiyet_yontem_tercihi.csv` | 330 | Gruplar arası fark | `arastirma_yontemi_tercihi` | `cinsiyet` | Chi-square |
| 08 | `08_olcek_guvenirlik.csv` | 200 | Ölçek güvenirliği | — | 20 `madde_*` items | Cronbach's alpha |
| 09 | `09_eksik_veri.xlsx` | 140 | Gruplar arası fark | `yasam_doyumu` | `grup` | Independent t-test |
| 10 | `10_turkce_excel_ciktisi.csv` | 100 | Gruplar arası fark | `sinav_puani` | `grup` | Independent t-test |

Set the measurement level to **Oranlı (ratio)** for the continuous variables and
**Sınıflama (nominal)** for the grouping ones. For 07 both variables are nominal;
for 08 the items are **Sıralama (ordinal)**.

## What each file is really testing

**01–03** are the straightforward paths: §3.3 picks a test, §3.4 confirms its
assumptions hold, and it runs.

**04 and 05 are the interesting ones.** Both start somewhere and end somewhere
else, and the report says so:

- **04** — three departments, normal within each but with very different
  spreads. §3.3 picks a one-way ANOVA; Levene's test fails; §3.4 substitutes
  **Welch's ANOVA**. The result screen shows an amber banner explaining the
  swap, and the same sentence appears in the Word and PDF exports.
- **05** — reaction times, right-skewed as reaction times always are. §3.3
  picks an independent t-test; the normality check fails in both groups; §3.4
  substitutes **Mann-Whitney U** and the interpretation switches to mean ranks.

**06** yields two different analyses from one file depending on whether you say
you are looking for a relationship or trying to predict — this is the §3.3
ambiguity resolved by asking rather than guessing.

**07** has group labels with no digits but a 2×3 table, so Cramér's V is banded
against the df-adjusted thresholds rather than the plain .1/.3/.5 cuts.

**08** is a 20-item Likert scale with one strong latent factor, producing an
alpha near .94 and a per-item "alpha if deleted" column.

**09** is an `.xlsx` with 18 blank cells scattered through it. The analysis runs
on the complete cases; note the reduced *n* in the report (122, not 140).

**10** is the file most likely to arrive from a real user: saved as CSV by a
Turkish-locale Excel, so it is semicolon-separated, cp1254-encoded, and writes
scores as `68,52` rather than `68.52`. All three are handled at ingest.

## Seeing a refusal

§3.3 refuses anything its rules do not cover rather than picking a nearby test.
To see that, take **01** and ask for the opposite of a sensible analysis:
dependent `yontem` (categorical), independent `basari_puani` (continuous). You
get an explicit Turkish message rather than a result — and the credit is
refunded.

`03_sinif_duzeyi_kaygi.csv` also has group labels containing digits
(`1. sınıf` … `4. sınıf`), which exercises the §3.6 validator's handling of
numbers that legitimately appear inside category names.
