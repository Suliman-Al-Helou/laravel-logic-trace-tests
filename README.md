# laravel-logic-trace-tests

An [Agent Skill](https://github.com/anthropics/skills) that makes an AI agent write Laravel/PHP tests
from **evidence**, under a workflow enforced by a script instead of by prose.

For one endpoint, job, command or class it:

1. traces the real flow (route, middleware, FormRequest, controller, service, model, events, policy),
2. turns every branch into a decision-table row,
3. runs **probes** (real requests against the test DB) to observe what actually happens,
4. writes tests that pin the **current** behavior and record the **recommended** behavior with a
   one-line reason,
5. has the script run the tests and generate the report.

```php
// EDGE: E-03
// COVERS: D-07
// VERDICT: DIFFERS
// CURRENT: second identical POST returns 201 and creates a duplicate order
// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
```

## Why a script owns the workflow

Skills are advisory text, and weaker models skip steps or grade their own homework. Here the agent
runs `lltt.py next` (one phase at a time) and `lltt.py gate` (must pass to advance).

| Weakness of prose-only skills | What this skill does |
|---|---|
| Steps get skipped | `next` shows only the current phase; `gate` blocks advancing |
| Invented facts | every line needs a `file.php:line` that exists; probes must be stamped by a real run |
| Circular "recommended" behavior | a precedent that is the code under test is rejected |
| Hidden surprises | a probe that contradicts the code reading forces an EDGE test; edge ids cannot have gaps |
| "All tests pass" claims | the script runs the tests and writes `.trace/run.json` |
| Padded or fabricated reports | `finish` generates the report and the final answer |
| Editing the checker | skill files are hash-checked, `state.json` is signed |
| Infinite fix loops | 5 failed gates on a phase = `BLOCKED`, stop and report |

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

> Write tests for `POST /api/orders` with the laravel-logic-trace-tests skill.

Docker / Sail users set the runner first: `export LLTT_TEST_CMD='sail artisan test'`.

You can also drive it by hand:

```bash
python3 skills/laravel-logic-trace-tests/scripts/lltt.py init --target "POST /api/orders" --type http --lang en
python3 skills/laravel-logic-trace-tests/scripts/lltt.py next
python3 skills/laravel-logic-trace-tests/scripts/lltt.py gate
python3 skills/laravel-logic-trace-tests/scripts/lltt.py status    # phase and time per phase
python3 skills/laravel-logic-trace-tests/scripts/lltt.py finish
```

Outputs are in `.trace/`: `logic-map.md`, `decision-table.md`, `probes/`, `run.json`,
`behavior-report.md`, `run-summary.json`.

## Requirements

Laravel project with Pest or PHPUnit and a configured test database (`phpunit.xml` or `.env.testing`),
`python3` 3.8+, and `php` on PATH (or `LLTT_TEST_CMD`).

## What it executes

- `lltt.py init` reads `phpunit.xml`, `composer.json` and runs `php artisan --version`.
- `lltt.py gate` (phase 5) runs your test command on the test files the agent added. Nothing else.
- Probes are tests the agent writes under `tests/Probes/`; they run through your test runner and DB config.
- The skill declares no `allowed-tools`.

## Honest limitations

- **Not tamper-proof.** The checks stop skipping, hallucination and lazy self-grading. An agent with
  shell access that deliberately rewrites `lltt.py` and re-signs state can still cheat. Review the
  `.trace/` folder if the stakes are high.
- Not yet evaluated across models. Compliance of small models is the hypothesis, not a result.
- Developed without a PHP runtime in the test harness: Python checks are covered by 45 unit tests,
  the PHP/Pest snippets in the references and `ProbeRecorder.php` are not run in CI.
- Test parsing is regex-based (Pest `it()/test()` and PHPUnit methods); unusual layouts such as data
  providers or generated tests may be mis-detected.
- The mock check matches class base names found in the logic map.
- Linux/macOS tested. Windows paths are untested.
- Time: probes plus per-file test runs take minutes. Per-phase timing is in `status` and the report.

## Develop

```bash
python3 -m unittest discover -s tests -v
python3 skills/laravel-logic-trace-tests/scripts/lltt.py make-manifest   # after editing any skill file
```

## License

MIT
