# Changelog

## 0.3.0: failing tests from documented expectations
Goal change: the skill no longer pins today's behavior with passing tests. It writes tests that FAIL now,
for the right reason, based on documented expectations, and says UNKNOWN when it has no source.

- Two modes: `audit` (code exists) and `spec` (tests first, no code yet).
- New phases: `existing` (do existing tests really check edge cases, or only the happy path?) and
  `expect` (the correct behavior comes from a project doc with a verified quote, or a web page, never from
  the model's memory).
- Verdicts: MATCH / GAP / UNKNOWN (audit), NEW / UNKNOWN (spec). UNKNOWN rows get a question for the user and no test.
- Red/green proof: the script runs the new tests with JUnit output. GAP/NEW tests must FAIL with an assertion
  (not an error, not a wrong-reason failure like a missing class). Every other new test must PASS.
- A test must assert the status codes of the EXPECTED behavior (a number in the test title does not count).
- Decision table: new `Snippet` column (verbatim code, checked near the cited line); every `app/` line cited in
  the logic map needs a decision row or a NO-BRANCH line.
- `scan-tests` command labels existing tests: `success-only`, `checks-more-than-success`, `no-assert`.
- Web sources: allowlisted hosts (`LLTT_WEB_ALLOW` to extend), `--web no` for agents without web tools.
- Removed the todo/pending "recommended" tests and `VERDICT`/`RECOMMENDED` fields from 0.2.
- 64 unit tests including cheating agents.

## 0.2.0: script-enforced workflow
State machine (`init/next/gate/finish`), HMAC-stamped probes, signed state, hash-checked skill files.

## 0.1.0: first draft
Prose-only workflow with a static gate script.
