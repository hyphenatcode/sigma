# Claude Code prompt — Turkish statistics platform MVP

Copy everything below the line into Claude Code. Place `requirements-specification.md` in the project root first, since the prompt refers to it.

---

I'm building an MVP of a web platform that helps Turkish graduate students run statistical analyses for their theses without needing to know SPSS. The full requirements are in `requirements-specification.md` in this repo — read it in full before writing any code.

**Non-negotiable design constraint**: the statistics engine is 100% deterministic Python. The LLM (Claude API) is only ever used to phrase a Turkish-language interpretation sentence around numbers the statistics engine already computed — it never computes or invents a number itself. Every numeric token the LLM outputs must be validated against the engine's actual output before being shown to a user. Treat this as a hard constraint, not a nice-to-have.

## Tech stack

Use exactly what's specified in §7 of the requirements doc:
- Backend + stats engine: Python, FastAPI, pandas, scipy.stats, statsmodels, pingouin
- Frontend: Next.js + Tailwind
- Database: PostgreSQL
- Document export: python-docx + a shared HTML→PDF path (WeasyPrint) so the in-app preview, Word export, and PDF export never drift out of sync
- No Celery/queue infrastructure, no microservices split — one FastAPI app, synchronous requests

## Build order (please follow this sequence — do not jump ahead to the frontend before the engine is solid)

### Phase 1 — Statistics engine core (highest priority, do this first and get it right)
1. Scaffold the FastAPI project structure.
2. Implement the rule-based test recommendation function exactly as specified in §3.3 of the requirements doc (the decision-tree pseudocode). Write it as a pure function that takes variable metadata and returns a candidate test — no LLM involved anywhere in this function.
3. Implement the assumption-checking layer from §3.4 (Shapiro-Wilk, Levene, VIF, Breusch-Pagan) as a separate pure module that the recommendation function calls to decide between a parametric test and its non-parametric fallback.
4. Implement the actual statistical test execution (independent t-test, paired t-test, one-way ANOVA, Mann-Whitney U, Kruskal-Wallis, Pearson/Spearman correlation, simple/multiple linear regression, chi-square, Cronbach's alpha) using `scipy.stats`/`statsmodels`/`pingouin`.
5. Implement effect size calculation per §3.5 for every test above, including the small/medium/large band lookup.
6. Build 5-10 small reference CSV datasets with hand-verifiable expected outputs (or cross-checked against R/jamovi if you have access to run them) and write a unit test for every test function asserting the output matches the reference within a reasonable tolerance. Do not proceed to Phase 2 until these pass.

### Phase 2 — Turkish interpretation + APA table generation
7. Implement the APA table generator (§3.7) as deterministic Python — one function per test family, following APA 7th-edition table conventions.
8. Implement the Claude API call for Turkish interpretation (§3.6): a fixed prompt template per test type that receives only the computed JSON payload, never raw data. Implement the post-generation numeric-token validation check described in §3.6, and write unit tests that feed it intentionally corrupted LLM output to confirm it correctly rejects mismatches.

### Phase 3 — API layer
9. Implement the endpoints listed in §6 of the requirements doc: dataset upload, variable confirmation, analysis creation, analysis retrieval, report generation, credits.
10. Wire up PostgreSQL using the data model in §4. Use an ORM (SQLAlchemy) with Alembic migrations.

### Phase 4 — Export
11. Implement Word (.docx) export via python-docx and PDF export via the shared HTML template + WeasyPrint, per §3.8.

### Phase 5 — Minimal frontend
12. Build the smallest possible Next.js flow that exercises the full pipeline: upload → confirm variables → pick analysis → view result → download report. Don't over-invest in visual design at this stage — functional and clear is the bar, not polished.

## What NOT to build right now

Do not implement anything listed in §9 of the requirements doc as out of scope: no mediation/moderation/SEM analyses, no institutional multi-seat billing, no async job queue, no SPSS file import, no mobile app. If you find yourself about to build one of these, stop and flag it instead.

## When you're unsure

If a statistical edge case comes up that isn't covered in the requirements doc's decision tree (§3.3) or assumption table (§3.4), don't guess — implement the narrower, explicitly-covered behavior and leave a `# TODO(spec-gap):` comment explaining what case is uncovered, rather than silently extending the rule-based logic beyond what's specified. Correctness and narrow scope matter more than coverage for this MVP (see the requirements doc's discussion of reputational risk in an academic context).
