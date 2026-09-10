# Requirements Specification — Turkish AI-Guided Statistical Analysis Platform

## 0. Document purpose

This is the technical requirements spec for the MVP described in the earlier Turkish product spec (`istatistik-platformu-spesifikasyon.md`). That document covers the business case, competitors, and pricing. This document translates it into buildable requirements: data model, decision logic, API surface, and stack — detailed enough to hand to an engineer (or Claude Code) with minimal ambiguity.

## 1. Product summary

A web application where a researcher uploads a dataset, defines their research question (DV/IV, group structure), receives a rule-based statistical test recommendation, runs the analysis, and receives:
- an APA-formatted results table
- a Turkish-language, APA-style narrative interpretation (including effect size)
- an exportable Word/PDF report

The core design constraint: **the LLM never computes statistics.** All numeric results come from a deterministic Python statistics engine. The LLM only phrases the interpretation of numbers it is given, inside a constrained template. This is a hallucination-safety requirement, not a style preference.

## 2. Users

- **Primary**: Turkish graduate students (MA/PhD) in social sciences, education, business, psychology running quantitative thesis chapters
- **Secondary**: faculty/researchers running quick analyses for papers
- **Future (v2+)**: institutional accounts (social science graduate institutes) — see §11

## 3. Functional requirements

### 3.1 Data ingestion
- Accept `.csv`, `.xlsx` upload (max 20MB for MVP)
- Parse into a tabular structure; detect header row
- Infer column data type: numeric, text/categorical, date (informational only, not used in v1 analysis)
- Present detected types to the user for confirmation/override before proceeding
- Store the parsed dataset keyed to a `Dataset` record (see data model)

### 3.2 Variable role & measurement-level assignment
User assigns, per relevant column:
- Role: dependent variable / independent variable / grouping variable / covariate (v2) / scale item (for reliability analysis)
- Measurement level: nominal / ordinal / interval / ratio
- For grouping variables: number of levels/groups is auto-counted from distinct values, shown to user for confirmation

### 3.3 Test recommendation engine (rule-based, deterministic — NOT an LLM call)

This is the core IP. Implement as an explicit decision tree function, not a prompt. Pseudocode of the v1 decision logic:

```
INPUT: dv_type, dv_measurement, iv_type, iv_measurement, n_groups, is_paired, n_ivs

IF dv is continuous (interval/ratio):
    IF iv is categorical:
        IF n_groups == 2:
            IF is_paired: candidate = "paired_t_test" (fallback: "wilcoxon_signed_rank")
            ELSE:          candidate = "independent_t_test" (fallback: "mann_whitney_u")
        IF n_groups > 2:
            IF is_paired: candidate = "repeated_measures_anova" (fallback: "friedman")
            ELSE:          candidate = "one_way_anova" (fallback: "kruskal_wallis")
    IF iv is continuous:
        IF n_ivs == 1: candidate = "pearson_correlation" (fallback: "spearman_correlation")
        IF n_ivs > 1:  candidate = "multiple_linear_regression"
    IF n_ivs == 1 AND iv continuous AND only relationship (no grouping): candidate = "simple_linear_regression"

IF dv is categorical AND iv is categorical:
    candidate = "chi_square_independence"

IF task == "scale_reliability":
    candidate = "cronbachs_alpha"

IF task == "factor_structure":
    candidate = "exploratory_factor_analysis"   # KMO + Bartlett gatekeeper tests included
```

- v1 must cover exactly these ~10 tests. Do not silently expand scope — a narrow, 100%-correct tool is the explicit product requirement (see stress-test discussion: wrong recommendations are reputationally worse than a "not supported yet" message).
- Any input combination not matching a rule → explicit "not supported in this version" message, never a best-guess fallback.

### 3.4 Assumption checking (runs automatically before finalizing test choice)

| Test family | Assumption | Check | If violated |
|---|---|---|---|
| t-tests, ANOVA | Normality | Shapiro-Wilk (n<50) or Kolmogorov-Smirnov (n≥50), per group | Switch candidate to non-parametric fallback listed in §3.3 |
| t-tests, ANOVA | Homogeneity of variance | Levene's test | Independent t-test → Welch's t-test; ANOVA → Welch's ANOVA |
| Regression | Linearity | Residual-vs-fitted pattern (visual flag, not auto-blocking in v1) | Flag in report, do not block |
| Regression | Multicollinearity | VIF per predictor | Flag if VIF > 10 |
| Regression | Homoscedasticity | Breusch-Pagan | Flag in report |
| Chi-square | Expected cell count | All expected counts ≥ 5 | Flag: consider Fisher's exact test (v2) |

The system always reports which assumption tests were run and their result — never silently skips this step.

### 3.5 Effect size (mandatory, not optional — per explicit product requirement)

| Test | Effect size metric | Interpretation thresholds (report which band it falls in) |
|---|---|---|
| t-tests | Cohen's d | 0.2 small / 0.5 medium / 0.8 large |
| ANOVA | eta-squared (η²) / partial η² | 0.01 small / 0.06 medium / 0.14 large |
| Correlation | r (itself is the effect size) | 0.1 / 0.3 / 0.5 |
| Regression | R² / adjusted R² | reported, not banded |
| Chi-square | Cramér's V | 0.1 / 0.3 / 0.5 (df-dependent, use standard table) |
| Non-parametric equivalents | rank-biserial r / epsilon-squared | standard bands |

### 3.6 Turkish interpretation generation (LLM layer — constrained)
- Input to the LLM call: a fixed JSON payload of computed values only (test name, statistic, df, p, effect size + band, group descriptives). The LLM never receives raw data.
- System prompt constrains output to a fixed sentence template per test type, in Turkish, APA-style, e.g.:
  `"{group1} ve {group2} arasında {yön} yönde {anlamlılık} bir fark bulunmuştur, t({df}) = {t}, p = {p}, d = {d} ({etki_büyüklüğü_yorumu})."`
- Output is validated post-generation: every numeric token in the LLM's output must exactly match a value from the input JSON (regex/string check). If mismatch → reject and re-render from template without the LLM, log the failure for review.

### 3.7 APA table generation
- Deterministic (Python), not LLM-generated
- One table generator function per test family, producing:
  - table number, title, column headers per APA 7th edition convention
  - a note row for significance markers and effect size explanation
- Output as both an inline HTML/preview table and an embeddable Word table object

### 3.8 Export
- Word (.docx): interpretation paragraph + APA table, using a python-docx template
- PDF: same content, generated from the same template (avoid maintaining two separate layout engines — render Word first, convert to PDF, or use a single HTML→PDF path for both preview and PDF)

### 3.9 Advanced analyses (v2 — explicitly out of v1 scope, but architecture must not block adding them)
- Mediation (Hayes Model 4), moderation (Model 1), moderated mediation (Models 7/14/59), serial mediation (Model 6), bootstrapped CIs
- SEM / path analysis, CFA, ANCOVA/MANOVA, McDonald's omega
- Design the `AnalysisType` registry (§4) as a pluggable list so these can be added without touching the core pipeline

### 3.10 Accounts & monetization
- Auth: email + university email verification (for the free tier / anti-abuse)
- Package-based credits, not subscription (per pricing discussion): `free_trial` (1 analysis), `single_analysis`, `thesis_bundle` (N analyses), `advanced_addon` (v2)
- Payment: local gateway (İyzico) for TL/KDV invoicing
- v1 does not need multi-seat/institutional billing, but the `Organization` entity (§4) should exist as a nullable foreign key from day one so v2 institutional licensing doesn't require a schema migration

## 4. Data model (core entities)

```
User
  id, email, university_email_verified (bool), organization_id (nullable, FK → Organization), created_at

Organization                # exists from v1 for future institutional licensing, unused in v1 UI
  id, name, plan_type, seat_limit, created_at

Dataset
  id, user_id (FK), filename, storage_path, row_count, column_count, uploaded_at

Variable
  id, dataset_id (FK), column_name, detected_type, confirmed_type, measurement_level, role

Analysis
  id, user_id (FK), dataset_id (FK), analysis_type (enum, from AnalysisType registry),
  variable_config (JSON: which Variables map to which roles),
  assumption_results (JSON), effect_size (JSON), raw_result (JSON), status, created_at

Report
  id, analysis_id (FK), interpretation_text_tr, apa_table_html, docx_path, pdf_path, created_at

CreditLedger
  id, user_id (FK), package_type, credits_remaining, purchased_at, payment_reference
```

## 5. Non-functional requirements

- **Correctness over coverage**: every statistical function must be unit-tested against known reference outputs (e.g., cross-checked against R or SPSS output on a fixed test dataset) before shipping. This is the single highest-priority NFR given the reputational stakes discussed earlier.
- **Data privacy (KVKK)**: uploaded datasets may contain personal data (survey respondent identifiers). Store uploaded files encrypted at rest; do not use uploaded data for any purpose beyond the requested analysis; provide a data-deletion endpoint; do not send raw respondent-level data to the LLM API (§3.6 already enforces this by design).
- **Language**: all user-facing UI and output text in Turkish. Backend code, comments, and this spec in English (standard practice, does not affect user-facing language).
- **Performance**: analysis run + report generation should complete in well under 10 seconds for typical thesis-sized datasets (n < 2000). No need for async job queue in v1 given this constraint — keep the request/response synchronous to reduce infrastructure complexity.
- **Accessibility**: standard web accessibility (form labels, keyboard nav) — no special requirement beyond baseline.

## 6. API surface (v1)

```
POST   /api/datasets                 upload file → returns dataset_id + detected variable list
PATCH  /api/datasets/{id}/variables  confirm/override variable types & roles
POST   /api/analyses                 { dataset_id, analysis_type, variable_config } → runs pipeline, returns Analysis
GET    /api/analyses/{id}            fetch result + assumption results + effect size
POST   /api/analyses/{id}/report     generate Report (docx + pdf) → returns download URLs
GET    /api/credits                  current user's remaining credits
POST   /api/credits/purchase         initiate payment flow (İyzico redirect)
```

## 7. Tech stack recommendation

| Layer | Choice | Why |
|---|---|---|
| Statistics engine | Python: `pandas`, `scipy.stats`, `statsmodels`, `pingouin` | `pingouin` in particular ships effect sizes and assumption tests (Shapiro, Levene) with clean APIs — reduces custom implementation risk |
| Backend API | Python, FastAPI | Same language as the stats engine (no cross-language serialization layer), async-friendly for the LLM call, auto-generated OpenAPI docs |
| LLM interpretation | Anthropic Claude API, constrained prompt + output validation (§3.6) | Turkish fluency, structured-output discipline |
| Document generation | `python-docx` for Word; render same template to PDF via `docx2pdf`/LibreOffice headless, or a single HTML→PDF path (`WeasyPrint`) shared with the in-app preview to avoid maintaining two layout engines | Avoids drift between preview, Word, and PDF outputs |
| Frontend | Next.js (React) + Tailwind CSS | Fast to build forms/tables, good ecosystem, easy Vercel deploy, doubles as the marketing site |
| Database | PostgreSQL | Relational structure fits the data model in §4 cleanly; JSON columns handle the flexible `variable_config`/`raw_result` fields |
| File storage | Cloudflare R2 (S3-compatible) | Cheaper egress than S3 for a cost-sensitive early-stage product |
| Auth | Supabase Auth or Clerk | Faster to ship than hand-rolled auth; either integrates cleanly with Postgres |
| Payments | İyzico | Local TL processing + KDV invoicing; Stripe is a poor fit for the Turkish market at this stage |
| Hosting | Backend: Railway or Fly.io. Frontend: Vercel | Low ops overhead for a small team, reasonable free/low tiers for MVP validation |
| Background jobs | None in v1 (see NFR on performance) — revisit only if report generation proves slow in practice | Avoid Celery/Redis complexity until proven necessary |
| Monitoring | Sentry | Minimal setup, catches the statistics-engine edge cases that matter most |

**Explicitly avoid for v1**: microservices split between stats engine and API (keep them in one FastAPI app — split later only if scaling demands it), Celery/queue infrastructure, multi-tenant institutional billing UI, any of the v2 advanced analyses in §3.9.

## 8. Validation & testing strategy

1. Build a fixed set of 5-10 reference datasets with known, pre-computed correct answers (cross-validated against R or jamovi output).
2. Every statistical function ships with a unit test asserting output matches the reference to a reasonable decimal tolerance.
3. Before any real-user pilot, run the full pipeline against all reference datasets and manually verify every generated Turkish interpretation sentence and APA table.
4. The output-validation check in §3.6 (numeric token matching) is itself unit-tested with intentionally corrupted LLM outputs to confirm it correctly rejects them.

## 9. Out of scope for v1 (explicit)

- Advanced analyses (§3.9)
- Institutional multi-seat accounts and billing UI
- Real-time collaboration
- Database/API connectors
- Any SPSS `.sav` file import (v2 candidate)
- Mobile app (web-responsive is sufficient for v1)

## 10. Open questions for the founder (not engineering decisions)

- Free-tier abuse prevention: is university-email verification sufficient, or is a stricter check needed given how price-sensitive this market is?
- Credit expiry policy: do thesis-bundle credits expire? (Affects `CreditLedger` schema slightly — decide before building the payments flow.)
