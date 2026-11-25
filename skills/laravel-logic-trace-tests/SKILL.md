---
name: laravel-logic-trace-tests
description: Writes real FAILING tests for Laravel/PHP back-end features from documented expectations, under a script-enforced workflow. Traces the real flow of an endpoint, probes edge cases, checks whether existing tests only cover the happy path, looks up the correct behavior in project docs and the web (Laravel docs, OWASP), and writes tests that fail now for the right reason (red proof run by the script). Also works test-first when the code does not exist yet. Says "unknown" instead of guessing. Use whenever the user asks to write, generate, add, review or improve tests for Laravel code (controllers, endpoints, FormRequests, services, models, jobs, policies), asks what edge cases a feature has, wants tests before writing code (TDD/red phase), or says "cover this with tests".
---

# Laravel logic-trace tests (script-driven)

A script owns the workflow and checks your work. Do not improvise a workflow from memory.

1. Pick ONE endpoint, job, command or class. If the request is broader, ask which one.
2. From the Laravel project root run (SKILL_DIR = the folder containing this file):
   `python3 SKILL_DIR/scripts/lltt.py init --target "<the one target>" --mode audit --web yes --lang ar`
   - `--mode audit` if the code exists, `--mode spec` if it is not written yet (tests first).
   - `--web yes` ONLY if you have a web search or fetch tool, otherwise `--web no` and tell the user
     research was limited to project docs.
   - `--lang` is the user's language (ar or en). `--type` is http (default), job or command.
3. Run `python3 SKILL_DIR/scripts/lltt.py next` and do exactly what it prints. Nothing else.
4. When done, run the `gate` command it prints. FAIL: fix only the listed items, run gate again.
   PASS: run `next`.
5. After the last gate run `finish` and print the FINAL ANSWER block verbatim.

Never edit app code, files inside the skill folder, `.trace/state.json` or `.trace/.key`.
Never claim tests pass or fail unless the script printed it. Not knowing is a valid result: write UNKNOWN.
If the script prints BLOCKED, stop and show the user the failures.
