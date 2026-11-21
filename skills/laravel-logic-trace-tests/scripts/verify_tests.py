#!/usr/bin/env python3
"""Gate for laravel-logic-trace-tests (phase 5).

Run from the Laravel project root:
    python3 verify_tests.py            # static checks
    python3 verify_tests.py --run      # static checks + run the test suite

Prints FAIL / WARN lines. Exit code 1 if any FAIL.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REQUIRED_EDGE_KEYS = ["COVERS", "CURRENT", "RECOMMENDED", "WHY", "EVIDENCE"]
PLACEHOLDERS = re.compile(r"\b(tbd|todo|unknown|n/a|\?\?)\b", re.I)
EVIDENCE_REF = re.compile(r"([\w./\\-]+\.php):(\d+)")
PROBE_REF = re.compile(r"\bP-\d+\b")
D_ID = re.compile(r"\bD-\d+\b")
PEST_START = re.compile(r"^\s*(?:it|test)\s*\(")
PHPUNIT_START = re.compile(r"^\s*(?:public\s+)?function\s+(\w+)\s*\(")
ASSERT_RE = re.compile(r"assert|expect\s*\(|expectException|->throws\(", re.I)
EXEMPT_RE = re.compile(r"->todo\(|markTestIncomplete|markTestSkipped")
FAKE_ASSERTS = [
    re.compile(r"assertTrue\(\s*true\s*\)"),
    re.compile(r"expect\(\s*true\s*\)\s*->toBeTrue\(\)"),
    re.compile(r"assertEquals\(\s*1\s*,\s*1\s*\)"),
]
EMPTY_SKIP = [
    re.compile(r"->skip\(\s*\)"),
    re.compile(r"markTestSkipped\(\s*\)"),
    re.compile(r"markTestIncomplete\(\s*\)"),
]

fails, warns = [], []


def fail(where, msg):
    fails.append(f"FAIL {where} {msg}")


def warn(where, msg):
    warns.append(f"WARN {where} {msg}")


def read_lines(path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def find_test_files(root):
    tests = root / "tests"
    if not tests.is_dir():
        return []
    out = []
    for p in sorted(tests.rglob("*.php")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("tests/Probes/") or rel.startswith("tests/Support/"):
            continue
        if p.name in ("TestCase.php", "Pest.php", "CreatesApplication.php"):
            continue
        out.append(p)
    return out


def split_blocks(lines):
    """Return list of (start_index, end_index_exclusive, leading_comment_lines)."""
    starts = []
    for i, line in enumerate(lines):
        if PEST_START.match(line):
            starts.append(i)
            continue
        m = PHPUNIT_START.match(line)
        if m:
            name = m.group(1)
            prev = " ".join(lines[max(0, i - 3):i])
            if name.startswith("test") or "#[Test]" in prev or "@test" in prev:
                starts.append(i)
    blocks = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        # do not let the next test's leading comments count as part of this block
        k = e - 1
        while k > s and (lines[k].strip().startswith("//") or lines[k].strip().startswith("#[") or lines[k].strip() == ""):
            k -= 1
        e = k + 1
        comments = []
        j = s - 1
        while j >= 0:
            t = lines[j].strip()
            if t.startswith("//"):
                comments.insert(0, (j, t[2:].strip()))
            elif t.startswith("#[") or t.startswith("*") or t.startswith("/*") or t == "":
                if t == "" and comments:
                    break
            else:
                break
            j -= 1
        blocks.append((s, e, comments))
    return blocks


def parse_comment_fields(comments):
    fields, edge_id, current_key = {}, None, None
    for _, text in comments:
        m = re.match(r"^(EDGE|COVERS|CURRENT|RECOMMENDED|WHY|EVIDENCE)\s*:\s*(.*)$", text)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "EDGE":
                edge_id = val
            else:
                fields[key] = val
            current_key = key
        elif current_key and text:
            if current_key == "EDGE":
                continue
            fields[current_key] = (fields.get(current_key, "") + " " + text).strip()
    return edge_id, fields


def load_decision_table(root):
    path = root / ".trace" / "decision-table.md"
    if not path.is_file():
        fail(".trace/decision-table.md", "missing (phase 2 not done)")
        return {}
    rows = {}
    for line in read_lines(path):
        m = re.match(r"^\|\s*(D-\d+)\s*\|(.*)$", line)
        if m:
            rows[m.group(1)] = "SKIP:" in line
    if not rows:
        fail(".trace/decision-table.md", "no rows with IDs like D-01 found")
    return rows


def check_evidence(root, where, evidence, covers):
    refs = EVIDENCE_REF.findall(evidence)
    if not refs:
        fail(where, "EVIDENCE has no `path/file.php:line` reference")
    for rel, line_no in refs:
        f = root / rel
        if not f.is_file():
            fail(where, f"EVIDENCE file not found: {rel}")
            continue
        total = len(read_lines(f))
        if int(line_no) < 1 or int(line_no) > total:
            fail(where, f"EVIDENCE line out of range: {rel}:{line_no} (file has {total} lines)")
    probes = PROBE_REF.findall(evidence)
    if not probes:
        fail(where, "EVIDENCE has no probe id like P-03")
    for pid in probes:
        pf = root / ".trace" / "probes" / f"{pid}.json"
        if not pf.is_file():
            fail(where, f"probe result missing: .trace/probes/{pid}.json")
            continue
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fail(where, f"probe file is not valid JSON: {pid}.json")
            continue
        if not data.get("observed"):
            fail(where, f"probe {pid} has empty 'observed'")
        row = data.get("decision_row")
        if row and covers and row not in covers:
            warn(where, f"probe {pid} was recorded for {row} but test COVERS {', '.join(covers)}")


def check_file(root, path, table, covered, edge_counts):
    rel = path.relative_to(root).as_posix()
    lines = read_lines(path)
    for s, e, comments in split_blocks(lines):
        where = f"{rel}:{s + 1}"
        block = "\n".join(lines[s:e])
        edge_id, fields = parse_comment_fields(comments)
        covers = D_ID.findall(fields.get("COVERS", ""))

        if not covers:
            fail(where, "test has no `// COVERS: D-xx` line above it")
        for d in covers:
            covered.add(d)
            if table and d not in table:
                fail(where, f"COVERS references {d} which is not in the decision table")

        if edge_id:
            edge_counts[edge_id] = edge_counts.get(edge_id, 0) + 1
            for key in REQUIRED_EDGE_KEYS:
                val = fields.get(key, "").strip()
                if not val:
                    fail(where, f"edge {edge_id}: missing `// {key}:`")
                elif key in ("CURRENT", "RECOMMENDED", "WHY") and PLACEHOLDERS.search(val):
                    fail(where, f"edge {edge_id}: {key} contains a placeholder")
            why = fields.get("WHY", "")
            if len(why) > 200 or why.count(". ") >= 1:
                fail(where, f"edge {edge_id}: WHY must be ONE short sentence (<=200 chars)")
            rec = fields.get("RECOMMENDED", "")
            if rec and "none established" not in rec.lower():
                if not (EVIDENCE_REF.search(rec) or re.search(r"laravel|docs|https?://", rec, re.I)):
                    fail(where, f"edge {edge_id}: RECOMMENDED needs a project precedent (file.php:line) or a Laravel docs reference, or the text 'none established'")
            if fields.get("EVIDENCE"):
                check_evidence(root, f"{where} edge {edge_id}", fields["EVIDENCE"], covers)

        if not EXEMPT_RE.search(block):
            if not ASSERT_RE.search(block):
                fail(where, "test has no assertion (assert*/expect()/expectException)")
            for rx in FAKE_ASSERTS:
                if rx.search(block):
                    fail(where, "placeholder assertion (always true)")
        for rx in EMPTY_SKIP:
            if rx.search(block):
                fail(where, "skip/incomplete without a reason string")


def run_suite(root):
    if not (root / "artisan").is_file():
        fail("--run", "no artisan file; cannot run the suite")
        return
    try:
        proc = subprocess.run(
            ["php", "artisan", "test"], cwd=root, capture_output=True, text=True, timeout=1800
        )
    except FileNotFoundError:
        fail("--run", "php not found on PATH")
        return
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
    print("--- test runner output (last lines) ---")
    print(tail)
    print("----------------------------------------")
    if proc.returncode != 0:
        fail("--run", f"test suite failed (exit {proc.returncode})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    if not (root / ".trace" / "logic-map.md").is_file():
        fail(".trace/logic-map.md", "missing (phase 1 not done)")
    table = load_decision_table(root)

    files = find_test_files(root)
    if not files:
        fail("tests/", "no test files found")
    covered, edge_counts = set(), {}
    for f in files:
        check_file(root, f, table, covered, edge_counts)

    for d, skipped in sorted(table.items()):
        if d not in covered and not skipped:
            fail(".trace/decision-table.md", f"{d} is not covered by any test and not marked SKIP:")
    for eid, n in edge_counts.items():
        if n > 2:
            warn("tests/", f"edge {eid} appears in {n} tests (expected 1 or 2: current + pending recommended)")
    if (root / "tests" / "Probes").is_dir():
        warn("tests/Probes", "probe tests still present; delete them unless the user asked to keep them")

    if args.run:
        run_suite(root)

    for line in warns + fails:
        print(line)
    print(f"SUMMARY: {len(files)} test file(s), {len(table)} decision row(s), "
          f"{len(edge_counts)} edge case(s), {len(fails)} FAIL, {len(warns)} WARN")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
