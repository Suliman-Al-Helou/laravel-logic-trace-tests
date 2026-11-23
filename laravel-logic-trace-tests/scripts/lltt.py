#!/usr/bin/env python3
"""lltt: workflow driver and gate for the laravel-logic-trace-tests skill.

The agent does not follow a prose workflow. This script owns the workflow:

    lltt.py init --target "POST /api/orders"
    lltt.py next      # prints ONLY the current phase
    lltt.py gate      # checks the phase output; advances only on PASS
    lltt.py finish    # runs nothing by itself except report generation

Phases: 1 trace, 2 decide, 3 probe, 4 write-tests, 5 run (the script runs the tests),
then `finish` generates the report and the final answer.

Run from the Laravel project root (or pass --root).
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "0.2.0"
SELF = Path(__file__).resolve()
SKILL_DIR = SELF.parent.parent
MAX_ATTEMPTS = 5
SKEW = 3  # seconds of tolerated clock skew
MIN_PROBED_RATIO = 0.6
NEAR_LINES = 5  # a "precedent" this close to the evidence line counts as circular

PHASES = [
    (1, "trace", "01-trace.md", [".trace/logic-map.md"]),
    (2, "decide", "02-decision-table.md", [".trace/decision-table.md"]),
    (3, "probe", "03-probe.md", ["tests/Probes/*.php", ".trace/probes/P-xx.json"]),
    (4, "write-tests", "04-write-tests.md", ["tests/** (new tests only)"]),
    (5, "run", "05-run.md", ["(the script runs the tests and writes .trace/run.json)"]),
]
LAYERS = {
    "route", "middleware", "request", "validation", "controller", "service", "model",
    "database", "event", "job", "policy", "auth", "response", "cache", "storage",
}
EDGE_KEYS = ["COVERS", "VERDICT", "CURRENT", "RECOMMENDED", "WHY", "EVIDENCE"]
VERDICTS = {"SAME", "DIFFERS", "NO-RECOMMENDATION"}

REF_RE = re.compile(r"((?:[\w.\-]+[/\\])*[\w.\-]+\.php):(\d+)")
PROBE_ID_RE = re.compile(r"\bP-\d+\b")
D_ID_RE = re.compile(r"\bD-\d+\b")
STATUS_RE = re.compile(r"\b[1-5]\d\d\b")
PLACEHOLDER_RE = re.compile(r"\b(tbd|unknown|n/a|lorem)\b|\?\?|<(?:entry point|what you searched|reason|file|fact)[^>]*>", re.I)
NONE_RE = re.compile(r"^[-*\s]*(?:[^:]{0,60}:\s*)?none\b", re.I)
NOTFOUND_RE = re.compile(r"NOT FOUND:\s*\S+", re.I)
PEST_TITLE = re.compile(r"^\s*(?:it|test)\s*\(\s*(?P<q>['\"])(?P<title>.*?)(?P=q)")
PEST_ANY = re.compile(r"^\s*(?:it|test)\s*\(")
PHPUNIT_FN = re.compile(r"^\s*(?:public\s+)?function\s+(\w+)\s*\(")
ASSERT_RE = re.compile(r"assert|expect\s*\(|expectException|->throws\(", re.I)
PENDING_RE = re.compile(r"->todo\(|markTestIncomplete|markTestSkipped")
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
MOCK_RE = re.compile(r"(?:Mockery::mock|Mockery::spy|->mock|->spy|->partialMock)\(\s*([\\\w]+)::class")
COMMENT_KEY_RE = re.compile(
    r"^(EDGE|COVERS|VERDICT|CURRENT|RECOMMENDED|WHY|EVIDENCE|ALLOW-MOCK)\s*:\s*(.*)$"
)

STANDING_RULES = """\
STANDING RULES (apply in every phase)
 1. Do only what this phase says. Do not read ahead. Do not skip steps.
 2. Never edit app code, files inside the skill folder, .trace/state.json or .trace/.key.
 3. Every fact needs a file.php:line you actually opened. No source = do not write it.
 4. Never write "tests pass" yourself. Only this script's output counts.
 5. If a gate says BLOCKED, stop and show the user the failures."""

LABELS = {
    "en": {
        "summary": "Summary", "edges": "Edge cases", "tested": "decision rows tested",
        "probes": "probes", "differs": "edge cases where CURRENT differs from RECOMMENDED",
        "same": "edge cases where CURRENT equals RECOMMENDED", "norec": "edge cases without an established recommendation",
        "nottested": "rows not tested", "run": "Test run", "report": "Full report", "time": "Time",
        "files": "Test files", "none": "none",
    },
    "ar": {
        "summary": "الملخص", "edges": "الحالات الحدية", "tested": "صفوف قرار مختبرة",
        "probes": "probes", "differs": "حالات يختلف فيها الحالي عن الموصى به",
        "same": "حالات الحالي فيها يساوي الموصى به", "norec": "حالات بلا توصية مثبتة",
        "nottested": "صفوف غير مختبرة", "run": "تشغيل الاختبارات", "report": "التقرير الكامل", "time": "الوقت",
        "files": "ملفات الاختبار", "none": "لا يوجد",
    },
}


# ----------------------------------------------------------------------------- utils
def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def sha_text(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def read_lines(path: Path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def die(msg: str, code: int = 1):
    print(msg)
    sys.exit(code)


def refs_in(text: str):
    return [(p.replace("\\", "/"), int(n)) for p, n in REF_RE.findall(text)]


class Ctx:
    def __init__(self, root: Path):
        self.root = root
        self.trace = root / ".trace"
        self._lines = {}

    def line_count(self, rel: str):
        if rel not in self._lines:
            f = self.root / rel
            self._lines[rel] = len(read_lines(f)) if f.is_file() else None
        return self._lines[rel]

    def check_refs(self, refs, where: str):
        errs = []
        for rel, n in refs:
            total = self.line_count(rel)
            if total is None:
                errs.append(f"{where}: file not found: {rel}")
            elif n < 1 or n > total:
                errs.append(f"{where}: line out of range: {rel}:{n} (file has {total} lines)")
        return errs


# ----------------------------------------------------------------------------- manifest
def manifest_files():
    files = [SKILL_DIR / "SKILL.md", SELF]
    for sub in ("references", "assets"):
        d = SKILL_DIR / sub
        if d.is_dir():
            files += sorted(p for p in d.iterdir() if p.is_file())
    return files


def make_manifest():
    lines = []
    for p in manifest_files():
        if p.is_file():
            lines.append(f"{sha_text(p)}  {p.relative_to(SKILL_DIR).as_posix()}")
    (SKILL_DIR / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"MANIFEST written ({len(lines)} files)")


def verify_manifest():
    mf = SKILL_DIR / "MANIFEST.sha256"
    if not mf.is_file():
        return ["MANIFEST.sha256 missing. Reinstall the skill."]
    expected = {}
    for line in mf.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, rel = line.split("  ", 1)
            expected[rel.strip()] = h
    errs = []
    for rel, h in expected.items():
        p = SKILL_DIR / rel
        if not p.is_file():
            errs.append(f"skill file missing: {rel}")
        elif sha_text(p) != h:
            errs.append(f"skill file was modified: {rel}")
    for p in manifest_files():
        rel = p.relative_to(SKILL_DIR).as_posix()
        if p.is_file() and rel not in expected:
            errs.append(f"unexpected skill file: {rel}")
    return errs


# ----------------------------------------------------------------------------- state
def sign(state: dict, key: str) -> str:
    body = json.dumps({k: v for k, v in state.items() if k != "sig"}, sort_keys=True, ensure_ascii=False)
    return hmac.new(key.encode(), body.encode("utf-8"), "sha256").hexdigest()


def read_key(ctx: Ctx) -> str:
    kf = ctx.trace / ".key"
    if not kf.is_file():
        die("STATE ERROR: .trace/.key missing. Run: init --reset")
    return kf.read_text().strip()


def save_state(ctx: Ctx, state: dict):
    state["sig"] = sign(state, read_key(ctx))
    (ctx.trace / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state(ctx: Ctx) -> dict:
    sf = ctx.trace / "state.json"
    if not sf.is_file():
        die("NOT INITIALISED. Run: init --target \"<endpoint or class>\"")
    state = json.loads(sf.read_text(encoding="utf-8"))
    if not hmac.compare_digest(state.get("sig", ""), sign(state, read_key(ctx))):
        die("STATE TAMPERED: .trace/state.json was edited by hand. Run: init --reset")
    return state


def cmd_prefix(state: dict) -> str:
    return f"python3 {SELF}"


# ----------------------------------------------------------------------------- environment
def run_quiet(cmd, cwd):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
        return (p.stdout + p.stderr).strip()
    except Exception:
        return ""


def detect_env(root: Path):
    info, stops, notes = {}, [], []
    if not (root / "artisan").is_file():
        stops.append("no 'artisan' file here. Run from the Laravel project root (or pass --root).")
    import os
    custom = os.environ.get("LLTT_TEST_CMD", "").strip()
    php = shutil.which("php")
    info["php"] = run_quiet(["php", "-r", "echo PHP_VERSION;"], root) if php else "not found"
    info["laravel"] = run_quiet(["php", "artisan", "--version"], root) if php and (root / "artisan").is_file() else "unknown"
    composer = (root / "composer.json").read_text(encoding="utf-8", errors="replace") if (root / "composer.json").is_file() else ""
    info["runner"] = "pest" if (root / "vendor/bin/pest").exists() or '"pestphp/pest"' in composer else "phpunit"
    info["test_cmd"] = custom or "php artisan test"
    if not custom and not php:
        stops.append("php not found on PATH. Set LLTT_TEST_CMD, e.g. LLTT_TEST_CMD='sail artisan test'.")
    cfg = next((root / n for n in ("phpunit.xml", "phpunit.xml.dist") if (root / n).is_file()), None)
    if cfg is None:
        stops.append("no phpunit.xml found. Ask the user how tests are configured.")
    else:
        text = cfg.read_text(encoding="utf-8", errors="replace")
        m_c = re.search(r'name="DB_CONNECTION"[^>]*value="([^"]*)"', text)
        m_d = re.search(r'name="DB_DATABASE"[^>]*value="([^"]*)"', text)
        conn, dbn = (m_c.group(1) if m_c else ""), (m_d.group(1) if m_d else "")
        info["test_db"] = f"{conn or 'NOT SET'} / {dbn or 'NOT SET'}"
        has_env_testing = (root / ".env.testing").is_file()
        if not conn and not has_env_testing:
            stops.append(f"{cfg.name} sets no DB_CONNECTION and there is no .env.testing: probes could hit the default database.")
        elif conn and conn != "sqlite" and not dbn and not has_env_testing:
            stops.append("non-sqlite test connection without a DB_DATABASE override. Ask the user which test database to use.")
    traits = []
    tdir = root / "tests"
    if tdir.is_dir():
        for p in tdir.rglob("*.php"):
            t = p.read_text(encoding="utf-8", errors="replace")
            for name in ("RefreshDatabase", "DatabaseTransactions", "LazilyRefreshDatabase"):
                if name in t:
                    traits.append(name)
    info["db_trait"] = max(set(traits), key=traits.count) if traits else "none found (check Pest.php / base TestCase)"
    return info, stops, notes


# ----------------------------------------------------------------------------- test parsing
def list_test_files(root: Path):
    tdir = root / "tests"
    out = []
    if tdir.is_dir():
        for p in sorted(tdir.rglob("*.php")):
            rel = p.relative_to(root).as_posix()
            if rel.startswith("tests/Probes/") or rel.startswith("tests/Support/"):
                continue
            if p.name in ("TestCase.php", "Pest.php", "CreatesApplication.php"):
                continue
            out.append(p)
    return out


def parse_blocks(lines):
    starts = []
    for i, line in enumerate(lines):
        m = PEST_TITLE.match(line)
        if m:
            starts.append((i, m.group("title")))
            continue
        if PEST_ANY.match(line):
            starts.append((i, line.strip()))
            continue
        m = PHPUNIT_FN.match(line)
        if m:
            prev = " ".join(lines[max(0, i - 3):i])
            if m.group(1).startswith("test") or "#[Test]" in prev or "@test" in prev:
                starts.append((i, m.group(1)))
    blocks = []
    for n, (s, name) in enumerate(starts):
        e = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        k = e - 1
        while k > s and (lines[k].strip().startswith("//") or lines[k].strip().startswith("#[") or lines[k].strip() == ""):
            k -= 1
        e = k + 1
        comments, j = [], s - 1
        while j >= 0:
            t = lines[j].strip()
            if t.startswith("//"):
                comments.insert(0, t[2:].strip())
            elif t.startswith("#[") or t.startswith("*") or t.startswith("/*"):
                pass
            elif t == "":
                if comments:
                    break
            else:
                break
            j -= 1
        blocks.append({"name": name, "start": s, "end": e, "comments": comments, "text": "\n".join(lines[s:e])})
    return blocks


def parse_fields(comments):
    fields, cur, edge = {}, None, None
    for text in comments:
        m = COMMENT_KEY_RE.match(text)
        if m:
            key, val = m.group(1), m.group(2).strip()
            cur = key
            if key == "EDGE":
                edge = val
            else:
                fields[key] = val
        elif cur and cur != "EDGE" and text:
            fields[cur] = (fields.get(cur, "") + " " + text).strip()
    return edge, fields


def snapshot_tests(root: Path):
    snap = {}
    for p in list_test_files(root):
        rel = p.relative_to(root).as_posix()
        snap[rel] = {"sha": sha_text(p), "blocks": [b["name"] for b in parse_blocks(read_lines(p))]}
    return snap


# ----------------------------------------------------------------------------- decision table
def parse_table(ctx: Ctx):
    """Return (rows, errors). Each row: dict(id, layer, cond, outcome, source, probe)."""
    p = ctx.trace / "decision-table.md"
    rows, errs = [], []
    if not p.is_file():
        return rows, [".trace/decision-table.md is missing"]
    header_seen = False
    for ln in read_lines(p):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if cells and cells[0].upper() == "ID":
            header_seen = True
            if len(cells) != 6:
                errs.append("table header must have 6 columns: ID | Layer | Condition | Code outcome | Source | Probe")
            continue
        if len(cells) != 6:
            errs.append(f"malformed row (need 6 columns): {s[:70]}")
            continue
        rows.append({"id": cells[0], "layer": cells[1].lower(), "cond": cells[2], "outcome": cells[3],
                     "source": cells[4], "probe": cells[5]})
    if not header_seen:
        errs.append("table header row (ID | Layer | ...) not found")
    return rows, errs


def probe_kind(probe: str):
    if re.fullmatch(r"P-\d+", probe):
        return "probe"
    m = re.fullmatch(r"no:duplicate-of:(D-\d+)", probe)
    if m:
        return "dup:" + m.group(1)
    if re.fullmatch(r"no:(external|unreachable):.+", probe):
        return "no"
    return None


# ----------------------------------------------------------------------------- probes
def numbers_in(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int):
        out.add(obj)
    elif isinstance(obj, str) and obj.strip().isdigit():
        out.add(int(obj.strip()))
    elif isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            numbers_in(v, out)
    return out


def status_values(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.fullmatch(r"(http_)?status\w*", str(k), re.I):
                numbers_in(v, out)
            else:
                status_values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            status_values(v, out)
    return out


def load_probe(ctx: Ctx, pid: str):
    f = ctx.trace / "probes" / f"{pid}.json"
    if not f.is_file():
        return None, f"probe result missing: .trace/probes/{pid}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")), None
    except json.JSONDecodeError:
        return None, f"probe file is not valid JSON: {pid}.json"


# ----------------------------------------------------------------------------- gates
def gate_trace(ctx: Ctx, state: dict):
    errs = []
    p = ctx.trace / "logic-map.md"
    if not p.is_file():
        return [".trace/logic-map.md is missing"], []
    sections, cur = {}, None
    for ln in read_lines(p):
        m = re.match(r"^##\s*(\d+)\.", ln)
        if m:
            cur = int(m.group(1))
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(ln)
    for n in range(1, 11):
        if n not in sections:
            errs.append(f"section '## {n}.' is missing (use assets/logic-map.template.md)")
    all_refs, sec1_refs = [], []
    for n in range(1, 11):
        body = [l for l in sections.get(n, []) if l.strip() and not l.strip().startswith(("<!--", "###", "```"))
                and not set(l.strip()) <= set("|-: ")]
        if n in sections and not body:
            errs.append(f"section {n} is empty: write 'none' if nothing applies")
        for l in body:
            s = l.strip()
            if PLACEHOLDER_RE.search(s):
                errs.append(f"section {n}: template placeholder left in -> {s[:60]}")
                continue
            r = refs_in(s)
            if r:
                errs += ctx.check_refs(r, f"section {n}")
                all_refs += r
                if n == 1:
                    sec1_refs += r
            elif NONE_RE.match(s) or NOTFOUND_RE.search(s):
                continue
            elif s.endswith(":"):
                errs.append(f"section {n}: empty field -> {s[:60]}")
            else:
                errs.append(f"section {n}: statement without a file.php:line source -> {s[:60]}")
    if state.get("type") == "http" and not any(f.startswith("routes/") for f, _ in sec1_refs):
        errs.append("section 1 (Route) must cite a routes/*.php line for an HTTP target")
    need = 4 if state.get("type") == "http" else 3
    if len({r for r in all_refs}) < need:
        errs.append(f"the map cites only {len(set(all_refs))} distinct file:line sources (minimum {need})")
    return errs, []


def gate_decide(ctx: Ctx, state: dict):
    errs, warns = [], []
    rows, e0 = parse_table(ctx)
    errs += e0
    if e0 and not rows:
        return errs, warns
    if len(rows) < 3:
        errs.append(f"only {len(rows)} decision rows (minimum 3)")
    ids = [r["id"] for r in rows]
    for i, rid in enumerate(ids, 1):
        if rid != f"D-{i:02d}":
            errs.append(f"row ids must be sequential D-01, D-02, ...; found {rid} at position {i}")
            break
    probe_ids, source_files = [], set()
    probed = 0
    for r in rows:
        w = r["id"]
        if r["layer"] not in LAYERS:
            errs.append(f"{w}: layer '{r['layer']}' not in {sorted(LAYERS)}")
        refs = refs_in(r["source"])
        if not refs:
            errs.append(f"{w}: Source needs a file.php:line")
        errs += ctx.check_refs(refs, w)
        source_files |= {f for f, _ in refs}
        if not r["cond"] or not r["outcome"] or PLACEHOLDER_RE.search(r["cond"] + r["outcome"]):
            errs.append(f"{w}: empty or placeholder Condition/Code outcome")
        kind = probe_kind(r["probe"])
        if kind is None:
            errs.append(f"{w}: Probe column must be P-xx, no:duplicate-of:D-xx, no:external:<reason> or no:unreachable:<reason>")
        elif kind == "probe":
            probed += 1
            probe_ids.append(r["probe"])
        elif kind.startswith("dup:"):
            target = kind[4:]
            if target not in ids or target == r["id"]:
                errs.append(f"{w}: duplicate-of target {target} is invalid")
        elif len(r["probe"].split(":", 2)[2].split()) < 3:
            errs.append(f"{w}: 'no:' reason needs at least 3 words")
    dup = {p for p in probe_ids if probe_ids.count(p) > 1}
    if dup:
        errs.append(f"probe ids used by more than one row: {sorted(dup)}")
    if rows and probed / len(rows) < MIN_PROBED_RATIO:
        errs.append(f"only {probed}/{len(rows)} rows have a probe (minimum {int(MIN_PROBED_RATIO * 100)}%). Probe more rows.")
    text = (ctx.trace / "decision-table.md").read_text(encoding="utf-8")
    nb = {}
    for m in re.finditer(r"^[-*]\s*(app/[\w/.\-]+\.php):\s*(.+)$", text, re.M):
        nb[m.group(1)] = m.group(2)
        if len(m.group(2).split()) < 3:
            errs.append(f"NO-BRANCH entry for {m.group(1)} needs a reason of at least 3 words")
    map_text = (ctx.trace / "logic-map.md").read_text(encoding="utf-8")
    for f in sorted(set(re.findall(r"app/[\w/.\-]+\.php", map_text))):
        if f not in source_files and f not in nb:
            errs.append(f"{f} is in the logic map but has no decision row and no '- {f}: <reason>' NO-BRANCH line")
    return errs, warns


def gate_probe(ctx: Ctx, state: dict):
    errs, warns = [], []
    rows, _ = parse_table(ctx)
    key = read_key(ctx)
    phase2_done = parse_iso(next(h for h in state["history"] if h["phase"] == 2)["completed_at"])
    pdir = ctx.root / "tests" / "Probes"
    src_ids = set()
    if pdir.is_dir():
        for f in pdir.rglob("*.php"):
            src_ids |= set(re.findall(r"['\"](P-\d+)['\"]", f.read_text(encoding="utf-8", errors="replace")))
    else:
        errs.append("tests/Probes/ does not exist: probes must be tests that call ProbeRecorder::save(...)")
    mismatches = []
    seen = set()
    for r in rows:
        if probe_kind(r["probe"]) != "probe":
            continue
        pid, w = r["probe"], r["id"]
        seen.add(pid)
        data, err = load_probe(ctx, pid)
        if err:
            errs.append(f"{w}: {err}")
            continue
        if pid not in src_ids:
            errs.append(f"{w}: no probe test in tests/Probes/ mentions '{pid}' (hand-written results are rejected)")
        if data.get("probe") != pid or data.get("decision_row") != w:
            errs.append(f"{w}: {pid}.json says probe={data.get('probe')} row={data.get('decision_row')}")
        if not isinstance(data.get("observed"), dict) or not data["observed"]:
            errs.append(f"{w}: {pid}.json has empty 'observed'")
            continue
        rec = data.get("recorded_at", "")
        expect = hmac.new(key.encode(), f"{pid}|{w}|{rec}".encode(), "sha256").hexdigest()
        if not hmac.compare_digest(str(data.get("stamp", "")), expect):
            errs.append(f"{w}: {pid}.json has an invalid stamp (not produced by ProbeRecorder in this run)")
            continue
        try:
            t = parse_iso(rec)
        except ValueError:
            errs.append(f"{w}: {pid}.json has a bad recorded_at")
            continue
        if (t - phase2_done).total_seconds() < -SKEW:
            errs.append(f"{w}: {pid}.json was recorded before the decision table was approved")
        if (t - now()).total_seconds() > SKEW:
            errs.append(f"{w}: {pid}.json recorded_at is in the future")
        codes = {int(c) for c in STATUS_RE.findall(r["outcome"])}
        sv = status_values(data["observed"])
        if codes and sv and not (codes & sv):
            mismatches.append(w)
            warns.append(f"{w}: code reading says {sorted(codes)} but the probe observed {sorted(sv)}. This surprise MUST become an EDGE test in phase 4.")
        elif codes and not sv:
            warns.append(f"{w}: Code outcome mentions {sorted(codes)} but the probe has no status key. Add 'status' to observed.")
    pf = ctx.trace / "probes"
    if pf.is_dir():
        for f in sorted(pf.glob("P-*.json")):
            if f.stem not in seen:
                warns.append(f"orphan probe file {f.name} (not referenced by the decision table)")
    state["mismatch_rows"] = mismatches
    return errs, warns


def analyze_tests(ctx: Ctx, state: dict):
    """Collect the NEW test blocks (not present at init) with parsed fields."""
    snap = state.get("snapshot", {})
    owned_files, blocks = {}, []
    for p in list_test_files(ctx.root):
        rel = p.relative_to(ctx.root).as_posix()
        old = snap.get(rel)
        lines = read_lines(p)
        for b in parse_blocks(lines):
            if old is not None and b["name"] in old["blocks"]:
                continue
            edge, fields = parse_fields(b["comments"])
            b.update({"file": rel, "line": b["start"] + 1, "edge": edge, "fields": fields,
                      "pending": bool(PENDING_RE.search(b["text"]))})
            blocks.append(b)
            owned_files[rel] = sha_text(p)
    return blocks, owned_files


def gate_tests(ctx: Ctx, state: dict):
    errs, warns = [], []
    rows, _ = parse_table(ctx)
    by_id = {r["id"]: r for r in rows}
    blocks, owned = analyze_tests(ctx, state)
    if not blocks:
        return ["no new tests found since init (tests already present at init do not count)"], [], {}
    probe_cache = {}
    for r in rows:
        if probe_kind(r["probe"]) == "probe":
            d, _ = load_probe(ctx, r["probe"])
            probe_cache[r["probe"]] = d or {}
    traced = {Path(f).stem for f in re.findall(r"app/[\w/.\-]+\.php", (ctx.trace / "logic-map.md").read_text(encoding="utf-8"))}
    covered, edges = set(), {}
    for b in blocks:
        w = f"{b['file']}:{b['line']}"
        f = b["fields"]
        covers = D_ID_RE.findall(f.get("COVERS", ""))
        if not covers:
            errs.append(f"{w}: test has no '// COVERS: D-xx' line directly above it")
        for d in covers:
            covered.add(d)
            if d not in by_id:
                errs.append(f"{w}: COVERS {d} is not in the decision table")
        if not b["pending"]:
            if not ASSERT_RE.search(b["text"]):
                errs.append(f"{w}: test has no assertion (assert*/expect()/expectException)")
            for rx in FAKE_ASSERTS:
                if rx.search(b["text"]):
                    errs.append(f"{w}: placeholder assertion (always true)")
        for rx in EMPTY_SKIP:
            if rx.search(b["text"]):
                errs.append(f"{w}: skip/incomplete without a reason string")
        for m in MOCK_RE.finditer(b["text"]):
            base = m.group(1).split("\\")[-1]
            if base in traced and f"ALLOW-MOCK: {base}" not in " ".join(b["comments"]):
                errs.append(f"{w}: mocks traced class {base}. Fake only external boundaries, or add '// ALLOW-MOCK: {base} <reason>'")
        if b["edge"]:
            edges.setdefault(b["edge"], []).append(b)
    # edge validation
    for eid, bl in edges.items():
        if not re.fullmatch(r"E-\d+", eid):
            errs.append(f"{bl[0]['file']}:{bl[0]['line']}: edge id '{eid}' must look like E-01")
            continue
        for b in bl:
            w = f"{b['file']}:{b['line']} {eid}"
            f = b["fields"]
            for k in EDGE_KEYS:
                if not f.get(k, "").strip():
                    errs.append(f"{w}: missing '// {k}:'")
            for k in ("CURRENT", "RECOMMENDED", "WHY"):
                if PLACEHOLDER_RE.search(f.get(k, "")):
                    errs.append(f"{w}: {k} contains a placeholder")
            why = f.get("WHY", "")
            if len(why) > 200 or why.count(". ") >= 1:
                errs.append(f"{w}: WHY must be ONE short sentence (max 200 chars)")
            verdict = f.get("VERDICT", "").upper()
            if verdict and verdict not in VERDICTS:
                errs.append(f"{w}: VERDICT must be one of {sorted(VERDICTS)}")
            rec = f.get("RECOMMENDED", "")
            none_est = "none established" in rec.lower()
            if verdict == "NO-RECOMMENDATION" and not none_est:
                errs.append(f"{w}: VERDICT NO-RECOMMENDATION requires 'RECOMMENDED: none established'")
            if none_est and verdict and verdict != "NO-RECOMMENDATION":
                errs.append(f"{w}: 'none established' requires VERDICT: NO-RECOMMENDATION")
            covers = D_ID_RE.findall(f.get("COVERS", ""))
            ev = f.get("EVIDENCE", "")
            ev_refs = refs_in(ev)
            if not ev_refs:
                errs.append(f"{w}: EVIDENCE needs a file.php:line")
            errs += ctx.check_refs(ev_refs, w)
            pids = PROBE_ID_RE.findall(ev)
            if not pids:
                errs.append(f"{w}: EVIDENCE needs a probe id like P-03")
            obs_nums, obs_status = set(), set()
            for pid in pids:
                d = probe_cache.get(pid)
                if d is None:
                    errs.append(f"{w}: probe {pid} is not a probe of the decision table")
                    continue
                if d.get("decision_row") not in covers:
                    errs.append(f"{w}: probe {pid} was recorded for {d.get('decision_row')} but this test COVERS {', '.join(covers) or 'nothing'}")
                obs_nums |= numbers_in(d.get("observed", {}))
                obs_status |= status_values(d.get("observed", {}))
            for d in covers:
                if d in by_id and probe_kind(by_id[d]["probe"]) != "probe":
                    errs.append(f"{w}: an EDGE must cover a probed row; {d} has no probe")
            cur_codes = {int(c) for c in STATUS_RE.findall(f.get("CURRENT", ""))}
            if cur_codes and not cur_codes <= obs_nums:
                errs.append(f"{w}: CURRENT mentions {sorted(cur_codes - obs_nums)} but the probe(s) observed {sorted(obs_status or obs_nums)}")
            if rec and not none_est:
                prec = refs_in(rec)
                docs = re.search(r"laravel\.com/docs[\w/#.\-]*", rec)
                circ = list(ev_refs)
                for d in covers:
                    if d in by_id:
                        circ += refs_in(by_id[d]["source"])
                good = [(fl, ln) for fl, ln in prec
                        if not any(fl == cf and abs(ln - cl) <= NEAR_LINES for cf, cl in circ)]
                errs += ctx.check_refs(prec, w + " RECOMMENDED")
                if not docs and not good:
                    errs.append(f"{w}: RECOMMENDED needs a precedent in ANOTHER place (file.php:line, not the code under test) "
                                f"or a laravel.com/docs URL, otherwise write 'none established'")
        verdicts = {b["fields"].get("VERDICT", "").upper() for b in bl}
        pend = [b for b in bl if b["pending"]]
        norm = [b for b in bl if not b["pending"]]
        if not norm:
            errs.append(f"{eid}: needs one real (non-pending) test pinning the CURRENT behavior")
        if "DIFFERS" in verdicts:
            if not pend:
                errs.append(f"{eid}: VERDICT DIFFERS needs a second, pending test for the RECOMMENDED behavior (->todo() / markTestIncomplete)")
            if norm and not any("current-behavior" in b["text"] for b in norm):
                errs.append(f"{eid}: the CURRENT-behavior test must carry group 'current-behavior'")
        elif pend:
            errs.append(f"{eid}: pending test present but VERDICT is not DIFFERS")
        if len(bl) > 2:
            errs.append(f"{eid}: appears in {len(bl)} tests (expected 1 or 2)")
    nums = sorted(int(e[2:]) for e in edges if re.fullmatch(r"E-\d+", e))
    if nums and nums != list(range(1, len(nums) + 1)):
        errs.append(f"edge ids must be E-01..E-{len(nums):02d} without gaps; found {['E-%02d' % n for n in nums]}")
    # coverage
    dup_of = {}
    for r in rows:
        k = probe_kind(r["probe"])
        if k and k.startswith("dup:"):
            dup_of[r["id"]] = k[4:]
    for r in rows:
        k = probe_kind(r["probe"])
        if k == "no":
            continue
        target = dup_of.get(r["id"], r["id"])
        if target not in covered:
            errs.append(f"{r['id']}: not covered by any test{'' if target == r['id'] else ' (via ' + target + ')'}")
    covered_by_edge = set()
    for bl in edges.values():
        for b in bl:
            covered_by_edge |= set(D_ID_RE.findall(b["fields"].get("COVERS", "")))
    for d in state.get("mismatch_rows", []):
        if d not in covered_by_edge:
            errs.append(f"{d}: probe observed something different from the code reading; it needs an EDGE test")
    p3 = parse_iso(next(h for h in state["history"] if h["phase"] == 3)["completed_at"]).timestamp()
    for rel in owned:
        if (ctx.root / rel).stat().st_mtime < p3 - SKEW:
            warns.append(f"{rel} is older than the probe phase")
    return errs, warns, owned


def run_tests(ctx: Ctx, state: dict):
    errs, results = [], []
    if (ctx.root / "tests" / "Probes").exists():
        errs.append("tests/Probes/ still exists. Delete it (rm -r tests/Probes), then re-run gate.")
    cur = {rel: sha_text(ctx.root / rel) for rel in state.get("owned_files", {}) if (ctx.root / rel).is_file()}
    if cur != state.get("owned_files"):
        return ["test files changed after gate 4 passed; phase 4 re-opened. Run gate again."], [], "reopen"
    if errs:
        return errs, results, None
    prefix = shlex.split(state["test_cmd"])
    for rel in state["owned_files"]:
        t0 = time.time()
        try:
            p = subprocess.run(prefix + [rel], cwd=ctx.root, capture_output=True, text=True, timeout=900)
            code, out = p.returncode, (p.stdout + p.stderr)
        except FileNotFoundError as e:
            return [f"cannot run tests: {e}. Set LLTT_TEST_CMD."], results, None
        except subprocess.TimeoutExpired:
            code, out = 124, "timeout after 900s"
        tail = "\n".join(out.strip().splitlines()[-12:])
        results.append({"file": rel, "exit": code, "seconds": round(time.time() - t0, 1), "tail": tail})
        if code != 0:
            errs.append(f"{rel}: test run FAILED (exit {code}). Last output:\n{tail}")
    (ctx.trace / "run.json").write_text(json.dumps({"cmd": state["test_cmd"], "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    return errs, results, None


# ----------------------------------------------------------------------------- commands
def cmd_init(ctx: Ctx, a):
    import os
    state_file = ctx.trace / "state.json"
    if state_file.exists() and not a.reset:
        die("ALREADY INITIALISED. Use: status / next. To start over: init --reset --target ...")
    if a.reset and ctx.trace.exists():
        shutil.move(str(ctx.trace), str(ctx.root / f".trace.bak-{int(time.time())}"))
    errs = verify_manifest()
    if errs:
        die("SKILL INTEGRITY FAILED:\n" + "\n".join(" - " + e for e in errs))
    info, stops, _ = detect_env(ctx.root)
    if stops:
        die("STOP:\n" + "\n".join(" - " + s for s in stops))
    if not a.target.strip():
        die("STOP: --target must name ONE endpoint, job, command or class")
    ctx.trace.mkdir(exist_ok=True)
    (ctx.trace / "probes").mkdir(exist_ok=True)
    (ctx.trace / ".key").write_text(secrets.token_hex(24), encoding="utf-8")
    t = now()
    state = {
        "version": VERSION, "target": a.target, "type": a.type, "lang": a.lang, "keep_probes": False,
        "phase": 1, "created_at": iso(t), "phase_started_at": iso(t), "attempts": {}, "blocked": False,
        "history": [], "env": info, "test_cmd": info["test_cmd"], "snapshot": snapshot_tests(ctx.root),
        "mismatch_rows": [], "owned_files": {},
    }
    save_state(ctx, state)
    lines = [f"{k}: {v}" for k, v in info.items()]
    (ctx.trace / "env.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("INIT OK")
    print("\n".join(lines))
    print(f"\nNext: {cmd_prefix(state)} next")


def phase_def(n):
    return next(p for p in PHASES if p[0] == n)


def cmd_next(ctx: Ctx, state: dict):
    n = state["phase"]
    if state["blocked"]:
        die("BLOCKED: too many failed gate attempts. Stop and show the user the failures (run: status).")
    if n > 5:
        die(f"All phases passed. Run: {cmd_prefix(state)} finish")
    _, name, ref, outs = phase_def(n)
    body = (SKILL_DIR / "references" / ref).read_text(encoding="utf-8")
    att = state["attempts"].get(str(n), 0)
    print(f"================ PHASE {n}/5: {name.upper()} ================")
    print(f"Target: {state['target']}   (type: {state['type']})   gate attempts used: {att}/{MAX_ATTEMPTS}\n")
    print(body.strip())
    print("\nOUTPUT (the gate checks these):")
    for o in outs:
        print(f"  - {o}")
    print("\n" + STANDING_RULES)
    print(f"\nWHEN DONE, run exactly:\n  {cmd_prefix(state)} gate")


def advance(ctx: Ctx, state: dict, n: int):
    t = now()
    state["history"] = [h for h in state["history"] if h["phase"] != n]
    state["history"].append({"phase": n, "name": phase_def(n)[1], "started_at": state["phase_started_at"],
                             "completed_at": iso(t), "attempts": state["attempts"].get(str(n), 0) + 1})
    state["phase"] = n + 1
    state["phase_started_at"] = iso(t)
    state["attempts"][str(n)] = 0


def cmd_gate(ctx: Ctx, state: dict):
    if state["blocked"]:
        die("BLOCKED: too many failed gate attempts. Stop and show the user the failures (run: status).")
    n = state["phase"]
    if n > 5:
        die(f"Nothing to gate. Run: {cmd_prefix(state)} finish")
    errs = verify_manifest()
    if errs:
        die("SKILL INTEGRITY FAILED (an agent edited the skill?):\n" + "\n".join(" - " + e for e in errs))
    warns, reopen = [], False
    if n == 1:
        errs, warns = gate_trace(ctx, state)
    elif n == 2:
        errs, warns = gate_decide(ctx, state)
    elif n == 3:
        errs, warns = gate_probe(ctx, state)
    elif n == 4:
        errs, warns, owned = gate_tests(ctx, state)
        if not errs:
            state["owned_files"] = owned
    else:
        errs, _, flag = run_tests(ctx, state)
        reopen = flag == "reopen"
    for w in warns:
        print("WARN " + w)
    if errs:
        if reopen:
            state["phase"] = 4
            state["phase_started_at"] = iso(now())
        else:
            k = str(n)
            state["attempts"][k] = state["attempts"].get(k, 0) + 1
            if state["attempts"][k] >= MAX_ATTEMPTS:
                state["blocked"] = True
        save_state(ctx, state)
        for e in errs:
            print("FAIL " + e)
        print(f"\nGATE {n}: FAIL ({len(errs)}). Fix ONLY these items, then run gate again. Do not move on.")
        if state["blocked"]:
            print(f"BLOCKED: {MAX_ATTEMPTS} failed attempts. Stop and show the user the failures above.")
        sys.exit(1)
    advance(ctx, state, n)
    save_state(ctx, state)
    nxt = f"{cmd_prefix(state)} next" if state["phase"] <= 5 else f"{cmd_prefix(state)} finish"
    print(f"GATE {n}: PASS ({phase_def(n)[1]}).\nNext: {nxt}")


def cmd_status(ctx: Ctx, state: dict):
    print(f"target: {state['target']}  phase: {state['phase']}/5  blocked: {state['blocked']}")
    for h in state["history"]:
        d = (parse_iso(h["completed_at"]) - parse_iso(h["started_at"])).total_seconds()
        print(f" - phase {h['phase']} {h['name']}: passed after {h['attempts']} gate run(s), {int(d)}s")
    if state["attempts"]:
        print(f"failed attempts on open phases: { {k: v for k, v in state['attempts'].items() if v} }")


def cell(s: str) -> str:
    return s.replace("|", "/").replace("\n", " ").strip()


def cmd_finish(ctx: Ctx, state: dict):
    if state["phase"] != 6:
        die(f"NOT FINISHED: phase {state['phase']}/5 is still open. Run: {cmd_prefix(state)} next")
    errs = verify_manifest()
    if errs:
        die("SKILL INTEGRITY FAILED:\n" + "\n".join(" - " + e for e in errs))
    blocks, owned = analyze_tests(ctx, state)
    if owned != state["owned_files"]:
        die("test files changed after the run gate. Re-run gate 4 and 5.")
    L = LABELS[state["lang"]]
    rows, _ = parse_table(ctx)
    run = json.loads((ctx.trace / "run.json").read_text(encoding="utf-8"))
    edges = {}
    for b in blocks:
        if b["edge"]:
            edges.setdefault(b["edge"], []).append(b)
    ordered = sorted(edges.items(), key=lambda kv: int(kv[0][2:]))
    n_diff = n_same = n_norec = 0
    edge_lines = []
    for eid, bl in ordered:
        f = bl[0]["fields"]
        v = f["VERDICT"].upper()
        n_diff += v == "DIFFERS"
        n_same += v == "SAME"
        n_norec += v == "NO-RECOMMENDATION"
        edge_lines.append(f"| {eid} | {v} | {cell(f['CURRENT'])} | {cell(f['RECOMMENDED'])} | {cell(f['WHY'])} | {cell(f['EVIDENCE'])} |")
    probed = [r for r in rows if probe_kind(r["probe"]) == "probe"]
    skipped = [r for r in rows if probe_kind(r["probe"]) == "no"]
    total_s = int((parse_iso(state["history"][-1]["completed_at"]) - parse_iso(state["created_at"])).total_seconds())
    rep = [f"# Behavior report: {state['target']}", "",
           f"Generated by laravel-logic-trace-tests {VERSION} (`lltt.py finish`). Not hand-written.", "",
           "## Environment", ""] + [f"- {k}: {v}" for k, v in state["env"].items()]
    rep += ["", "## Test run (executed by the script)", "", f"Command prefix: `{run['cmd']}`", ""]
    for r in run["results"]:
        rep.append(f"- `{r['file']}`: exit {r['exit']} in {r['seconds']}s")
    rep += ["", "## Edge cases", "",
            "| Edge | Verdict | Current (observed) | Recommended | Why | Evidence |",
            "|------|---------|--------------------|-------------|-----|----------|"] + edge_lines
    rep += ["", "## Pending recommended tests (todo)", ""]
    pend = [eid for eid, bl in ordered if any(b["pending"] for b in bl)]
    rep += [f"- {e}" for e in pend] or ["- none"]
    rep += ["", "## Rows not tested (`no:` in the decision table)", ""]
    rep += [f"- {r['id']}: {r['probe']} ({r['cond']})" for r in skipped] or ["- none"]
    rep += ["", "## Time per phase", ""]
    for h in state["history"]:
        d = int((parse_iso(h["completed_at"]) - parse_iso(h["started_at"])).total_seconds())
        rep.append(f"- {h['name']}: {d}s ({h['attempts']} gate run(s))")
    rep.append(f"- total: {total_s}s")
    (ctx.trace / "behavior-report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    summary = {"version": VERSION, "target": state["target"], "decision_rows": len(rows), "probes": len(probed),
               "edges": len(ordered), "differs": n_diff, "total_seconds": total_s, "history": state["history"]}
    (ctx.trace / "run-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = all(r["exit"] == 0 for r in run["results"])
    print("DONE")
    print("=== FINAL ANSWER (print this block verbatim, add nothing else) ===")
    print(f"{L['summary']}: {state['target']}")
    print(f"- {len(probed)} {L['probes']}, {len(rows) - len(skipped)}/{len(rows)} {L['tested']}")
    print(f"- {L['edges']}: {len(ordered)} ({n_diff} {L['differs']}; {n_same} {L['same']}; {n_norec} {L['norec']})")
    for eid, bl in ordered:
        f = bl[0]["fields"]
        if f["VERDICT"].upper() == "DIFFERS":
            print(f"  * {eid}: {f['CURRENT']}  ->  {f['RECOMMENDED']}  ({f['WHY']})")
    print(f"- {L['nottested']}: {len(skipped)}" + ("" if not skipped else " (" + ", ".join(r['id'] for r in skipped) + ")"))
    print(f"- {L['run']}: {'PASS' if ok else 'FAIL'} ({len(run['results'])} file(s), command: {run['cmd']})")
    print(f"- {L['files']}: " + ", ".join(run_f["file"] for run_f in run["results"]))
    print(f"- {L['time']}: {total_s}s")
    print(f"- {L['report']}: .trace/behavior-report.md")
    print("=== END FINAL ANSWER ===")


def main():
    ap = argparse.ArgumentParser(prog="lltt.py")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init")
    pi.add_argument("--target", default="")
    pi.add_argument("--type", choices=["http", "job", "command"], default="http")
    pi.add_argument("--lang", choices=["en", "ar"], default="en")
    pi.add_argument("--reset", action="store_true")
    for name in ("next", "gate", "status", "finish", "verify-manifest", "make-manifest"):
        sub.add_parser(name)
    a = ap.parse_args()
    if a.cmd == "make-manifest":
        return make_manifest()
    if a.cmd == "verify-manifest":
        errs = verify_manifest()
        print("MANIFEST OK" if not errs else "\n".join(errs))
        sys.exit(1 if errs else 0)
    ctx = Ctx(Path(a.root).resolve())
    if a.cmd == "init":
        return cmd_init(ctx, a)
    state = load_state(ctx)
    {"next": cmd_next, "gate": cmd_gate, "status": cmd_status, "finish": cmd_finish}[a.cmd](ctx, state)


if __name__ == "__main__":
    main()
