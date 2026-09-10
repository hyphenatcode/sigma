# Sigma

Turkish-language statistical analysis platform for graduate students writing
quantitative thesis chapters — upload a dataset, define the research question,
get an APA-formatted table, a Turkish APA-style interpretation, and a Word/PDF
report, without knowing SPSS.

Built to the spec in [`requirements-specification.md`](requirements-specification.md);
section references throughout the code point back to it.

## The central design constraint

**The LLM never computes a statistic.** Every number comes from a deterministic
Python engine. Claude is used only to phrase a Turkish sentence around numbers
the engine already computed, and its output is machine-checked before a user
sees it:

```
engine result ──► payload (computed values only, never raw rows)
                     │
                     ├──► deterministic Turkish template  ─────┐
                     │                                          │
                     └──► Claude (constrained prompt) ──► numeric-token
                                                          validation
                                                               │
                                            pass ──► LLM text  │
                                            fail ──► template ◄┘  (+ logged)
```

Every numeric token in the model's output must trace to a value in the payload.
If any does not, the text is discarded, the deterministic template ships
instead, and the rejection is logged for review. Sigma works with no API key at
all — the statistics and the report are identical, only the prose is less fluid.

## What v1 does

Rule-based test selection (§3.3) across exactly these analyses, with automatic
assumption checking (§3.4) that swaps in the non-parametric fallback or the
unequal-variance variant and always says why:

| Family | Tests |
|---|---|
| t-tests | independent, paired, Welch |
| ANOVA | one-way, Welch |
| Non-parametric | Mann-Whitney U, Wilcoxon signed-rank, Kruskal-Wallis |
| Correlation | Pearson, Spearman |
| Regression | simple and multiple linear |
| Categorical | chi-square of independence |
| Reliability | Cronbach's alpha |

Effect sizes are mandatory (§3.5) and reported with their small/medium/large
band. Anything the decision tree does not cover produces an explicit Turkish
"not supported in this version" message — never a best-guess neighbouring test.

**Named by §3.3 but not executable in v1:** repeated-measures ANOVA, Friedman,
and exploratory factor analysis. The recommendation engine still selects and
*names* them so the refusal is precise; implementing them needs spec detail the
requirements doc does not give (sphericity correction policy; EFA extraction,
rotation and retention rules). See `TODO(spec-gap)` comments.

## Layout

```
backend/
  app/
    stats/            the engine — recommendation (§3.3), assumptions (§3.4),
                      effect sizes (§3.5), procedures, pipeline
    interpretation/   payload, templates, Claude call, token validator (§3.6)
    apa/              APA 7th-edition table generators (§3.7)
    export/           shared HTML -> preview + WeasyPrint PDF; python-docx Word (§3.8)
    api/              FastAPI routers (§6)
    models.py         SQLAlchemy models (§4)
  tests/
    fixtures/         8 reference datasets with hand-verified expected values
frontend/             minimal Next.js flow exercising the whole pipeline
```

## Running it locally

Verified on Python 3.11 and Node 22 against PostgreSQL 16.

### Prerequisites

- **Python 3.11+** and **Node 20+**
- **PostgreSQL 14+**, running
- **Pango/cairo**, for the PDF export only:
  - Debian/Ubuntu: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b`
  - macOS: `brew install pango libffi`
  - Fedora: `sudo dnf install pango`

  If you skip this, everything else still works: report generation falls back
  to Word-only and the API returns a null `pdf_url` rather than failing.

### Setup

```bash
# 1. Python dependencies
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. Database — the role matters, not just the database. The default
#    DATABASE_URL is postgresql+psycopg2://sigma:sigma@localhost:5432/sigma,
#    so `createdb sigma` on its own is not enough.
sudo -u postgres psql -c "CREATE USER sigma WITH PASSWORD 'sigma' CREATEDB;"
sudo -u postgres createdb -O sigma sigma

# 3. Configuration. Keep .env at the repository root (it is read from there
#    whichever directory you start the app from).
cp .env.example .env
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#    ...paste that into STORAGE_ENCRYPTION_KEY in .env.
#    ANTHROPIC_API_KEY is optional: without it, interpretations come from the
#    deterministic Turkish templates and the statistics are unchanged.

# 4. Migrations
cd backend && ../.venv/bin/alembic upgrade head

# 5. Run
../.venv/bin/uvicorn app.main:app --reload      # http://localhost:8000/docs
```

```bash
# Frontend, in a second terminal
cd frontend && npm install && npm run dev       # http://localhost:3000
```

The frontend proxies `/api/*` to `http://localhost:8000` by default; set
`SIGMA_API_URL` to point it elsewhere.

Sign in with any email address — auth is a development seam, see below. A new
account gets one free analysis credit (§3.10); further runs return HTTP 402
until the İyzico flow is wired, so during development grant more with:

```sql
INSERT INTO credit_ledger (id, user_id, package_type, credits_remaining, purchased_at)
SELECT gen_random_uuid()::text, id, 'single_analysis', 10, now() FROM users;
```

### Tests

```bash
cd backend && ../.venv/bin/python -m pytest     # 244 tests, no database needed
```

The suite runs on SQLite and needs neither PostgreSQL nor an API key.

Step 3 of §8's validation strategy — reading every generated Turkish sentence
and APA table before a pilot — is a script, since no assertion can judge prose:

```bash
cd backend && ../.venv/bin/python scripts/verify_reference_datasets.py
cd backend && ../.venv/bin/python scripts/verify_reference_datasets.py --llm
```

With `--llm` it reports, per analysis, whether the generated text passed §3.6
validation or was rejected and replaced — and prints the rejected text.

## Sample data

`sample-data/` holds ten thesis-sized Turkish datasets covering every analysis
path, including the two where §3.4 overrides §3.3's first choice, an `.xlsx`
with missing cells, and a CSV in the semicolon/cp1254/comma-decimal format a
Turkish-locale Excel produces. `sample-data/README.md` lists which variables to
pick for each and what it should land on. Regenerate with:

```bash
.venv/bin/python sample-data/generate.py
```

These are separate from `backend/tests/fixtures/`, which stay small and
hand-verifiable because their job is to pin the engine's numbers.

## Correctness

§5 makes correctness the highest-priority requirement, so the engine is pinned
to reference values derived **independently of the engine** — each expected
number in `tests/test_procedures.py` comes from writing the textbook formula
out against the fixture (multiple regression via the normal equations, ANOVA
via the sum-of-squares decomposition, and so on), with the arithmetic recorded
in the test docstring. A failure there means the engine disagrees with the
definition, not merely with itself.

The §3.6 validator is tested against eleven intentionally corrupted LLM
outputs — altered statistics, altered df, altered effect sizes, invented
confidence intervals, citation years, sample sizes and post-hoc statistics —
and every deterministic template is confirmed to pass its own validator, so the
fallback path can never be self-rejecting.

One deliberate limit is pinned by a test: §3.6 specifies a *membership* check,
so it catches fabricated numbers but not a real number attached to the wrong
label (a median presented as a mean). The mitigation is that the deterministic
template, which cannot mislabel, is what ships whenever validation fails.

## Not implemented, on purpose

- **Auth** is an `X-User-Email` header seam, not security. §7 specifies
  Supabase Auth or Clerk, and §10 leaves the verification policy open.
  `get_current_user` is the single place a real verifier plugs in.
- **İyzico payments.** `POST /api/credits/purchase` validates the package and
  returns `pending` without granting credits. Wiring it needs merchant
  credentials and a signature-verified callback; a stub that granted credits
  would be a route that appears to take money and does not.
- Everything in §9 (mediation/moderation/SEM, institutional billing, async job
  queue, SPSS `.sav` import, mobile app).

## Privacy (§5, KVKK)

Uploaded datasets are Fernet-encrypted before touching disk and decrypted only
in memory for the duration of an analysis; a test asserts the plaintext is not
recoverable from the stored file. `DELETE /api/datasets/{id}` removes the file
and cascades the rows. Raw respondent-level data is never sent to the Anthropic
API — the §3.6 payload boundary enforces this by construction, and a test
asserts row-level values do not appear in it.
