# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The one constraint that overrides everything

**The LLM never computes a statistic.** Every number a user sees comes from
deterministic Python. Claude is used only to phrase a Turkish sentence around
numbers the engine already computed, and its output is machine-checked before
anyone sees it: every numeric token must trace back to a value in the payload,
or the text is discarded and a deterministic template ships instead.

This is a hallucination-safety requirement in an academic context, not a style
preference. Do not "improve" the interpretation layer by letting the model
derive, round, or infer a value. If a number needs to exist, compute it in
`app/stats/` and add it to the payload.

`requirements-specification.md` is the spec. Code comments cite it by section
(`§3.3`, `§3.4`…); keep that convention — it is how a reader checks behaviour
against intent.

## Commands

All Python commands run from `backend/` with the repo-root venv:

```bash
../.venv/bin/python -m pytest -q                          # 318 tests, ~10s
../.venv/bin/python -m pytest tests/test_pipeline.py -q   # one file
../.venv/bin/python -m pytest -q -k "welch or algorithm_confusion"
../.venv/bin/alembic upgrade head                         # migrations
../.venv/bin/uvicorn app.main:app --reload                # :8000, /docs for OpenAPI

# §8 step 3 — print every Turkish sentence and APA table for a human to read.
# No assertion can judge prose; this is how it gets judged.
../.venv/bin/python scripts/verify_reference_datasets.py
../.venv/bin/python scripts/verify_reference_datasets.py --llm   # adds the real API call
```

The suite runs on SQLite and needs neither PostgreSQL nor an API key. Passing
`pytest` therefore says nothing about whether the database is configured — the
Alembic step is the first thing that exercises it.

Frontend, from `frontend/`: `npm run dev`, `npm run build`, `npx tsc --noEmit`.
There is no lint script; the typecheck is the gate.

Regenerate the demo datasets with `.venv/bin/python sample-data/generate.py`
(seeded, so they reproduce byte for byte).

## Branching

`main` is protected and deploys to production. Work on a branch and open a pull
request; CI runs on the PR and on `main` after merge, and the three job names
(**Backend tests**, **Frontend build**, **Docker image builds**) are the
required checks. Do not push to `main` directly.

## Architecture

Request flow for the one thing this app does:

```
upload ─► ingestion ─► §3.3 recommend ─► §3.4 assumptions ─► execute ─► §3.5 effect size
                            │                   │
                            │                   └─ may SUBSTITUTE the test, and records why
                            └─ refuses outright if no rule matches
                                        │
                     ┌──────────────────┴──────────────────┐
                     ▼                                     ▼
              §3.7 APA tables                    §3.6 interpretation
                     │                        (payload → LLM → validate → fall back)
                     └──────────────┬──────────────────────┘
                                    ▼
                     §3.8 one HTML template → preview + PDF; python-docx → Word
```

**`app/stats/`** is the engine and is pure — no I/O, no LLM, no database.
`recommendation.py` is a transcription of §3.3's decision tree as a pure
function. `pipeline.py` is the only place a test gets swapped for its
non-parametric fallback or unequal-variance variant, and it always records the
Turkish reason on the result.

**`app/stats/registry.py`** is a pluggable `AnalysisType` registry (§3.9). Adding
an analysis means appending a spec and a runner; the recommender, pipeline, API
and data model do not change. Tests §3.3 names but v1 cannot execute
(repeated-measures ANOVA, Friedman, EFA) are registered with
`supported_in_v1=False` so refusals can *name* them rather than degrade to a
nearby test.

**`app/interpretation/`** is the safety boundary. `payload.py` reduces a result
to computed values only — there is no code path from uploaded rows to the
Anthropic API, which is also what §5's KVKK requirement turns on.
`validator.py` enforces the numeric-token rule. `service.py` fixes the order:
build payload → render template → call LLM → validate → on failure discard and
keep the template.

**`app/auth.py`** verifies Supabase JWTs. `_key_for` returns the key *and* the
permitted algorithms together — that pairing is what prevents algorithm
confusion, so do not refactor it into separate lookups.

## Things that will bite

**Reference fixtures are hand-verified.** Expected values in
`tests/test_procedures.py` were derived independently of the engine by writing
the textbook formula out against the fixture; the arithmetic is in each
docstring. If one fails, the engine is wrong — do not adjust the expected value
to match. (Three times during the build the *test constant* was the error; the
docstring arithmetic is how that was settled each time.)

**§3.3 refuses rather than guesses.** An uncovered combination returns an
explicit Turkish message. Do not add a "closest match" fallback. Where the spec
is genuinely silent, implement the narrower behaviour and leave a
`# TODO(spec-gap):` explaining what is uncovered — there are eight of these,
and they are deliberate.

**The §3.6 validator is a membership check, not a binding check.** It catches
fabricated numbers but not a real number attached to the wrong label (a median
presented as a mean). This is what §3.3 specifies and is pinned by a test. The
mitigation is that the template — which cannot mislabel — ships on any failure.

**Welch's ANOVA has its own APA table** with no sum-of-squares columns. Welch
adjusts denominator df rather than partitioning SS, so printing an SS/MS source
table beside Welch's F produces a table that does not reconcile.

**Config is read from absolute paths.** `env_file` resolves against the working
directory, so a relative `.env` was silently ignored when the app started from
`backend/`. Keep `.env` at the repo root.

**Losing `STORAGE_ENCRYPTION_KEY` loses every uploaded dataset**, irreversibly.
Unset, the app uses a per-process ephemeral key and data becomes unreadable at
the next restart. `ENVIRONMENT=production` refuses to boot without it.

**Storage encryption sits above the backend**, in `storage.save`/`load`, so
local and R2 carry the identical §5 guarantee. Do not push it down into R2's
server-side encryption — that would put a readable key in Cloudflare's hands.
`Dataset.storage_path` holds a *key* (`datasets/<id>.csv.enc`), not a
filesystem path; the local backend still honours absolute paths as a migration
shim for rows written before R2.

## Not implemented, deliberately

İyzico returns
`pending` without granting credits rather than faking a payment. The LLM path
has only ever run against mocks. Everything in §9 is out of scope.

`ALLOW_INSECURE_HEADER_AUTH` accepts an `X-User-Email` header so local
development and the tests need no Supabase project. It is not authentication;
it is off by default and production refuses to start with it enabled.
