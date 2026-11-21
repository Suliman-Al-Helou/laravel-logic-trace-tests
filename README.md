# laravel-logic-trace-tests

An [Agent Skill](https://github.com/anthropics/skills) for Laravel/PHP back-end tests that are built
from **evidence**, not guesses.

It makes the agent trace the real request flow (route → middleware → FormRequest → controller →
service → model → events/jobs → policy), find edge cases by reading the code and running probes,
and then write tests that pin the **current** behavior and state the **recommended** behavior with
a one-line reason.

## What you get

For each edge case, a comment block above the test (checked by a gate script):

```php
// EDGE: E-03
// COVERS: D-07
// CURRENT: second identical POST returns 201 and creates a duplicate order
// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
```

Plus `.trace/logic-map.md`, `.trace/decision-table.md`, `.trace/probes/*.json` and
`.trace/behavior-report.md`.

## Rules the skill enforces

1. No edge case without a `file.php:line` the agent opened and a probe result it actually ran.
2. `RECOMMENDED` comes from a project precedent or Laravel docs, otherwise `none established`.
3. Application code is never modified. Only `tests/` and `.trace/`.
4. Probes run through the test runner only (test DB), never against the default environment.
5. A gate script fails the run on incomplete edge blocks, missing evidence, assertion-less tests,
   and uncovered decision-table rows.

Designed to stay usable with small/cheap models: short `SKILL.md`, one phase per reference file,
mechanical checks instead of prose rules.

## Install

Replace ` Suliman-Al-Helou` with the account that hosts this repo.

**Gemini CLI**
```bash
gemini skills install https://github.com/ Suliman-Al-Helou/laravel-logic-trace-tests.git \
  --path skills/laravel-logic-trace-tests --scope workspace --consent
```

**Any agent that supports `npx skills`**
```bash
npx skills add  Suliman-Al-Helou/laravel-logic-trace-tests --skill laravel-logic-trace-tests
```

**Claude Code (manual)**
```bash
git clone --depth 1 https://github.com/ Suliman-Al-Helou/laravel-logic-trace-tests.git /tmp/lltt
mkdir -p .claude/skills && cp -r /tmp/lltt/skills/laravel-logic-trace-tests .claude/skills/
```

**Laravel Boost**
```bash
mkdir -p .ai/skills && cp -r /tmp/lltt/skills/laravel-logic-trace-tests .ai/skills/
php artisan boost:update
```

Copy the whole folder: the scripts and references live beside `SKILL.md`.

## Use

Run from the Laravel project root and name ONE feature or endpoint:

> Write tests for `POST /api/orders`. Use the laravel-logic-trace-tests skill.

## Requirements

- Laravel project with Pest or PHPUnit and a configured test database
- `bash`, `php`, `python3` on PATH

## What the scripts do (read before installing)

- `scripts/detect_env.sh` — read-only: runs `php artisan --version`, greps `phpunit.xml` / `composer.json`,
  counts test files, writes `.trace/env.txt`.
- `scripts/verify_tests.py` — static checks over `tests/` and `.trace/`. With `--run` it executes
  `php artisan test`.
- The skill declares no `allowed-tools`.

## Known limitations (v0.1.0)

- Not yet evaluated on multiple models; compliance of cheap models is unmeasured.
- The gate is regex-based and can miss unusual test layouts (data providers, dynamic tests).
- The gate does not yet reject a `RECOMMENDED` precedent that points at the same line as `EVIDENCE`
  (circular evidence).
- The gate does not detect gaps in edge IDs (an edge dropped without being reported as UNVERIFIED).
- Speed: probes and full-suite runs can make a run take several minutes.

## Roadmap

- Circular-evidence check in the gate
- Edge-ID continuity check
- Batched probes and focused test runs
- Evals with with-skill vs without-skill runs on a small model

## License

MIT
