Write the tests. Copy the style of two existing tests (runner, naming, factories). Only NEW tests are checked.
Put new tests under `tests/Feature` (HTTP flow) or `tests/Unit` (pure logic).

The rule: a test asserts the EXPECTED behavior from `.trace/expectations.md`. Never the current behavior.
A GAP test (audit) or NEW test (spec) must FAIL when the script runs it, because an assertion about the expected
behavior is false today. It must not error. Write it so it fails for the right reason:
- send the real request / call the real code path; assert the expected status code and the expected state.
- do not reference classes, routes (by name) or helpers that do not exist; use URL paths. A missing class makes
  an ERROR, which the gate rejects.
- never `->todo()`, `->skip()`, `markTestIncomplete` on a GAP/NEW test.

Above EVERY new test put `// COVERS: D-xx`. Plain tests (MATCH rows) need only that.
Above every GAP/NEW test put the full block:

```php
// EDGE: E-01
// COVERS: D-03
// KIND: GAP
// CURRENT: second identical POST returns 201 and creates a duplicate order
// EXPECTED: 409 and no second order
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
// SOURCE: docs/wayfinder/01-orders.md:58
it('duplicate submit is rejected with 409', function () {
    ...->assertConflict();
});
```
- KIND: `GAP` in audit mode, `NEW` in spec mode. The row's verdict in expectations.md must be the same.
- EXPECTED: same status numbers as the row's Expected. SOURCE: exactly the row's Source.
- CURRENT and EVIDENCE only in audit mode: EVIDENCE = a real file.php:line + the probe id recorded for that row;
  every status code in CURRENT must exist in that probe's data.
- WHY: ONE sentence, max 200 characters. One test per edge. Edge ids E-01, E-02 ... no gaps.
- The test must assert every status code that EXPECTED mentions (the number or the assertCreated-style helper).

Rows:
- GAP/NEW rows: one failing test each (full block).
- MATCH rows: a normal passing test, unless an existing test is STRONG for it.
- UNKNOWN rows: NO test. They are questions for the user.

Quality rules: through the public boundary; never mock a class from the logic map (fake mail, storage,
HTTP client, queue only; or `// ALLOW-MOCK: ClassName reason`); every test asserts an observable result and exact
values; no `assertTrue(true)`; deterministic (factories, `Carbon::setTestNow`).
