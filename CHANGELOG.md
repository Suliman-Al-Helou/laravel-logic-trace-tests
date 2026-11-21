# Changelog

## 0.1.0 — first public draft
- Five-phase workflow: detect env, trace flow, decision table, probe, write tests, gate + report.
- `scripts/detect_env.sh` (read-only environment check) and `scripts/verify_tests.py` (static gate).
- Edge cases require code evidence (`file.php:line`) and a recorded probe result.
- Tests pin CURRENT behavior; RECOMMENDED behavior is a pending test with a one-line reason.
- Not yet evaluated across models. See "Known limitations" in the README.
