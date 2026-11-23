---
name: laravel-logic-trace-tests
description: Writes Laravel/PHP back-end tests from evidence, not guesses, under a script-enforced workflow. Traces the real request flow (route, middleware, FormRequest, controller, service, model, events, jobs, policy), finds edge cases by reading the code and running probes, then writes tests that pin CURRENT behavior and state the RECOMMENDED behavior with a one-line reason. Use whenever the user asks to write, generate, add, review or improve tests for Laravel code (controllers, API endpoints, FormRequests, services, actions, models, jobs, policies), asks "what edge cases does this have", "how does this endpoint really behave", or just says "cover this with tests", even if they do not mention Pest, PHPUnit or edge cases.
---

# Laravel logic-trace tests (script-driven)

A script owns the workflow and checks your work. Do not improvise a workflow from memory.

1. Pick ONE endpoint, job, command or class. If the request is broader, ask which one.
2. From the Laravel project root run (SKILL_DIR = the folder containing this file):
   `python3 SKILL_DIR/scripts/lltt.py init --target "<the one target>" --type http --lang ar`
   (`--type` is http, job or command; `--lang` is the user's language: ar or en)
3. Run `python3 SKILL_DIR/scripts/lltt.py next` and do exactly what it prints. Nothing else.
4. When done, run the `gate` command it prints. FAIL: fix only the listed items, run gate again.
   PASS: run `next`.
5. After the last gate run `finish` and print the FINAL ANSWER block verbatim.

Never edit app code, files inside the skill folder, `.trace/state.json` or `.trace/.key`.
Never claim tests pass unless the script printed it. If the script prints BLOCKED, stop and show
the user the failures.
