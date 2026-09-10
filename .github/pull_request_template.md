## What changed, and why

<!-- One or two sentences. Link the §-section of requirements-specification.md
     if this touches specified behaviour. -->

## Checks that matter in this repo

<!-- Delete the lines that do not apply. -->

- [ ] **Statistics engine** (`app/stats/`): any new or changed expected value in
      `tests/test_procedures.py` was derived independently of the engine, with
      the arithmetic written into the test docstring. A failing reference test
      was not "fixed" by adjusting the constant.
- [ ] **Interpretation layer** (`app/interpretation/`): the LLM still computes
      nothing. Any number the narrative can mention is computed in
      `app/stats/` and present in the payload.
- [ ] **§3.3 decision tree**: no "closest match" fallback added. Uncovered
      combinations still refuse explicitly, and any genuine spec silence is
      marked `# TODO(spec-gap):`.
- [ ] **Migration**: applies *and* reverses cleanly.
- [ ] Ran `scripts/verify_reference_datasets.py` and read the output, if this
      changes anything a user reads.

## Anything not verified

<!-- State it plainly rather than leaving it implied — e.g. "not tested against
     a live Supabase project", "image not built locally". -->
