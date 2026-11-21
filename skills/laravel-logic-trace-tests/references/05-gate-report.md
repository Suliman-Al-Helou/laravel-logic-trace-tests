# Phase 5 — Gate and report

## 1. Run the gate

From the project root:

```
python3 <skill-dir>/scripts/verify_tests.py
python3 <skill-dir>/scripts/verify_tests.py --run    # also runs the test suite
```

Fix every `FAIL`. Re-run. Max 3 rounds. `WARN` lines go to the report.

The gate checks: edge blocks complete, evidence files and lines exist, probe files
exist, every decision-table row covered or skipped, no assertion-less tests, no
placeholder assertions, no `skip()` without a reason.

## 2. Clean up

Delete `tests/Probes/` unless the user asked to keep it. Keep `.trace/`.

## 3. Write `.trace/behavior-report.md`

Use `assets/behavior-report.template.md`. One row per edge case:
ID | Current (observed) | Recommended | Why (one sentence) | Evidence.
Add a section `UNVERIFIED` for anything you could not probe, and `Not covered`
for rows marked SKIP.

## 4. Final answer to the user (short)

- the report table (or its path if more than ~10 rows)
- commands you ran and their real result
- what is UNVERIFIED and why
- Do not claim coverage numbers you did not measure.
