Write the tests under `tests/Feature` (HTTP flow) or `tests/Unit` (pure logic). Copy the style of
two existing tests (runner, naming, factories, helpers). Only NEW tests are checked.

Above EVERY new test put:
```php
// COVERS: D-07
```
Plain tests need only COVERS. An edge case needs the full block:
```php
// EDGE: E-03
// COVERS: D-07
// VERDICT: DIFFERS
// CURRENT: second identical POST returns 201 and creates a duplicate order
// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
```
- VERDICT: SAME (current is already what is recommended), DIFFERS, or NO-RECOMMENDATION
  (then RECOMMENDED must be exactly `none established`).
- DIFFERS needs TWO tests with the same block: one real test pinning CURRENT with
  `->group('current-behavior')` (PHPUnit: `#[Group('current-behavior')]`), and one pending test for
  RECOMMENDED: Pest `->todo()`, PHPUnit `$this->markTestIncomplete('reason')`.
- Edge ids are E-01, E-02 ... with no gaps. WHY is ONE sentence, max 200 characters.
- EVIDENCE: a real file.php:line plus a probe id whose probe was recorded for a row you COVER.
- Every status code you write in CURRENT must appear in that probe's observed data.
- RECOMMENDED precedent must not be the code under test (see phase 3 rules).
- Every probe row that differs from the code reading (the gate told you) needs an EDGE.
- Every decision row must be covered (rows marked `no:external/unreachable` are exempt;
  `no:duplicate-of:D-xx` is covered through D-xx).

Quality rules: test through the public boundary (HTTP or a public service method); never mock a class
that is in the logic map (fake mail, storage, HTTP client, queue only, or add
`// ALLOW-MOCK: ClassName reason`); every test asserts an observable result; assert exact values from
the probes; no `assertTrue(true)`; skip/incomplete need a reason; deterministic (factories,
`Carbon::setTestNow`).
