Observe what REALLY happens. A probe is a throwaway test that runs the real code path with the
edge input and records the result through ProbeRecorder. Hand-written probe results are rejected.

Setup (once):
1. Copy `assets/ProbeRecorder.php` to `tests/Support/ProbeRecorder.php` (fix the namespace to match
   composer.json autoload-dev).
2. Create `tests/Probes/` and put probe tests there. Use the same DB trait as the project's feature
   tests (see `.trace/env.txt`, `db_trait`).

One probe per row that has `P-xx` in the decision table:

```php
it('P-03 duplicate submit', function () {
    $user = User::factory()->create();
    $payload = [/* valid values with the edge applied */];
    $first  = $this->actingAs($user)->postJson('/api/orders', $payload);
    $second = $this->actingAs($user)->postJson('/api/orders', $payload);

    \Tests\Support\ProbeRecorder::save('P-03', 'D-07', [
        'status_1' => $first->status(),
        'status_2' => $second->status(),
        'body_2'   => $second->json(),
        'db_count' => \App\Models\Order::count(),
    ]);
});
```

- The probe id and row id must match the decision table. Always include a `status` key for HTTP cases.
- Run only the probe files, e.g. `php artisan test tests/Probes/OrderProbeTest.php`, then OPEN the
  `.trace/probes/P-xx.json` files and read them.
- An exception is a valid observation: catch it and record class and message.
- Do not edit app code to make a probe pass. If a probe cannot run, fix the probe.
- Compare each result with the row's Code outcome. If a probe shows a different status than the code
  reading, keep it in mind: it is a strong candidate for a GAP in the expect phase. Do not hide it.

The recorded results are facts about TODAY's behavior. The next phases decide what the CORRECT behavior is.
