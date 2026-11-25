Find out whether tests ALREADY exist for this target and whether they really check the edge cases or
only the happy path. Write `.trace/existing-tests.md`:

| ID | Existing test | Strength | Reason |

One row for EVERY decision row (D-01...). Steps:
1. Find existing tests: grep `tests/` for the route URI, the controller, the service, the FormRequest names.
2. Run `python3 SKILL_DIR/scripts/lltt.py scan-tests <test file or folder>`. It prints each test with a label:
   `success-only` (asserts only a success status), `checks-more-than-success`, or `no-assert`.
3. For each decision row choose:
   - STRONG: a test that asserts the behavior of THAT row, including its failure path or the stored state
     (database, role, cache, dispatched job). `Existing test` = `tests/Path/File.php:LINE` (a line inside it).
   - WEAK: a test touches the row but only asserts a success status, or does not check the state. Same cell format.
   - NONE: nothing covers the row. `Existing test` = `-`.
4. Reason: 3+ words saying why (e.g. "asserts 422 and the error key", "only checks 201, not the role").

The gate rejects STRONG when the cited test is `success-only`, and cited tests that do not exist.
Tests that look like "written only to pass": one success assertion, no failure-path assertion, no state check.
