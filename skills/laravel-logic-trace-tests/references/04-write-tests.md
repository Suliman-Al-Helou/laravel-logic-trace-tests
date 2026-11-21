# Phase 4 — Write the tests

Output: test files under `tests/Feature` (HTTP flow) or `tests/Unit` (pure logic with
no framework). Detect the project's style first: look at 2 existing tests and copy
the runner (Pest/PHPUnit), naming, factories and helpers.

## Two kinds of test per edge case

**A. CURRENT == RECOMMENDED**, or no recommendation established → one normal test
asserting the observed behavior.

**B. CURRENT != RECOMMENDED** →
1. A characterization test that asserts the CURRENT observed behavior (it passes today).
   Add `->group('current-behavior')` (Pest) or `#[Group('current-behavior')]` (PHPUnit).
2. A second test asserting the RECOMMENDED behavior, marked pending:
   Pest `->todo()`, PHPUnit `$this->markTestIncomplete('RECOMMENDED: ...')`.
   Do not make it fail the suite.

## Required comment block (the gate script parses this) — put it right above the test

```php
// EDGE: E-03
// COVERS: D-07
// CURRENT: second identical POST returns 201 and creates a duplicate order
// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
```

- `WHY` is ONE short sentence.
- `EVIDENCE` must contain a real `file.php:line` AND a probe id whose
  `.trace/probes/P-xx.json` exists.
- Tests that are not edge cases (plain happy path) need only `// COVERS: D-xx`.

## Test quality rules

- Test through the public boundary: HTTP request, or a public service method. Do not
  assert private state or call private methods.
- Never mock the class under test. Fake only external boundaries (mail, HTTP client,
  storage, queue when checking dispatch).
- Every test has a real assertion on an observable result (status, JSON, DB row, event).
  Never `assertTrue(true)`. Do not assert only "no exception".
- Assert exact values from the probe (status code, validation error KEYS, DB counts),
  not loose checks like "status is not 500".
- Tests are independent and deterministic: use factories, `Carbon::setTestNow()` for time.
- Name: `it('<condition> -> <outcome>')` using the decision-table wording.
- One decision-table row can be covered by several tests; every row must be covered
  or marked `SKIP: reason`.
