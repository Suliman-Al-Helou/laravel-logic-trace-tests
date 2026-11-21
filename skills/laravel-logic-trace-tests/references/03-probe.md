# Phase 3 — Probe: observe what really happens

Output: one `.trace/probes/P-xx.json` per probe. A probe is a throwaway test that
runs the real code path with an edge input and records the real result.

## Setup (once)

1. Copy `assets/ProbeRecorder.php` to `tests/Support/ProbeRecorder.php`.
   Adjust the namespace to match `composer.json` autoload-dev (usually `Tests\Support`).
2. Create `tests/Probes/` (probe files live here and are deleted after phase 4,
   unless the user asks to keep them).
3. Probes MUST use the same DB trait as the project's feature tests
   (`RefreshDatabase` / `DatabaseTransactions`). Confirm with `.trace/env.txt`.
   If env.txt printed a STOP about the database, do not run probes.

## One probe per decision-table row you intend to test

```php
// tests/Probes/OrderProbeTest.php  (Pest style; PHPUnit: same body in a test method)
it('P-03 duplicate submit', function () {
    $user = User::factory()->create();
    $payload = [/* values copied from the factory/rules, with the edge applied */];

    $first  = $this->actingAs($user)->postJson('/api/orders', $payload);
    $second = $this->actingAs($user)->postJson('/api/orders', $payload);

    ProbeRecorder::save('P-03', 'D-07', [
        'request'  => $payload,
        'status_1' => $first->status(),
        'status_2' => $second->status(),
        'body_2'   => $second->json(),
        'db_count' => \App\Models\Order::count(),
    ]);
});
```

Run only that probe: `php artisan test --filter=P-03` (or `vendor/bin/pest --filter=P-03`).
Then OPEN `.trace/probes/P-03.json` and read it.

## Rules

- Record raw values: status code, JSON body (or validation error keys), DB counts or
  column values, dispatched jobs/events (use `Event::fake()/Queue::fake()` ONLY when
  you are checking dispatch, and say so in the probe's `note`).
- A probe that errors with an exception is a valid observation: record the
  exception class and message (`try/catch` around the call, then `ProbeRecorder::save`).
- If a probe does not run (syntax, missing factory), fix it. Do not invent its result.
- Do not edit application code to make a probe pass.
- Compare each result with the decision-table "Code outcome". If they differ, the
  difference itself is an edge case: keep both in the row notes.

## Deciding RECOMMENDED (after observing)

Find the recommended behavior in this order, stop at the first hit:
1. **Project precedent.** grep other controllers/services for the same situation
   (e.g. how other endpoints answer a duplicate or a missing record). Cite `file.php:line`.
2. **Laravel documentation.** If web access exists, search the Laravel docs for the
   exact feature (validation, authorization, queues, eloquent...). Cite page + section.
3. Neither found: `RECOMMENDED: none established`.

Current behavior that matches the precedent/docs: `CURRENT == RECOMMENDED`, normal test.
