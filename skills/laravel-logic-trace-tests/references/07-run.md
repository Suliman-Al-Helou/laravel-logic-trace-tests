This phase has no authoring. The script runs YOUR new tests itself (one file at a time, with JUnit output) and proves:
- RED: every GAP/NEW test fails with a failed assertion (not an error, not a wrong-reason failure such as a
  missing class or table). A GAP test that PASSES means the behavior already works or the test asserts the current
  behavior: fix the test or change the verdict.
- GREEN: every other new test passes.

Before running the gate (audit mode): delete the probes: `rm -r tests/Probes` (recorded results stay).
Then run the gate. If a test fails for the wrong reason, fix the TEST (never the app code) and run the gate again.
Changing a test file re-opens the tests phase so the checks run again.

Runner: if it is not `php artisan test` (Docker, Sail), the user sets LLTT_TEST_CMD before init, e.g.
`LLTT_TEST_CMD='sail artisan test'`. The runner must accept `--log-junit=<file>`.
