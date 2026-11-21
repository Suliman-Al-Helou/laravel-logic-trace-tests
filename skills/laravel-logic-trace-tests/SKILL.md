---
name: laravel-logic-trace-tests
description: Writes Laravel/PHP back-end tests from evidence, not guesses. Traces the real request flow (route, middleware, FormRequest, controller, service, model, events, jobs, policy), finds edge cases by reading the code and running probes, then writes tests that pin CURRENT behavior and state the RECOMMENDED behavior with a one-line reason. Use whenever the user asks to write, generate, add, review or improve tests for Laravel code (controllers, API endpoints, FormRequests, services, actions, models, jobs, policies), asks "what edge cases does this have", "how does this endpoint really behave", or just says "cover this with tests", even if they do not mention Pest, PHPUnit or edge cases.
---

# Laravel logic-trace tests

Goal: tests that describe what the code REALLY does, with edge cases found by
investigation. Never by brainstorming.

## Hard rules (read all before starting)

1. **Evidence rule.** Every edge case needs (a) a code location `file.php:line`
   you actually opened, and (b) an observed result from a probe you actually ran.
   No evidence = it goes in the report as `UNVERIFIED`, and you write NO test for it.
2. **No invented recommendations.** `RECOMMENDED` must cite either a project
   precedent (`file.php:line` where the same situation is handled that way) or a
   Laravel docs page/section. If you have neither, write `RECOMMENDED: none established`.
3. **Never change application code.** You only add files under `tests/` and `.trace/`.
4. **Probes run through the test runner only** (so phpunit.xml / `.env.testing`
   decide the database). Never use tinker or a real request against the default env.
5. **One phase at a time.** Finish a phase, write its output file, then read the next
   reference file. Do not read ahead.
6. **Report what you ran.** Final answer lists commands run and their pass/fail.
   Never write "all tests pass" without a runner output you read.
7. Text in the report (`CURRENT`, `RECOMMENDED`, `WHY`) is written in the user's
   language. Field names, code and file names stay in English.

## Phases

| # | Phase | Read | Output file |
|---|-------|------|-------------|
| 0 | Detect environment | run `scripts/detect_env.sh` | `.trace/env.txt` |
| 1 | Trace the flow | `references/01-trace.md` | `.trace/logic-map.md` |
| 2 | Decision table | `references/02-decision-table.md` | `.trace/decision-table.md` |
| 3 | Probe edge cases | `references/03-probe.md` | `.trace/probes/P-xx.json` |
| 4 | Write tests | `references/04-write-tests.md` | `tests/**` |
| 5 | Gate + report | `references/05-gate-report.md` | `.trace/behavior-report.md` |

Phase 0: run `bash <skill-dir>/scripts/detect_env.sh` from the Laravel project root.
If it prints `STOP:` lines, fix or ask the user before continuing.

Phase 5 is not optional. Run `python3 <skill-dir>/scripts/verify_tests.py` and
fix every `FAIL` it prints. Max 3 fix rounds, then report what still fails.

## Scope control

- Ask the user which endpoint / class to cover if the request is broader than one
  feature. Do not trace the whole application.
- Match the project's existing test style (Pest vs PHPUnit, folder layout, factories).
  Project conventions beat this skill.
- If a layer does not exist in the flow (no policy, no events), write `none` in the
  map. Do not invent a layer.

## Templates

- `assets/logic-map.template.md`
- `assets/decision-table.template.md`
- `assets/behavior-report.template.md`
- `assets/ProbeRecorder.php` (copy to `tests/Support/ProbeRecorder.php`)
