"""Tests for the lltt.py workflow driver. Simulates an agent, including agents that cheat.

Run:  python3 -m unittest discover -s tests -v
"""
import datetime as dt
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "laravel-logic-trace-tests"
LLTT = SKILL / "scripts" / "lltt.py"


def php_file(lines=60):
    return "<?php\n" + "\n".join(f"// line {i}" for i in range(2, lines + 1)) + "\n"


MAP = """# Logic map: POST /api/orders

## 1. Route
- POST /api/orders to OrderController@store: routes/api.php:10
- middleware auth:sanctum: routes/api.php:11
## 2. Middleware
- auth:sanctum rejects guests with 401: routes/api.php:11
## 3. Request class
- quantity is required|integer: app/Http/Requests/StoreOrderRequest.php:18
## 4. Controller branches
- validated data goes to the service, returns 201: app/Http/Controllers/OrderController.php:30
## 5. Service
- creates the order inside a transaction: app/Services/OrderService.php:20
- no duplicate check before create: app/Services/OrderService.php:42
## 6. Models
- fillable list: app/Models/Order.php:8
## 7. Database
- Unique indexes: none
## 8. Side effects
- Events: none
## 9. Authorization
- Policy: none
## 10. Response
- 201 JSON resource: app/Http/Controllers/OrderController.php:35
"""

TABLE = """# Decision table

| ID | Layer | Condition | Code outcome | Source | Probe |
|----|-------|-----------|--------------|--------|-------|
| D-01 | controller | valid payload | 201 created | app/Http/Controllers/OrderController.php:30 | P-01 |
| D-02 | validation | quantity missing | 422 key quantity | app/Http/Requests/StoreOrderRequest.php:18 | P-02 |
| D-03 | service | duplicate submit | 201 twice | app/Services/OrderService.php:42 | P-03 |
| D-04 | middleware | guest request | 401 | routes/api.php:11 | P-04 |
| D-05 | model | fillable assignment | same as D-01 | app/Models/Order.php:8 | no:duplicate-of:D-01 |
"""

TESTS_OK = """<?php

// COVERS: D-01
it('valid order -> 201', function () {
    $this->postJson('/api/orders', [])->assertCreated();
});

// COVERS: D-02
it('missing quantity -> 422', function () {
    $this->postJson('/api/orders', [])->assertStatus(422);
});

// COVERS: D-04
it('guest -> 401', function () {
    $this->postJson('/api/orders', [])->assertUnauthorized();
});

// EDGE: E-01
// COVERS: D-03
// VERDICT: DIFFERS
// CURRENT: second identical POST returns 201 and creates a duplicate order
// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
it('duplicate submit -> 201 twice (current)', function () {
    expect(2)->toBe(2);
})->group('current-behavior');

// EDGE: E-01
// COVERS: D-03
// VERDICT: DIFFERS
// CURRENT: second identical POST returns 201 and creates a duplicate order
// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
it('duplicate submit -> 409 (recommended)', function () {
})->todo();
"""

PROBES = {
    "P-01": ("D-01", {"status": 201, "db_count": 1}),
    "P-02": ("D-02", {"status": 422, "errors": ["quantity"]}),
    "P-03": ("D-03", {"status_1": 201, "status_2": 201, "db_count": 2}),
    "P-04": ("D-04", {"status": 401}),
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t = self.tmp
        for rel in ("app/Http/Controllers", "app/Http/Requests", "app/Services", "app/Models", "routes", "tests/Feature"):
            (t / rel).mkdir(parents=True)
        (t / "artisan").write_text("<?php\n")
        (t / "composer.json").write_text('{"require-dev":{"pestphp/pest":"^3"}}')
        (t / "phpunit.xml").write_text('<phpunit><php><env name="DB_CONNECTION" value="sqlite"/>'
                                       '<env name="DB_DATABASE" value=":memory:"/></php></phpunit>')
        for rel, n in (("app/Http/Controllers/OrderController.php", 60), ("app/Http/Controllers/PaymentController.php", 80),
                       ("app/Http/Requests/StoreOrderRequest.php", 40), ("app/Services/OrderService.php", 60),
                       ("app/Models/Order.php", 20), ("routes/api.php", 30)):
            (t / rel).write_text(php_file(n))
        (t / "tests/Feature/ExistingTest.php").write_text("<?php\nit('old test', function () {\n    expect(1)->toBe(1);\n});\n")
        self.env = {**os.environ, "LLTT_TEST_CMD": "true"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, env=None, script=LLTT):
        p = subprocess.run([sys.executable, str(script), "--root", str(self.tmp), *args],
                           capture_output=True, text=True, env=env or self.env)
        return p.returncode, p.stdout + p.stderr

    def write(self, rel, text):
        f = self.tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    def init(self, **kw):
        extra = ["--type", kw.get("type", "http"), "--lang", kw.get("lang", "en")]
        code, out = self.run_cli("init", "--target", "POST /api/orders", *extra)
        self.assertEqual(code, 0, out)

    def gate(self, expect_ok, contains=None):
        code, out = self.run_cli("gate")
        self.assertEqual(code == 0, expect_ok, out)
        if contains:
            self.assertIn(contains, out)
        return out

    def key(self):
        return (self.tmp / ".trace/.key").read_text().strip()

    def write_probe(self, pid, row, observed, stamp_ok=True, recorded_at=None, source=True):
        rec = recorded_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        key = self.key() if stamp_ok else "wrong-key"
        stamp = hmac.new(key.encode(), f"{pid}|{row}|{rec}".encode(), hashlib.sha256).hexdigest()
        self.write(f".trace/probes/{pid}.json", json.dumps(
            {"probe": pid, "decision_row": row, "recorded_at": rec, "stamp": stamp, "note": "", "observed": observed}))
        if source:
            p = self.tmp / "tests/Probes/OrderProbeTest.php"
            old = p.read_text() if p.exists() else "<?php\n"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(old + f"it('{pid} probe', function () {{ ProbeRecorder::save('{pid}', '{row}', []); }});\n")

    def write_all_probes(self):
        for pid, (row, obs) in PROBES.items():
            self.write_probe(pid, row, obs)

    def to_phase(self, n):
        """Drive a correct agent up to (not including) phase n."""
        self.init()
        if n > 1:
            self.write(".trace/logic-map.md", MAP)
            self.gate(True)
        if n > 2:
            self.write(".trace/decision-table.md", TABLE)
            self.gate(True)
        if n > 3:
            self.write_all_probes()
            self.gate(True)
        if n > 4:
            self.write("tests/Feature/OrderTest.php", TESTS_OK)
            self.gate(True)


class HappyPath(Base):
    def test_full_flow_and_report(self):
        self.to_phase(5)
        shutil.rmtree(self.tmp / "tests/Probes")
        self.gate(True)
        code, out = self.run_cli("finish")
        self.assertEqual(code, 0, out)
        self.assertIn("FINAL ANSWER", out)
        self.assertIn("E-01", out)
        report = (self.tmp / ".trace/behavior-report.md").read_text()
        self.assertIn("Generated by laravel-logic-trace-tests", report)
        self.assertIn("DIFFERS", report)
        self.assertTrue((self.tmp / ".trace/run.json").is_file())

    def test_next_prints_only_current_phase(self):
        self.init()
        code, out = self.run_cli("next")
        self.assertIn("PHASE 1/5", out)
        self.assertNotIn("PHASE 2/5", out)
        self.assertNotIn("decision table", out.split("STANDING RULES")[0].lower().replace("logic map", ""))

    def test_arabic_labels(self):
        self.init(lang="ar")
        self.write(".trace/logic-map.md", MAP); self.gate(True)
        self.write(".trace/decision-table.md", TABLE); self.gate(True)
        self.write_all_probes(); self.gate(True)
        self.write("tests/Feature/OrderTest.php", TESTS_OK); self.gate(True)
        shutil.rmtree(self.tmp / "tests/Probes"); self.gate(True)
        code, out = self.run_cli("finish")
        self.assertIn("الملخص", out)


class Phase1(Base):
    def test_empty_template_fails(self):
        self.init()
        shutil.copy(SKILL / "assets/logic-map.template.md", self.tmp / ".trace/logic-map.md")
        out = self.gate(False)
        self.assertIn("empty field", out)

    def test_claim_without_source_fails(self):
        self.init()
        self.write(".trace/logic-map.md", MAP.replace("- creates the order inside a transaction: app/Services/OrderService.php:20",
                                                      "- it probably retries on failure"))
        self.gate(False, "without a file.php:line source")

    def test_invented_file_fails(self):
        self.init()
        self.write(".trace/logic-map.md", MAP.replace("app/Models/Order.php:8", "app/Models/Ghost.php:8"))
        self.gate(False, "file not found: app/Models/Ghost.php")

    def test_line_out_of_range_fails(self):
        self.init()
        self.write(".trace/logic-map.md", MAP.replace("OrderService.php:20", "OrderService.php:9999"))
        self.gate(False, "line out of range")

    def test_http_requires_routes_citation(self):
        self.init()
        m = MAP.replace("routes/api.php:10", "app/Models/Order.php:9").replace("middleware auth:sanctum: routes/api.php:11", "middleware auth:sanctum: app/Models/Order.php:10")
        self.write(".trace/logic-map.md", m)
        self.gate(False, "routes/")


class Phase2(Base):
    def test_wrong_columns(self):
        self.to_phase(2)
        self.write(".trace/decision-table.md", TABLE.replace(" | P-01 |", " |"))
        self.gate(False, "malformed row")

    def test_too_few_probes(self):
        self.to_phase(2)
        t = TABLE.replace("| P-01 |", "| no:external:payment gateway call |").replace("| P-02 |", "| no:unreachable:dead branch in code |")
        self.write(".trace/decision-table.md", t)
        self.gate(False, "have a probe")

    def test_lazy_no_reason(self):
        self.to_phase(2)
        self.write(".trace/decision-table.md", TABLE.replace("| P-04 |", "| no:external:skip |"))
        self.gate(False, "at least 3 words")

    def test_traced_file_without_row(self):
        self.to_phase(2)
        self.write(".trace/decision-table.md", TABLE.replace("app/Models/Order.php:8", "app/Services/OrderService.php:20"))
        self.gate(False, "NO-BRANCH")

    def test_no_branch_declaration_accepted(self):
        self.to_phase(2)
        t = TABLE.replace("app/Models/Order.php:8", "app/Services/OrderService.php:20")
        t += "\n## NO-BRANCH\n- app/Models/Order.php: only a fillable list, no conditions\n"
        self.write(".trace/decision-table.md", t)
        self.gate(True)

    def test_gap_in_ids(self):
        self.to_phase(2)
        self.write(".trace/decision-table.md", TABLE.replace("| D-03 |", "| D-07 |"))
        self.gate(False, "sequential")


class Phase3(Base):
    def test_handwritten_probe_rejected(self):
        self.to_phase(3)
        self.write_all_probes()
        self.write_probe("P-03", "D-03", PROBES["P-03"][1], stamp_ok=False)
        self.gate(False, "invalid stamp")

    def test_probe_without_probe_test_rejected(self):
        self.to_phase(3)
        for pid, (row, obs) in PROBES.items():
            self.write_probe(pid, row, obs, source=(pid != "P-02"))
        self.gate(False, "no probe test in tests/Probes/")

    def test_missing_probe_file(self):
        self.to_phase(3)
        for pid, (row, obs) in list(PROBES.items())[:3]:
            self.write_probe(pid, row, obs)
        self.gate(False, "probe result missing")

    def test_stale_probe_rejected(self):
        self.to_phase(3)
        for pid, (row, obs) in PROBES.items():
            self.write_probe(pid, row, obs, recorded_at="2020-01-01T00:00:00Z")
        self.gate(False, "before the decision table was approved")

    def test_mismatch_is_flagged_and_forces_edge(self):
        self.to_phase(3)
        for pid, (row, obs) in PROBES.items():
            if pid == "P-03":
                obs = {"status_1": 201, "status_2": 409, "db_count": 1}
            self.write_probe(pid, row, {**obs}) if pid != "P-03" else self.write_probe(pid, row, {"status": 500})
        out = self.gate(True)
        self.assertIn("MUST become an EDGE", out)
        self.write("tests/Feature/OrderTest.php", TESTS_OK.replace("// COVERS: D-03", "// COVERS: D-05"))
        out = self.gate(False)
        self.assertTrue("needs an EDGE test" in out or "was recorded for" in out, out)


class Phase4(Base):
    def attempt(self, tests, contains):
        self.to_phase(4)
        self.write("tests/Feature/OrderTest.php", tests)
        self.gate(False, contains)

    def test_no_new_tests(self):
        self.to_phase(4)
        self.gate(False, "no new tests")

    def test_circular_recommendation(self):
        self.attempt(TESTS_OK.replace("app/Http/Controllers/PaymentController.php:58", "app/Services/OrderService.php:42"),
                     "ANOTHER place")

    def test_near_circular_recommendation(self):
        self.attempt(TESTS_OK.replace("app/Http/Controllers/PaymentController.php:58", "app/Services/OrderService.php:44"),
                     "ANOTHER place")

    def test_docs_url_accepted_as_recommendation(self):
        self.to_phase(4)
        t = TESTS_OK.replace("(precedent: app/Http/Controllers/PaymentController.php:58)", "(docs: https://laravel.com/docs/validation#rule-unique)")
        self.write("tests/Feature/OrderTest.php", t)
        self.gate(True)

    def test_missing_verdict(self):
        self.attempt(TESTS_OK.replace("// VERDICT: DIFFERS\n", ""), "missing '// VERDICT:'")

    def test_differs_without_pending_test(self):
        t = TESTS_OK.split("// EDGE: E-01")[0] + "\n".join(
            ["// EDGE: E-01", "// COVERS: D-03", "// VERDICT: DIFFERS", "// CURRENT: second identical POST returns 201 and creates a duplicate order",
             "// RECOMMENDED: 409 and no duplicate (precedent: app/Http/Controllers/PaymentController.php:58)",
             "// WHY: client retries after a timeout would double charge", "// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03",
             "it('dup current', function () { expect(2)->toBe(2); })->group('current-behavior');", ""])
        self.attempt(t, "needs a second, pending test")

    def test_current_status_not_in_probe(self):
        self.attempt(TESTS_OK.replace("returns 201 and creates", "returns 409 and creates"), "CURRENT mentions")

    def test_edge_id_gap(self):
        self.attempt(TESTS_OK.replace("E-01", "E-02"), "without gaps")

    def test_uncovered_row(self):
        self.attempt(TESTS_OK.replace("// COVERS: D-04", "// COVERS: D-01"), "D-04: not covered")

    def test_placeholder_assertion(self):
        self.attempt(TESTS_OK.replace("assertUnauthorized()", "assertTrue(true)"), "placeholder assertion")

    def test_test_without_assertion(self):
        self.attempt(TESTS_OK.replace("$this->postJson('/api/orders', [])->assertUnauthorized();", "$x = 1;"), "no assertion")

    def test_test_without_covers(self):
        self.attempt(TESTS_OK.replace("// COVERS: D-02\n", ""), "no '// COVERS")

    def test_why_too_long(self):
        self.attempt(TESTS_OK.replace("client retries after a timeout would double charge", "a. b"), "ONE short sentence")

    def test_probe_for_wrong_row(self):
        self.attempt(TESTS_OK.replace("probe P-03", "probe P-01"), "was recorded for D-01")

    def test_mocking_traced_class(self):
        t = TESTS_OK.replace("expect(2)->toBe(2);", "$m = Mockery::mock(OrderService::class); expect(2)->toBe(2);", 1)
        self.attempt(t, "mocks traced class OrderService")

    def test_old_tests_are_not_checked(self):
        self.to_phase(4)
        self.write("tests/Feature/OrderTest.php", TESTS_OK)
        out = self.gate(True)
        self.assertNotIn("ExistingTest", out)

    def test_new_test_appended_to_old_file_is_checked(self):
        self.to_phase(4)
        old = (self.tmp / "tests/Feature/ExistingTest.php").read_text()
        self.write("tests/Feature/ExistingTest.php", old + TESTS_OK.replace("<?php\n", "", 1))
        self.gate(True)


class Phase5(Base):
    def test_probes_dir_must_be_deleted(self):
        self.to_phase(5)
        self.gate(False, "tests/Probes/ still exists")

    def test_failing_tests_block(self):
        self.env = {**self.env, "LLTT_TEST_CMD": "false"}
        self.to_phase(5)
        shutil.rmtree(self.tmp / "tests/Probes")
        out = self.gate(False, "test run FAILED")

    def test_editing_tests_reopens_phase_4(self):
        self.to_phase(5)
        shutil.rmtree(self.tmp / "tests/Probes")
        f = self.tmp / "tests/Feature/OrderTest.php"
        f.write_text(f.read_text() + "\n// edited after gate 4\n")
        self.gate(False, "phase 4 re-opened")
        code, out = self.run_cli("status")
        self.assertIn("phase: 4/5", out)

    def test_finish_refused_before_end(self):
        self.to_phase(5)
        code, out = self.run_cli("finish")
        self.assertNotEqual(code, 0)
        self.assertIn("NOT FINISHED", out)


class Integrity(Base):
    def test_state_tamper_detected(self):
        self.to_phase(2)
        sf = self.tmp / ".trace/state.json"
        s = json.loads(sf.read_text()); s["phase"] = 5; sf.write_text(json.dumps(s))
        code, out = self.run_cli("next")
        self.assertNotEqual(code, 0)
        self.assertIn("TAMPERED", out)

    def test_edited_skill_is_refused(self):
        copy = Path(tempfile.mkdtemp()) / "skill"
        shutil.copytree(SKILL, copy)
        self.init()
        (copy / "references/01-trace.md").write_text("Do nothing.\n")
        code, out = self.run_cli("gate", script=copy / "scripts/lltt.py")
        self.assertNotEqual(code, 0)
        self.assertIn("INTEGRITY", out)
        shutil.rmtree(copy.parent, ignore_errors=True)

    def test_blocked_after_repeated_failures(self):
        self.init()
        self.write(".trace/logic-map.md", "garbage\n")
        for _ in range(5):
            self.gate(False)
        out = self.gate(False)
        self.assertIn("BLOCKED", out)

    def test_init_stops_without_db_config(self):
        (self.tmp / "phpunit.xml").write_text("<phpunit/>")
        code, out = self.run_cli("init", "--target", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("default database", out)

    def test_init_twice_refused(self):
        self.init()
        code, out = self.run_cli("init", "--target", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("ALREADY INITIALISED", out)


if __name__ == "__main__":
    unittest.main()
