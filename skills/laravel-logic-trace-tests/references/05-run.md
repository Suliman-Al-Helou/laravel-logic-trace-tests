This phase has no authoring. The script runs the tests itself, one file at a time, so a claim
of "tests pass" cannot be made up.

Before running the gate:
1. Delete the probes: `rm -r tests/Probes` (the recorded results in `.trace/probes/` stay).
2. Make sure your new test files are saved.

Then run the gate. If a test fails, fix the TEST (never the app code), then run the gate again.
Changing a test file re-opens phase 4 automatically, so the checks run again.

If the runner command is not `php artisan test` (Docker, Sail...), the user must set
`LLTT_TEST_CMD` before `init`, for example `LLTT_TEST_CMD='sail artisan test'`.
