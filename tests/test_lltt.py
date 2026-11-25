"""Tests for the lltt.py workflow driver (v0.3). Simulates agents, including ones that cheat.

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
FAKE = Path(__file__).resolve().parent / "fake_runner.py"


def php_file(lines=60):
    return "<?php\n" + "\n".join(f"// line {i}" for i in range(2, lines + 1)) + "\n"


DOC = "\n".join(["# Ticket 01", "", "Acceptance criteria", "", "A valid request creates the order and stores it.",
                 "Missing quantity is refused.", "", "", "", "A repeated identical request must be rejected with 409 conflict.",
                 "Done."]) + "\n"

EXISTING_TEST = """<?php

it('creates order', function () {
    $this->postJson('/api/orders', [])->assertCreated();
});

it('validates quantity', function () {
    $this->postJson('/api/orders', [])->assertStatus(422);
});
"""

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

| ID | Layer | Condition | Code outcome | Source | Snippet | Probe |
|----|-------|-----------|--------------|--------|---------|-------|
| D-01 | controller | valid payload | 201 created | app/Http/Controllers/OrderController.php:30 | // line 30 | P-01 |
| D-02 | validation | quantity missing | 422 key quantity | app/Http/Requests/StoreOrderRequest.php:18 | // line 18 | P-02 |
| D-03 | service | duplicate submit | 201 twice | app/Services/OrderService.php:42 | // line 42 | P-03 |
| D-04 | middleware | guest request | 401 | routes/api.php:11 | // line 11 | P-04 |
| D-05 | model | fillable assignment | same as D-01 | app/Models/Order.php:8 | // line 8 | no:duplicate-of:D-01 |

## NO-BRANCH
- app/Http/Controllers/OrderController.php:35: response wrapper only
- app/Services/OrderService.php:20: transaction wrapper only
"""

EXISTING = """# Existing tests

| ID | Existing test | Strength | Reason |
|----|---------------|----------|--------|
| D-01 | tests/Feature/ExistingTest.php:4 | WEAK | only checks the created status |
| D-02 | tests/Feature/ExistingTest.php:8 | STRONG | asserts the 422 validation status |
| D-03 | - | NONE | no test sends the same payload twice |
| D-04 | - | NONE | no test calls as a guest |
| D-05 | - | NONE | fillable is not tested alone |
"""

EXPECT = """# Expectations

| ID | Expected | Type | Source | Quote | Verdict |
|----|----------|------|--------|-------|---------|
| D-01 | 201 and the order is stored | doc | docs/ticket.md:5 | A valid request creates the order and stores it. | MATCH |
| D-02 | 422 with error key quantity | web | https://laravel.com/docs/master/validation | The required rule | MATCH |
| D-03 | 409 and no second order | doc | docs/ticket.md:10 | A repeated identical request must be rejected with 409 conflict. | GAP |
| D-04 | - | unknown | - | - | UNKNOWN |

## QUESTIONS
- D-04: Should a guest get 401 or a redirect here?
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

// EDGE: E-01
// COVERS: D-03
// KIND: GAP
// CURRENT: second identical POST returns 201 and creates a duplicate order
// EXPECTED: 409 and no second order
// WHY: client retries after a timeout would double charge
// EVIDENCE: app/Services/OrderService.php:42 ; probe P-03
// SOURCE: docs/ticket.md:10
it('duplicate submit is rejected with 409', function () {
    $this->postJson('/api/orders', [])->assertConflict();
});
"""

GAP_FAILS = {"duplicate submit is rejected with 409": {"status": "failure", "message": "Expected response status code [409] but received 201."}}

PROBES = {
    "P-01": ("D-01", {"status": 201, "db_count": 1}),
    "P-02": ("D-02", {"status": 422, "errors": ["quantity"]}),
    "P-03": ("D-03", {"status_1": 201, "status_2": 201, "db_count": 2}),
    "P-04": ("D-04", {"status": 401}),
}

SPEC_EXPECT = """# Expectations

| ID | Expected | Type | Source | Quote | Verdict |
|----|----------|------|--------|-------|---------|
| D-01 | 201 and the order is stored | doc | docs/ticket.md:5 | A valid request creates the order and stores it. | NEW |
| D-02 | 409 and no second order | doc | docs/ticket.md:10 | A repeated identical request must be rejected with 409 conflict. | NEW |
| D-03 | - | unknown | - | - | UNKNOWN |

## QUESTIONS
- D-03: What should happen when quantity is zero?
"""

SPEC_TESTS = """<?php

// EDGE: E-01
// COVERS: D-01
// KIND: NEW
// EXPECTED: 201 and the order is stored
// WHY: the ticket requires a valid request to create the order
// SOURCE: docs/ticket.md:5
it('creates the order', function () {
    $this->postJson('/api/orders', [])->assertCreated();
});

// EDGE: E-02
// COVERS: D-02
// KIND: NEW
// EXPECTED: 409 and no second order
// WHY: the ticket rejects a repeated identical request
// SOURCE: docs/ticket.md:10
it('rejects a repeated request', function () {
    $this->postJson('/api/orders', [])->assertConflict();
});
"""

SPEC_FAILS = {
    "creates the order": {"status": "failure", "message": "Expected response status code [201] but received 404."},
    "rejects a repeated request": {"status": "failure", "message": "Expected response status code [409] but received 404."},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t = self.tmp
        for rel in ("app/Http/Controllers", "app/Http/Requests", "app/Services", "app/Models", "routes", "tests/Feature", "docs"):
            (t / rel).mkdir(parents=True)
        (t / "artisan").write_text("<?php\n")
        (t / "composer.json").write_text('{"require-dev":{"pestphp/pest":"^3"}}')
        (t / "phpunit.xml").write_text('<phpunit><php><env name="DB_CONNECTION" value="sqlite"/>'
                                       '<env name="DB_DATABASE" value=":memory:"/></php></phpunit>')
        for rel, n in (("app/Http/Controllers/OrderController.php", 60), ("app/Http/Requests/StoreOrderRequest.php", 40),
                       ("app/Services/OrderService.php", 60), ("app/Models/Order.php", 20), ("routes/api.php", 30)):
            (t / rel).write_text(php_file(n))
        (t / "docs/ticket.md").write_text(DOC)
        (t / "tests/Feature/ExistingTest.php").write_text(EXISTING_TEST)
        self.env = {**os.environ, "LLTT_TEST_CMD": f"{sys.executable} {FAKE}"}

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

    def init(self, mode="audit", web="yes", lang="en", typ="http"):
        code, out = self.run_cli("init", "--target", "POST /api/orders", "--mode", mode, "--web", web, "--lang", lang, "--type", typ)
        self.assertEqual(code, 0, out)

    def gate(self, ok, contains=None):
        code, out = self.run_cli("gate")
        self.assertEqual(code == 0, ok, out)
        if contains:
            self.assertIn(contains, out)
        return out

    def fake(self, results):
        self.write(".fake-results.json", json.dumps(results))

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

    def to_phase(self, name, **initkw):
        """Drive a correct audit agent up to (not including) phase `name`."""
        self.init(**initkw)
        steps = [("trace", ".trace/logic-map.md", MAP), ("decide", ".trace/decision-table.md", TABLE),
                 ("probe", None, None), ("existing", ".trace/existing-tests.md", EXISTING),
                 ("expect", ".trace/expectations.md", EXPECT), ("tests", "tests/Feature/OrderTest.php", TESTS_OK)]
        for step, rel, text in steps:
            if step == name:
                return
            if step == "probe":
                self.write_all_probes()
            else:
                self.write(rel, text)
            self.gate(True)


class HappyPath(Base):
    def test_audit_full_flow_and_report(self):
        self.to_phase("run")
        shutil.rmtree(self.tmp / "tests/Probes")
        self.fake(GAP_FAILS)
        self.gate(True)
        code, out = self.run_cli("finish")
        self.assertEqual(code, 0, out)
        self.assertIn("FINAL ANSWER", out)
        self.assertIn("E-01", out)
        self.assertIn("1 fail as intended, 2 pass", out)
        self.assertIn("D-04", out)
        report = (self.tmp / ".trace/behavior-report.md").read_text()
        self.assertIn("Not hand-written", report)
        self.assertIn("Expected response status code [409]", report)
        run = json.loads((self.tmp / ".trace/run.json").read_text())
        self.assertEqual({t["expected"] for r in run["results"] for t in r["tests"]}, {"FAIL", "PASS"})

    def test_spec_full_flow(self):
        self.init(mode="spec", web="no")
        self.write(".trace/expectations.md", SPEC_EXPECT); self.gate(True)
        self.write("tests/Feature/OrderTest.php", SPEC_TESTS); self.gate(True)
        self.fake(SPEC_FAILS)
        self.gate(True)
        code, out = self.run_cli("finish")
        self.assertEqual(code, 0, out)
        self.assertIn("2 fail as intended, 0 pass", out)
        self.assertIn("What should happen when quantity is zero?", out)
        self.assertIn("NO (project docs only)", out)

    def test_next_shows_only_current_phase(self):
        self.init()
        code, out = self.run_cli("next")
        self.assertIn("PHASE 1/7: TRACE", out)
        self.assertNotIn("PHASE 2/7", out)

    def test_arabic_labels(self):
        self.to_phase("run", lang="ar")
        shutil.rmtree(self.tmp / "tests/Probes")
        self.fake(GAP_FAILS)
        self.gate(True)
        code, out = self.run_cli("finish")
        self.assertIn("الملخص", out)

    def test_scan_tests(self):
        self.init()
        code, out = self.run_cli("scan-tests", "tests/Feature/ExistingTest.php")
        self.assertIn("[success-only]", out)
        self.assertIn("[checks-more-than-success]", out)


class Trace(Base):
    def test_claim_without_source(self):
        self.init()
        self.write(".trace/logic-map.md", MAP.replace("- creates the order inside a transaction: app/Services/OrderService.php:20", "- it probably retries"))
        self.gate(False, "without a file.php:line source")

    def test_invented_file(self):
        self.init()
        self.write(".trace/logic-map.md", MAP.replace("app/Models/Order.php:8", "app/Models/Ghost.php:8"))
        self.gate(False, "file not found")

    def test_http_needs_routes(self):
        self.init()
        m = MAP.replace("routes/api.php:10", "app/Models/Order.php:9").replace("middleware auth:sanctum: routes/api.php:11", "middleware auth:sanctum: app/Models/Order.php:10")
        self.write(".trace/logic-map.md", m)
        self.gate(False, "routes/")


class Decide(Base):
    def test_snippet_not_in_code(self):
        self.to_phase("decide")
        self.write(".trace/decision-table.md", TABLE.replace("// line 30", "return new OrderResource($order)"))
        self.gate(False, "Snippet not found")

    def test_six_columns_rejected(self):
        self.to_phase("decide")
        self.write(".trace/decision-table.md", TABLE.replace("| // line 42 |", "|"))
        self.gate(False, "malformed row")

    def test_map_line_without_row(self):
        self.to_phase("decide")
        self.write(".trace/decision-table.md", TABLE.replace("- app/Services/OrderService.php:20: transaction wrapper only\n", ""))
        self.gate(False, "OrderService.php:20 is in the logic map but no decision row cites it")

    def test_whole_file_no_branch_accepted(self):
        self.to_phase("decide")
        t = TABLE.replace("- app/Services/OrderService.php:20: transaction wrapper only\n",
                          "- app/Services/OrderService.php: thin wrapper without conditions\n")
        self.write(".trace/decision-table.md", t)
        self.gate(True)

    def test_too_few_probes(self):
        self.to_phase("decide")
        t = TABLE.replace("| P-01 |", "| no:external:payment gateway call |").replace("| P-02 |", "| no:unreachable:dead branch in code |")
        self.write(".trace/decision-table.md", t)
        self.gate(False, "have a probe")

    def test_id_gap(self):
        self.to_phase("decide")
        self.write(".trace/decision-table.md", TABLE.replace("| D-03 |", "| D-07 |"))
        self.gate(False, "sequential")


class Probe(Base):
    def test_handwritten_probe(self):
        self.to_phase("probe")
        self.write_all_probes()
        self.write_probe("P-03", "D-03", PROBES["P-03"][1], stamp_ok=False)
        self.gate(False, "invalid stamp")

    def test_probe_without_test_source(self):
        self.to_phase("probe")
        for pid, (row, obs) in PROBES.items():
            self.write_probe(pid, row, obs, source=(pid != "P-02"))
        self.gate(False, "no probe test in tests/Probes/")

    def test_stale_probe(self):
        self.to_phase("probe")
        for pid, (row, obs) in PROBES.items():
            self.write_probe(pid, row, obs, recorded_at="2020-01-01T00:00:00Z")
        self.gate(False, "before the decision table was approved")


class Existing(Base):
    def test_missing_row(self):
        self.to_phase("existing")
        self.write(".trace/existing-tests.md", EXISTING.replace("| D-05 | - | NONE | fillable is not tested alone |\n", ""))
        self.gate(False, "D-05: no entry")

    def test_strong_on_success_only(self):
        self.to_phase("existing")
        self.write(".trace/existing-tests.md", EXISTING.replace("| D-01 | tests/Feature/ExistingTest.php:4 | WEAK", "| D-01 | tests/Feature/ExistingTest.php:4 | STRONG"))
        self.gate(False, "only asserts a success status")

    def test_cited_line_not_a_test(self):
        self.to_phase("existing")
        self.write(".trace/existing-tests.md", EXISTING.replace("ExistingTest.php:8", "ExistingTest.php:99"))
        self.gate(False, "is not inside an existing test")

    def test_none_with_a_test_cell(self):
        self.to_phase("existing")
        self.write(".trace/existing-tests.md", EXISTING.replace("| D-03 | - | NONE", "| D-03 | tests/Feature/ExistingTest.php:4 | NONE"))
        self.gate(False, "NONE must have '-'")


class Expect(Base):
    def attempt(self, text, contains, **kw):
        self.to_phase("expect", **kw)
        self.write(".trace/expectations.md", text)
        self.gate(False, contains)

    def test_missing_probed_row(self):
        self.attempt(EXPECT.replace("| D-04 | - | unknown | - | - | UNKNOWN |\n", ""), "D-04: probed decision row has no expectation")

    def test_quote_not_in_doc(self):
        self.attempt(EXPECT.replace("A valid request creates the order and stores it.", "Orders are always created."), "Quote not found near docs/ticket.md")

    def test_doc_missing(self):
        self.attempt(EXPECT.replace("docs/ticket.md:5", "docs/nothing.md:5"), "doc not found")

    def test_web_disabled(self):
        self.attempt(EXPECT, "web sources are disabled", web="no")

    def test_web_enabled_but_unused(self):
        t = EXPECT.replace("| web | https://laravel.com/docs/master/validation | The required rule |", "| doc | docs/ticket.md:6 | Missing quantity is refused. |")
        self.attempt(t, "no row uses a web source")

    def test_host_not_allowed(self):
        self.attempt(EXPECT.replace("https://laravel.com/docs/master/validation", "https://random-blog.example/x"), "host not in the allowed list")

    def test_match_contradicting_probe(self):
        self.attempt(EXPECT.replace("| D-03 | 409 and no second order | doc | docs/ticket.md:10 | A repeated identical request must be rejected with 409 conflict. | GAP |",
                                    "| D-03 | 409 and no second order | doc | docs/ticket.md:10 | A repeated identical request must be rejected with 409 conflict. | MATCH |"),
                     "marked MATCH")

    def test_unknown_without_question(self):
        self.attempt(EXPECT.replace("- D-04: Should a guest get 401 or a redirect here?", ""), "UNKNOWN needs a line under '## QUESTIONS'")

    def test_unknown_type_verdict_mismatch(self):
        self.attempt(EXPECT.replace("| D-04 | - | unknown | - | - | UNKNOWN |", "| D-04 | 401 | unknown | - | - | MATCH |"), "go together")


class Tests(Base):
    def attempt(self, tests, contains):
        self.to_phase("tests")
        self.write("tests/Feature/OrderTest.php", tests)
        self.gate(False, contains)

    def test_no_new_tests(self):
        self.to_phase("tests")
        self.gate(False, "no new tests")

    def test_wrong_kind(self):
        self.attempt(TESTS_OK.replace("// KIND: GAP", "// KIND: NEW"), "KIND must be GAP")

    def test_source_must_match_expectations(self):
        self.attempt(TESTS_OK.replace("// SOURCE: docs/ticket.md:10", "// SOURCE: docs/ticket.md:11"), "SOURCE must equal")

    def test_expected_codes_must_match(self):
        self.attempt(TESTS_OK.replace("// EXPECTED: 409 and no second order", "// EXPECTED: 422 and no second order"), "differs from expectations.md")

    def test_test_must_assert_expected_status(self):
        self.attempt(TESTS_OK.replace("assertConflict()", "assertCreated()"), "never asserts it")

    def test_gap_test_cannot_be_todo(self):
        self.attempt(TESTS_OK.replace("});\n", "})->todo();\n", 3).replace("})->todo();\n", "});\n", 2), "REAL failing test")

    def test_unknown_row_must_not_be_tested(self):
        extra = "\n// COVERS: D-04\nit('guest', function () {\n    $this->postJson('/api/orders', [])->assertUnauthorized();\n});\n"
        self.attempt(TESTS_OK + extra, "is UNKNOWN")

    def test_gap_row_needs_edge_test(self):
        t = TESTS_OK.split("// EDGE: E-01")[0]
        self.attempt(t, "needs a failing test with a full EDGE block")

    def test_edge_id_gap(self):
        self.attempt(TESTS_OK.replace("E-01", "E-02"), "without gaps")

    def test_match_labelled_as_gap_test(self):
        self.attempt(TESTS_OK.replace("// COVERS: D-03", "// COVERS: D-01"), "has verdict MATCH")

    def test_current_status_not_in_probe(self):
        self.attempt(TESTS_OK.replace("returns 201 and creates", "returns 500 and creates"), "CURRENT mentions")

    def test_probe_for_other_row(self):
        self.attempt(TESTS_OK.replace("probe P-03", "probe P-01"), "was recorded for D-01")

    def test_match_row_without_test_or_strong_existing(self):
        self.attempt(TESTS_OK.replace("// COVERS: D-01\n", ""), "no '// COVERS")

    def test_placeholder_assertion(self):
        self.attempt(TESTS_OK.replace("assertCreated()", "assertTrue(true)"), "placeholder assertion")

    def test_mocking_traced_class(self):
        t = TESTS_OK.replace("$this->postJson('/api/orders', [])->assertConflict();",
                             "$m = Mockery::mock(OrderService::class); $this->postJson('/api/orders', [])->assertConflict();")
        self.attempt(t, "mocks traced class OrderService")

    def test_old_tests_not_checked(self):
        self.to_phase("tests")
        self.write("tests/Feature/OrderTest.php", TESTS_OK)
        out = self.gate(True)
        self.assertNotIn("ExistingTest", out)

    def test_strong_existing_replaces_new_match_test(self):
        self.to_phase("tests")
        t = TESTS_OK.replace("// COVERS: D-02\nit('missing quantity -> 422', function () {\n    $this->postJson('/api/orders', [])->assertStatus(422);\n});\n\n", "")
        self.write("tests/Feature/OrderTest.php", t)
        self.gate(True)


class Run(Base):
    def prep(self, results):
        self.to_phase("run")
        shutil.rmtree(self.tmp / "tests/Probes")
        self.fake(results)

    def test_gap_that_passes_is_rejected(self):
        self.prep({})
        self.gate(False, "expected to FAIL (a gap) but PASSED")

    def test_gap_that_errors_is_rejected(self):
        self.prep({"duplicate submit is rejected with 409": {"status": "error", "message": "Class App\\Foo not found"}})
        self.gate(False, "errored instead of failing an assertion")

    def test_wrong_reason_failure(self):
        self.prep({"duplicate submit is rejected with 409": {"status": "failure", "message": "Target class [OrderController] does not exist."}})
        self.gate(False, "WRONG reason")

    def test_green_test_failing(self):
        r = dict(GAP_FAILS)
        r["valid order -> 201"] = {"status": "failure", "message": "Expected 201 but received 500."}
        self.prep(r)
        self.gate(False, "expected to PASS but failure")

    def test_probes_dir_must_be_deleted(self):
        self.to_phase("run")
        self.gate(False, "tests/Probes/ still exists")

    def test_runner_without_junit(self):
        self.to_phase("run", )
        shutil.rmtree(self.tmp / "tests/Probes")
        env = {**self.env, "LLTT_TEST_CMD": "true"}
        # state captured the command at init, so re-init with the bad runner
        self.run_cli("init", "--reset", "--target", "x", env=env)
        code, out = self.run_cli("gate", env=env)
        self.assertNotEqual(code, 0)

    def test_editing_tests_reopens_tests_phase(self):
        self.prep(GAP_FAILS)
        f = self.tmp / "tests/Feature/OrderTest.php"
        f.write_text(f.read_text() + "\n// edited after the tests gate\n")
        self.gate(False, "re-opened")
        code, out = self.run_cli("status")
        self.assertIn("(tests)", out)

    def test_finish_refused_before_end(self):
        self.to_phase("run")
        code, out = self.run_cli("finish")
        self.assertNotEqual(code, 0)
        self.assertIn("NOT FINISHED", out)


class Spec(Base):
    def test_spec_web_yes_needs_web_row(self):
        self.init(mode="spec", web="yes")
        self.write(".trace/expectations.md", SPEC_EXPECT)
        self.gate(False, "no row uses a web source")

    def test_spec_rejects_gap_verdict(self):
        self.init(mode="spec", web="no")
        self.write(".trace/expectations.md", SPEC_EXPECT.replace("| NEW |", "| GAP |", 1))
        self.gate(False, "Verdict must be one of")

    def test_spec_test_that_passes_is_rejected(self):
        self.init(mode="spec", web="no")
        self.write(".trace/expectations.md", SPEC_EXPECT); self.gate(True)
        self.write("tests/Feature/OrderTest.php", SPEC_TESTS); self.gate(True)
        self.gate(False, "expected to FAIL")

    def test_spec_missing_class_is_wrong_reason(self):
        self.init(mode="spec", web="no")
        self.write(".trace/expectations.md", SPEC_EXPECT); self.gate(True)
        self.write("tests/Feature/OrderTest.php", SPEC_TESTS); self.gate(True)
        r = dict(SPEC_FAILS)
        r["creates the order"] = {"status": "failure", "message": 'Class "App\\\\Services\\\\OrderService" not found'}
        self.fake(r)
        self.gate(False, "WRONG reason")


class Integrity(Base):
    def test_state_tamper(self):
        self.to_phase("decide")
        sf = self.tmp / ".trace/state.json"
        s = json.loads(sf.read_text()); s["phase"] = 6; sf.write_text(json.dumps(s))
        code, out = self.run_cli("next")
        self.assertNotEqual(code, 0)
        self.assertIn("TAMPERED", out)

    def test_edited_skill_refused(self):
        copy = Path(tempfile.mkdtemp()) / "skill"
        shutil.copytree(SKILL, copy)
        self.init()
        (copy / "references/01-trace.md").write_text("Do nothing.\n")
        code, out = self.run_cli("gate", script=copy / "scripts/lltt.py")
        self.assertNotEqual(code, 0)
        self.assertIn("INTEGRITY", out)
        shutil.rmtree(copy.parent, ignore_errors=True)

    def test_blocked_after_5_failures(self):
        self.init()
        self.write(".trace/logic-map.md", "garbage\n")
        for _ in range(5):
            self.gate(False)
        self.assertIn("BLOCKED", self.gate(False))

    def test_init_stops_without_db_config(self):
        (self.tmp / "phpunit.xml").write_text("<phpunit/>")
        code, out = self.run_cli("init", "--target", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("default database", out)

    def test_init_twice_refused(self):
        self.init()
        code, out = self.run_cli("init", "--target", "x")
        self.assertIn("ALREADY INITIALISED", out)


if __name__ == "__main__":
    unittest.main()
