# laravel-logic-trace-tests

An [Agent Skill](https://github.com/anthropics/skills) that writes **real failing tests** for Laravel/PHP
features, based on **documented expectations** (project docs, official docs, OWASP), under a workflow
enforced by a script instead of prose.

Two goals:

1. **Code exists (audit mode).** Trace the feature, probe it, check whether existing tests really cover edge
   cases or only the happy path, find the documented correct behavior, and write tests that fail now where the
   code differs from it.
2. **Code does not exist yet (spec mode).** Write the tests first from the ticket and from documented
   guidance. Every test fails now (red). Then the developer builds until green.

If it cannot find a source for what is correct, it says **UNKNOWN** and asks you. It does not guess.

## Result you get

```
Summary: POST /api/orders (audit)
- gaps (tests that must FAIL now): 1
  * E-01 [D-03]: second identical POST returns 201 ... -> 409 and no second order  (src: docs/ticket.md:10)
- behaviors confirmed by a source: 2
- UNKNOWN (no source found, needs your decision): 1
- Questions for you:
  ? D-04: Should a guest get 401 or a redirect here?
- Existing tests: STRONG 1, WEAK 1, NONE 3
- Red/green proof: 1 fail as intended, 2 pass
- Web research: YES, 1 source(s), not verified by the script
```

## How it is enforced

The agent runs `lltt.py next` (shows only the current phase) and `lltt.py gate` (must pass to advance).

| Phase (audit) | What the gate checks |
|---|---|
| trace | every statement has a `file.php:line` that exists |
| decide | snippets copied from the code are found near the cited line; every traced `app/` line has a row |
| probe | results stamped by `ProbeRecorder` (HMAC), backed by a real probe test |
| existing | cited tests exist; STRONG is rejected for tests that only assert a success status |
| expect | doc quotes are found in the doc; web hosts are allowlisted; MATCH must equal the probe's observed status; UNKNOWN needs a question |
| tests | a test asserts the EXPECTED status; SOURCE and EXPECTED equal expectations.md; no todo/skip; no mocking traced classes |
| run | the script runs the tests: gaps must FAIL with an assertion, the rest must PASS |

Spec mode runs only `expect`, `tests`, `run`.

## Install

Replace `YOUR_GITHUB_USER` with the account hosting this repo.

**Gemini CLI**
```bash
gemini skills install https://github.com/YOUR_GITHUB_USER/laravel-logic-trace-tests.git \
  --path skills/laravel-logic-trace-tests --scope workspace --consent
```

**`npx skills`**
```bash
npx skills add YOUR_GITHUB_USER/laravel-logic-trace-tests --skill laravel-logic-trace-tests
```

**Claude Code (manual)**
```bash
git clone --depth 1 https://github.com/YOUR_GITHUB_USER/laravel-logic-trace-tests.git /tmp/lltt
mkdir -p .claude/skills && cp -r /tmp/lltt/skills/laravel-logic-trace-tests .claude/skills/
```

Copy the whole folder. Do not edit files inside it: the script refuses to run if they changed.

## Use

From the Laravel project root, name ONE feature:

> Use laravel-logic-trace-tests on `POST /api/admin/instructors` (code exists, audit mode, web research on).

> Use laravel-logic-trace-tests in spec mode for the ticket docs/tickets/02-courses.md (no code yet).

Manual driving:
```bash
python3 skills/laravel-logic-trace-tests/scripts/lltt.py init --target "POST /api/orders" --mode audit --web yes --lang en
python3 skills/laravel-logic-trace-tests/scripts/lltt.py next
python3 skills/laravel-logic-trace-tests/scripts/lltt.py gate
python3 skills/laravel-logic-trace-tests/scripts/lltt.py status
python3 skills/laravel-logic-trace-tests/scripts/lltt.py finish
```

Docker / Sail: `export LLTT_TEST_CMD='sail artisan test'` before `init`. The runner must accept
`--log-junit=<file>`. Extra allowed web hosts: `export LLTT_WEB_ALLOW=example.com,docs.vendor.io`.

## Requirements

Laravel project with Pest or PHPUnit and a configured test database, `python3` 3.8+, `php` on PATH (or
`LLTT_TEST_CMD`).

## What it executes

- `init` reads `phpunit.xml`, `composer.json`, runs `php artisan --version`.
- The `run` gate runs your test command on the test files the agent added, nothing else.
- Probes are tests the agent writes under `tests/Probes/`; they run through your runner and DB config.
- The skill declares no `allowed-tools`.

## Honest limitations

- **Web sources are not verified by the script.** It cannot open URLs. It checks the host, requires a verbatim
  quote, and flags web sources in the report. Open them before trusting a GAP.
- **Not tamper-proof.** The checks stop skipping, invention and self-grading. An agent with shell access that
  deliberately rewrites `lltt.py` and re-signs state can still cheat.
- Not evaluated across models yet. Compliance of small models is a hypothesis.
- Developed without a PHP runtime: the 64 Python tests use a fake JUnit runner. The PHP/Pest snippets and
  `ProbeRecorder.php` are not run in CI, and `php artisan test --log-junit=...` should be checked on your setup.
- Test parsing is regex-based (Pest `it()/test()`, PHPUnit methods). Data providers and generated tests may be
  mis-detected.
- Whether a doc quote really supports the Expected text is the agent's judgment; the script checks the quote exists.
- Mutation testing is not included yet.
- Linux/macOS tested. Windows paths untested.

## Develop

```bash
python3 -m unittest discover -s tests -v
python3 skills/laravel-logic-trace-tests/scripts/lltt.py make-manifest   # after editing any skill file
```

## License

MIT
