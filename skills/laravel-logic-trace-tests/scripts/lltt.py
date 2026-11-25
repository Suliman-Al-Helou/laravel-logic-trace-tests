#!/usr/bin/env python3
"""lltt: workflow driver and gate for the laravel-logic-trace-tests skill (v0.3).

Two modes:
  audit  the code exists: trace -> decide -> probe -> existing -> expect -> tests -> run
  spec   no code yet:     expect -> tests -> run

The point: failing tests that fail for the RIGHT reason (an assertion about documented behavior),
based on documented expectations, never on the model's memory. The script runs the tests and proves
red (gaps fail) and green (the rest pass).

    lltt.py init --target "POST /api/orders" --mode audit --web yes
    lltt.py next | gate | status | finish | scan-tests <file>

Run from the Laravel project root (or pass --root).
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

VERSION = "0.3.0"
SELF = Path(__file__).resolve()
SKILL_DIR = SELF.parent.parent
MAX_ATTEMPTS = 5
SKEW = 3
MIN_PROBED_RATIO = 0.6

PHASE_SETS = {
    "audit": ["trace", "decide", "probe", "existing", "expect", "tests", "run"],
    "spec": ["expect", "tests", "run"],
}
PHASE_REF = {
    "trace": "01-trace.md", "decide": "02-decision-table.md", "probe": "03-probe.md",
    "existing": "04-existing-tests.md", "expect": "05-expect.md", "expect-spec": "05-expect-spec.md",
    "tests": "06-write-tests.md", "run": "07-run.md",
}
PHASE_OUT = {
    "trace": [".trace/logic-map.md"],
    "decide": [".trace/decision-table.md"],
    "probe": ["tests/Probes/*.php", ".trace/probes/P-xx.json"],
    "existing": [".trace/existing-tests.md"],
    "expect": [".trace/expectations.md"],
    "tests": ["tests/** (new tests only)"],
    "run": ["(the script runs the tests and proves red/green: .trace/run.json)"],
}
LAYERS = {
    "route", "middleware", "request", "validation", "controller", "service", "model",
    "database", "event", "job", "policy", "auth", "response", "cache", "storage",
}
DEFAULT_WEB = {
    "laravel.com", "spatie.be", "owasp.org", "phpunit.de", "pestphp.com", "php.net", "symfony.com",
    "developer.mozilla.org", "datatracker.ietf.org", "rfc-editor.org", "martinfowler.com", "github.com",
    "docs.github.com", "stackoverflow.com", "laracasts.com", "laravel-news.com", "postgresql.org",
    "mysql.com", "sqlite.org", "redis.io", "blog.ploeh.dk", "kentcdodds.com",
}
EDGE_KEYS_COMMON = ["COVERS", "KIND", "EXPECTED", "WHY", "SOURCE"]
EDGE_KEYS_AUDIT = ["CURRENT", "EVIDENCE"]

REF_RE = re.compile(r"((?:[\w.\-]+[/\\])*[\w.\-]+\.php):(\d+)")
DOC_RE = re.compile(r"^((?:[\w.\-]+[/\\])*[\w.\-]+\.(?:md|txt|rst|yml|yaml|json|php)):(\d+)$")
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
PENDING_RE = re.compile(r"->todo\(|markTestIncomplete|markTestSkipped|->skip\(")
FAKE_ASSERTS = [
    re.compile(r"assertTrue\(\s*true\s*\)"),
    re.compile(r"expect\(\s*true\s*\)\s*->toBeTrue\(\)"),
    re.compile(r"assertEquals\(\s*1\s*,\s*1\s*\)"),
]
EMPTY_SKIP = [re.compile(r"->skip\(\s*\)"), re.compile(r"markTestSkipped\(\s*\)"), re.compile(r"markTestIncomplete\(\s*\)")]
MOCK_RE = re.compile(r"(?:Mockery::mock|Mockery::spy|->mock|->spy|->partialMock)\(\s*([\\\w]+)::class")
COMMENT_KEY_RE = re.compile(
    r"^(EDGE|COVERS|KIND|CURRENT|EXPECTED|WHY|EVIDENCE|SOURCE|ALLOW-MOCK)\s*:\s*(.*)$"
)
SUCCESS_ASSERT = re.compile(r"assert(?:Ok|Created|Successful|NoContent|Accepted)\b|assertStatus\(\s*2\d\d|->toBe\(\s*2\d\d\s*\)|assertRedirect")
FAILURE_ASSERT = re.compile(
    r"assert(?:Forbidden|Unauthorized|NotFound|Invalid|JsonValidationErrors|Unprocessable|Conflict|BadRequest|"
    r"TooManyRequests|ServerError|ClientError|Unauthenticated)\b|assertStatus\(\s*[45]\d\d|->toBe\(\s*[45]\d\d|"
    r"expectException|->throws\(|toThrow|assertDatabaseMissing|assertSoftDeleted|assertNotPushed|assertNotDispatched|"
    r"assertNothingSent|assertNotSent|assertGuest|assertSessionHasErrors")
STATE_ASSERT = re.compile(
    r"assertDatabase(?:Has|Count|Missing)|assertModel(?:Exists|Missing)|->fresh\(\)|->refresh\(\)|hasRole\(|"
    r"assertEquals?\(|assertSame\(|assertCount\(|assertPushed|assertDispatched|assertJson(?:Path|Structure|Fragment)?\(|"
    r"assertExactJson|->toEqual\(|->toHaveCount\(|->toBeNull\(|->toBeTrue\(|->toBeFalse\(|->toContain\(")
STATUS_HELPERS = {
    200: "assertOk", 201: "assertCreated", 202: "assertAccepted", 204: "assertNoContent", 401: "assertUnauthorized",
    403: "assertForbidden", 404: "assertNotFound", 409: "assertConflict",
    422: "assertUnprocessable|assertInvalid|assertJsonValidationErrors|assertSessionHasErrors",
    429: "assertTooManyRequests",
}
WRONG_REASON = re.compile(
    r"Class \"[^\"]+\" not found|Call to (?:undefined|a member function)|Parse error|syntax error|Cannot declare|"
    r"Undefined (?:variable|array key|property|offset)|Target class \[[^\]]+\] does not exist|could not find driver|"
    r"Too few arguments|must be of type|Attempt to read property|Unresolvable dependency|Method .* does not exist|"
    r"Route \[[^\]]+\] not defined|Table '.*' doesn't exist|no such table", re.I)

STANDING_RULES = """\
STANDING RULES (apply in every phase)
 1. Do only what this phase says. Do not read ahead. Do not skip steps.
 2. Never edit app code, files inside the skill folder, .trace/state.json or .trace/.key.
 3. Facts about the code need a file.php:line you opened. Expected behavior needs a documented source
    (project doc with a quote, or a web page you actually opened). No source = write UNKNOWN. UNKNOWN is a valid answer.
 4. Never write "tests pass" or "tests fail" yourself. Only this script's output counts.
 5. If a gate says BLOCKED, stop and show the user the failures."""

LABELS = {
    "en": {
        "summary": "Summary", "gaps": "gaps (tests that must FAIL now)", "match": "behaviors confirmed by a source",
        "unknown": "UNKNOWN (no source found, needs your decision)", "existing": "Existing tests",
        "run": "Red/green proof", "report": "Full report", "time": "Time", "files": "Test files", "web": "Web research",
        "questions": "Questions for you", "none": "none", "new": "rules with new tests (must FAIL now)",
    },
    "ar": {
        "summary": "الملخص", "gaps": "فجوات (اختبارات يجب أن تفشل الآن)", "match": "سلوكيات مؤكدة بمصدر",
        "unknown": "غير معروف (لا مصدر، يحتاج قرارك)", "existing": "الاختبارات الموجودة",
        "run": "إثبات الفشل والنجاح", "report": "التقرير الكامل", "time": "الوقت", "files": "ملفات الاختبار",
        "web": "البحث في الويب", "questions": "أسئلة لك", "none": "لا يوجد",
        "new": "قواعد باختبارات جديدة (يجب أن تفشل الآن)",
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
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_lines(path: Path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def die(msg: str, code: int = 1):
    print(msg)
    sys.exit(code)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().strip("`").strip()


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

    def window(self, rel: str, line: int, before: int = 3, after: int = 3) -> str:
        lines = read_lines(self.root / rel)
        return norm(" ".join(lines[max(0, line - 1 - before): line + after]))


# ----------------------------------------------------------------------------- manifest
def manifest_files():
    files = [SKILL_DIR / "SKILL.md", SELF]
    for sub in ("references", "assets"):
        d = SKILL_DIR / sub
        if d.is_dir():
            files += sorted(p for p in d.iterdir() if p.is_file())
    return files


def make_manifest():
    lines = [f"{sha_text(p)}  {p.relative_to(SKILL_DIR).as_posix()}" for p in manifest_files() if p.is_file()]
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
        die("NOT INITIALISED. Run: init --target \"<endpoint or class>\" --mode audit|spec --web yes|no")
    state = json.loads(sf.read_text(encoding="utf-8"))
    if not hmac.compare_digest(state.get("sig", ""), sign(state, read_key(ctx))):
        die("STATE TAMPERED: .trace/state.json was edited by hand. Run: init --reset")
    return state


def cmd_prefix() -> str:
    return f"python3 {SELF}"


def cur_name(state):
    n = state["phase"]
    return state["phases"][n - 1] if 1 <= n <= len(state["phases"]) else None


def hist(state, name):
    return next((h for h in state["history"] if h["name"] == name), None)


# ----------------------------------------------------------------------------- environment
def run_quiet(cmd, cwd):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
        return (p.stdout + p.stderr).strip()
    except Exception:
        return ""


def detect_env(root: Path):
    info, stops = {}, []
    if not (root / "artisan").is_file():
        stops.append("no 'artisan' file here. Run from the Laravel project root (or pass --root).")
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
    return info, stops


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


def classify(text: str) -> dict:
    s = bool(SUCCESS_ASSERT.search(text))
    f = bool(FAILURE_ASSERT.search(text))
    st = bool(STATE_ASSERT.search(text))
    if not ASSERT_RE.search(text):
        label = "no-assert"
    elif s and not f and not st:
        label = "success-only"
    else:
        label = "checks-more-than-success"
    return {"success": s, "failure": f, "state": st, "label": label}


def cmd_scan_tests(ctx: Ctx, paths):
    targets = []
    for p in paths or []:
        pp = (ctx.root / p) if not Path(p).is_absolute() else Path(p)
        targets += sorted(pp.rglob("*.php")) if pp.is_dir() else [pp]
    if not targets:
        die("usage: scan-tests <file-or-folder> [...]")
    for f in targets:
        if not f.is_file():
            print(f"NOT FOUND {f}")
            continue
        rel = f.relative_to(ctx.root).as_posix() if str(f).startswith(str(ctx.root)) else str(f)
        for b in parse_blocks(read_lines(f)):
            c = classify(b["text"])
            flags = ",".join(k for k in ("success", "failure", "state") if c[k]) or "-"
            print(f"{rel}:{b['start'] + 1}  [{c['label']}]  asserts:{flags}  {b['name'][:70]}")


# ----------------------------------------------------------------------------- tables
def parse_md_table(path: Path, ncols: int, header_first: str):
    rows, errs, header = [], [], False
    if not path.is_file():
        return rows, [f"{path.name} is missing"]
    for ln in read_lines(path):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if cells and cells[0].upper() == header_first.upper():
            header = True
            if len(cells) != ncols:
                errs.append(f"{path.name}: table header must have {ncols} columns")
            continue
        if len(cells) != ncols:
            errs.append(f"{path.name}: malformed row (need {ncols} columns, snippets and text must not contain '|'): {s[:70]}")
            continue
        rows.append(cells)
    if not header:
        errs.append(f"{path.name}: table header row not found")
    return rows, errs


def parse_decisions(ctx: Ctx):
    cells, errs = parse_md_table(ctx.trace / "decision-table.md", 7, "ID")
    rows = [{"id": c[0], "layer": c[1].lower(), "cond": c[2], "outcome": c[3], "source": c[4], "snippet": c[5], "probe": c[6]}
            for c in cells]
    return rows, errs


def parse_expect(ctx: Ctx):
    cells, errs = parse_md_table(ctx.trace / "expectations.md", 6, "ID")
    rows = [{"id": c[0], "expected": c[1], "type": c[2].lower(), "source": c[3], "quote": c[4], "verdict": c[5].upper()}
            for c in cells]
    return rows, errs


def parse_existing(ctx: Ctx):
    cells, errs = parse_md_table(ctx.trace / "existing-tests.md", 4, "ID")
    rows = [{"id": c[0], "test": c[1], "strength": c[2].upper(), "reason": c[3]} for c in cells]
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
    if len(set(all_refs)) < need:
        errs.append(f"the map cites only {len(set(all_refs))} distinct file:line sources (minimum {need})")
    return errs, []


def gate_decide(ctx: Ctx, state: dict):
    errs, warns = [], []
    rows, e0 = parse_decisions(ctx)
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
    probe_ids, source_refs, probed = [], [], 0
    for r in rows:
        w = r["id"]
        if r["layer"] not in LAYERS:
            errs.append(f"{w}: layer '{r['layer']}' not in {sorted(LAYERS)}")
        refs = refs_in(r["source"])
        if not refs:
            errs.append(f"{w}: Source needs a file.php:line")
        else:
            bad = ctx.check_refs(refs, w)
            errs += bad
            source_refs += refs
            snip = norm(r["snippet"])
            if not (6 <= len(snip) <= 120):
                errs.append(f"{w}: Snippet must be 6 to 120 characters copied from the cited line")
            elif not bad:
                f, l = refs[0]
                if snip not in ctx.window(f, l):
                    errs.append(f"{w}: Snippet not found near {f}:{l} (copy the code verbatim, within 3 lines of the cited line)")
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
    nb_files, nb_lines = set(), set()
    for m in re.finditer(r"^[-*]\s*(app/[\w/.\-]+\.php)(?::(\d+))?:\s*(.+)$", text, re.M):
        if len(m.group(3).split()) < 3:
            errs.append(f"NO-BRANCH entry for {m.group(1)} needs a reason of at least 3 words")
        if m.group(2):
            nb_lines.add((m.group(1), int(m.group(2))))
        else:
            nb_files.add(m.group(1))
    map_text = (ctx.trace / "logic-map.md").read_text(encoding="utf-8")
    for f, l in sorted(set(refs_in(map_text))):
        if not f.startswith("app/") or f in nb_files:
            continue
        near_row = any(f == sf and abs(l - sl) <= 2 for sf, sl in source_refs)
        near_nb = any(f == nf and abs(l - nl) <= 2 for nf, nl in nb_lines)
        if not (near_row or near_nb):
            errs.append(f"{f}:{l} is in the logic map but no decision row cites it (within 2 lines). "
                        f"Add a row, or '- {f}:{l}: <reason>' under ## NO-BRANCH")
    return errs, warns


def gate_probe(ctx: Ctx, state: dict):
    errs, warns = [], []
    rows, _ = parse_decisions(ctx)
    key = read_key(ctx)
    phase2_done = parse_iso(hist(state, "decide")["completed_at"])
    pdir = ctx.root / "tests" / "Probes"
    src_ids = set()
    if pdir.is_dir():
        for f in pdir.rglob("*.php"):
            src_ids |= set(re.findall(r"['\"](P-\d+)['\"]", f.read_text(encoding="utf-8", errors="replace")))
    else:
        errs.append("tests/Probes/ does not exist: probes must be tests that call ProbeRecorder::save(...)")
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
            warns.append(f"{w}: code reading says {sorted(codes)} but the probe observed {sorted(sv)}. Keep this surprise in mind for the expect phase.")
        elif codes and not sv:
            warns.append(f"{w}: Code outcome mentions {sorted(codes)} but the probe has no status key. Add 'status' to observed.")
    pf = ctx.trace / "probes"
    if pf.is_dir():
        for f in sorted(pf.glob("P-*.json")):
            if f.stem not in seen:
                warns.append(f"orphan probe file {f.name} (not referenced by the decision table)")
    return errs, warns


def gate_existing(ctx: Ctx, state: dict):
    errs, warns = [], []
    drows, _ = parse_decisions(ctx)
    rows, e0 = parse_existing(ctx)
    errs += e0
    if e0 and not rows:
        return errs, warns
    want = [r["id"] for r in drows]
    got = [r["id"] for r in rows]
    for d in want:
        if d not in got:
            errs.append(f"{d}: no entry in existing-tests.md (write NONE if no existing test covers it)")
    for d in got:
        if d not in want:
            errs.append(f"{d}: not a decision row")
        if got.count(d) > 1:
            errs.append(f"{d}: appears more than once")
    snap = state.get("snapshot", {})
    result = {}
    for r in rows:
        w = r["id"]
        if r["strength"] not in ("STRONG", "WEAK", "NONE"):
            errs.append(f"{w}: Strength must be STRONG, WEAK or NONE")
            continue
        if len(r["reason"].split()) < 3:
            errs.append(f"{w}: Reason needs at least 3 words")
        result[w] = r["strength"]
        if r["strength"] == "NONE":
            if r["test"] != "-":
                errs.append(f"{w}: NONE must have '-' in the Existing test column")
            continue
        m = re.fullmatch(r"((?:[\w.\-]+/)*[\w.\-]+\.php):(\d+)", r["test"])
        if not m:
            errs.append(f"{w}: Existing test must be tests/path/File.php:line")
            continue
        rel, line = m.group(1), int(m.group(2))
        if rel not in snap:
            errs.append(f"{w}: {rel} was not a test file when the run started")
            continue
        blocks = parse_blocks(read_lines(ctx.root / rel))
        hit = next((b for b in blocks if b["start"] + 1 <= line <= b["end"] and b["name"] in snap[rel]["blocks"]), None)
        if hit is None:
            errs.append(f"{w}: {rel}:{line} is not inside an existing test")
            continue
        c = classify(hit["text"])
        if c["label"] == "no-assert":
            errs.append(f"{w}: the cited test has no assertion")
        elif r["strength"] == "STRONG" and c["label"] == "success-only":
            errs.append(f"{w}: labelled STRONG but '{hit['name'][:40]}' only asserts a success status. Label it WEAK.")
    state["existing"] = result
    return errs, warns


def host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    allow = set(DEFAULT_WEB) | {h.strip().lower() for h in os.environ.get("LLTT_WEB_ALLOW", "").split(",") if h.strip()}
    return any(host == d or host.endswith("." + d) for d in allow)


def gate_expect(ctx: Ctx, state: dict):
    errs, warns = [], []
    audit = state["mode"] == "audit"
    rows, e0 = parse_expect(ctx)
    errs += e0
    if e0 and not rows:
        return errs, warns
    allowed = {"MATCH", "GAP", "UNKNOWN"} if audit else {"NEW", "UNKNOWN"}
    dmap = {}
    if audit:
        drows, _ = parse_decisions(ctx)
        dmap = {r["id"]: r for r in drows}
        want = {r["id"] for r in drows if probe_kind(r["probe"]) == "probe"}
        have = {r["id"] for r in rows}
        for d in sorted(want - have):
            errs.append(f"{d}: probed decision row has no expectation (write UNKNOWN if you found no source)")
        for d in sorted(have - want):
            errs.append(f"{d}: expectation for a row that is not a probed decision row")
    else:
        if len(rows) < 3:
            errs.append(f"only {len(rows)} rules (minimum 3)")
        for i, r in enumerate(rows, 1):
            if r["id"] != f"D-{i:02d}":
                errs.append(f"rule ids must be sequential D-01, D-02, ...; found {r['id']} at position {i}")
                break
    ids = [r["id"] for r in rows]
    web_used = 0
    unknown_ids = []
    for r in rows:
        w = r["id"]
        if ids.count(w) > 1:
            errs.append(f"{w}: appears more than once")
        if not r["expected"] or PLACEHOLDER_RE.search(r["expected"]):
            errs.append(f"{w}: Expected is empty or a placeholder")
        if r["verdict"] not in allowed:
            errs.append(f"{w}: Verdict must be one of {sorted(allowed)} in {state['mode']} mode")
        if r["type"] not in ("doc", "web", "unknown"):
            errs.append(f"{w}: Type must be doc, web or unknown")
            continue
        if (r["type"] == "unknown") != (r["verdict"] == "UNKNOWN"):
            errs.append(f"{w}: Type unknown and Verdict UNKNOWN must go together")
        if r["type"] == "unknown":
            unknown_ids.append(w)
            if r["source"] != "-" or r["quote"] != "-":
                errs.append(f"{w}: unknown rows use '-' in Source and Quote")
            continue
        words = len(r["quote"].split())
        if not r["quote"] or r["quote"] == "-" or words > 25:
            errs.append(f"{w}: Quote must be a verbatim excerpt of at most 25 words")
        if r["type"] == "doc":
            m = DOC_RE.match(r["source"])
            if not m:
                errs.append(f"{w}: doc Source must be path/to/doc.md:line")
            else:
                rel, line = m.group(1).replace("\\", "/"), int(m.group(2))
                f = ctx.root / rel
                if not f.is_file():
                    errs.append(f"{w}: doc not found: {rel}")
                elif not (1 <= line <= len(read_lines(f))):
                    errs.append(f"{w}: doc line out of range: {rel}:{line}")
                elif norm(r["quote"]) not in ctx.window(rel, line, 4, 4):
                    errs.append(f"{w}: Quote not found near {rel}:{line} (copy it verbatim)")
        else:
            web_used += 1
            if not state.get("web"):
                errs.append(f"{w}: web sources are disabled for this run (init --web no). Use a project doc or UNKNOWN.")
            elif not r["source"].startswith("https://"):
                errs.append(f"{w}: web Source must be an https:// URL of a page you opened")
            elif not host_allowed(r["source"]):
                errs.append(f"{w}: host not in the allowed list. Use laravel.com, owasp.org, etc., or the user sets LLTT_WEB_ALLOW")
        if audit and w in dmap:
            d = dmap[w]
            ecodes = {int(c) for c in STATUS_RE.findall(r["expected"])}
            ccodes = {int(c) for c in STATUS_RE.findall(d["outcome"])}
            probe, _ = load_probe(ctx, d["probe"]) if probe_kind(d["probe"]) == "probe" else (None, None)
            sv = status_values((probe or {}).get("observed", {}))
            if r["verdict"] == "MATCH":
                if ecodes and ccodes and ecodes != ccodes:
                    errs.append(f"{w}: marked MATCH but Expected status {sorted(ecodes)} differs from Code outcome {sorted(ccodes)}")
                if ecodes and sv and not ecodes <= sv:
                    errs.append(f"{w}: marked MATCH but the probe observed {sorted(sv)}, not {sorted(ecodes)}")
            elif r["verdict"] == "GAP" and ecodes and sv and ecodes <= sv and ecodes == ccodes:
                warns.append(f"{w}: marked GAP but the status codes are identical. Say precisely what differs in Expected.")
    if state.get("web") and web_used == 0 and rows:
        errs.append("web research is enabled but no row uses a web source. Search the web for the documented behavior, "
                    "or run init --reset with --web no if you have no web tool.")
    text = (ctx.trace / "expectations.md").read_text(encoding="utf-8")
    qs = {m.group(1): m.group(2) for m in re.finditer(r"^[-*]\s*(D-\d+):\s*(.+)$", text, re.M)}
    for d in unknown_ids:
        if d not in qs or len(qs[d].split()) < 4:
            errs.append(f"{d}: UNKNOWN needs a line under '## QUESTIONS': '- {d}: <question to the user, 4+ words>'")
    return errs, warns


def analyze_tests(ctx: Ctx, state: dict):
    snap = state.get("snapshot", {})
    owned_files, blocks = {}, []
    for p in list_test_files(ctx.root):
        rel = p.relative_to(ctx.root).as_posix()
        old = snap.get(rel)
        for b in parse_blocks(read_lines(p)):
            if old is not None and b["name"] in old["blocks"]:
                continue
            edge, fields = parse_fields(b["comments"])
            b.update({"file": rel, "line": b["start"] + 1, "edge": edge, "fields": fields,
                      "pending": bool(PENDING_RE.search(b["text"]))})
            blocks.append(b)
            owned_files[rel] = sha_text(p)
    return blocks, owned_files


def asserts_status(text: str, code: int) -> bool:
    if str(code) in text:
        return True
    helper = STATUS_HELPERS.get(code)
    return bool(helper and re.search(helper, text))


def gate_tests(ctx: Ctx, state: dict):
    errs, warns = [], []
    audit = state["mode"] == "audit"
    want_kind = "GAP" if audit else "NEW"
    erows, _ = parse_expect(ctx)
    emap = {r["id"]: r for r in erows}
    dmap = {}
    if audit:
        drows, _ = parse_decisions(ctx)
        dmap = {r["id"]: r for r in drows}
    blocks, owned = analyze_tests(ctx, state)
    if not blocks:
        return ["no new tests found since init (tests already present at init do not count)"], [], {}
    traced = set()
    if audit:
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
            if d not in emap:
                errs.append(f"{w}: COVERS {d} has no row in expectations.md")
            elif emap[d]["verdict"] == "UNKNOWN":
                errs.append(f"{w}: {d} is UNKNOWN (no source). Do not write a test for it, ask the user.")
        edge_block = bool(b["edge"])
        if not b["pending"] or edge_block:
            if not ASSERT_RE.search(b["text"]) and not b["pending"]:
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
        if edge_block:
            edges.setdefault(b["edge"], []).append(b)
    for eid, bl in edges.items():
        if not re.fullmatch(r"E-\d+", eid):
            errs.append(f"{bl[0]['file']}:{bl[0]['line']}: edge id '{eid}' must look like E-01")
            continue
        if len(bl) > 1:
            errs.append(f"{eid}: appears in {len(bl)} tests (one failing test per edge)")
        for b in bl:
            w = f"{b['file']}:{b['line']} {eid}"
            f = b["fields"]
            for k in EDGE_KEYS_COMMON + (EDGE_KEYS_AUDIT if audit else []):
                if not f.get(k, "").strip():
                    errs.append(f"{w}: missing '// {k}:'")
            for k in ("CURRENT", "EXPECTED", "WHY"):
                if PLACEHOLDER_RE.search(f.get(k, "")):
                    errs.append(f"{w}: {k} contains a placeholder")
            why = f.get("WHY", "")
            if len(why) > 200 or why.count(". ") >= 1:
                errs.append(f"{w}: WHY must be ONE short sentence (max 200 chars)")
            if f.get("KIND", "").upper() != want_kind:
                errs.append(f"{w}: KIND must be {want_kind} in {state['mode']} mode")
            if b["pending"]:
                errs.append(f"{w}: a {want_kind} test must be a REAL failing test, not todo/skip/incomplete")
            covers = D_ID_RE.findall(f.get("COVERS", ""))
            expected_codes = {int(c) for c in STATUS_RE.findall(f.get("EXPECTED", ""))}
            for d in covers:
                row = emap.get(d)
                if row is None:
                    continue
                if row["verdict"] != want_kind:
                    errs.append(f"{w}: {d} has verdict {row['verdict']} in expectations.md, so it is not a {want_kind} test")
                    continue
                if norm(f.get("SOURCE", "")) != norm(row["source"]):
                    errs.append(f"{w}: SOURCE must equal the Source of {d} in expectations.md ({row['source']})")
                row_codes = {int(c) for c in STATUS_RE.findall(row["expected"])}
                if row_codes != expected_codes:
                    errs.append(f"{w}: EXPECTED status {sorted(expected_codes)} differs from expectations.md {sorted(row_codes)}")
            body = b["text"].replace(b["name"], "", 1)  # a status number in the test title is not an assertion
            for code in expected_codes:
                if not asserts_status(body, code):
                    errs.append(f"{w}: EXPECTED mentions {code} but the test never asserts it. The test must assert the EXPECTED behavior.")
            if audit:
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
                    d = next((r for r in dmap.values() if r["probe"] == pid), None)
                    if d is None:
                        errs.append(f"{w}: probe {pid} is not a probe of the decision table")
                        continue
                    pdata, _ = load_probe(ctx, pid)
                    pdata = pdata or {}
                    if d["id"] not in covers:
                        errs.append(f"{w}: probe {pid} was recorded for {d['id']} but this test COVERS {', '.join(covers) or 'nothing'}")
                    obs_nums |= numbers_in(pdata.get("observed", {}))
                    obs_status |= status_values(pdata.get("observed", {}))
                cur_codes = {int(c) for c in STATUS_RE.findall(f.get("CURRENT", ""))}
                if cur_codes and not cur_codes <= obs_nums:
                    errs.append(f"{w}: CURRENT mentions {sorted(cur_codes - obs_nums)} but the probe(s) observed {sorted(obs_status or obs_nums)}")
    nums = sorted(int(e[2:]) for e in edges if re.fullmatch(r"E-\d+", e))
    if nums and nums != list(range(1, len(nums) + 1)):
        errs.append(f"edge ids must be E-01..E-{len(nums):02d} without gaps; found {['E-%02d' % n for n in nums]}")
    existing = state.get("existing", {})
    edge_cov = set()
    for bl in edges.values():
        for b in bl:
            edge_cov |= set(D_ID_RE.findall(b["fields"].get("COVERS", "")))
    for r in erows:
        d, v = r["id"], r["verdict"]
        if v in ("GAP", "NEW") and d not in edge_cov:
            errs.append(f"{d}: verdict {v} needs a failing test with a full EDGE block (// EDGE: E-xx)")
        elif v == "MATCH" and d not in covered and existing.get(d) != "STRONG":
            errs.append(f"{d}: MATCH row has no new test and no STRONG existing test")
    if audit:
        p3 = parse_iso(hist(state, "probe")["completed_at"]).timestamp()
        for rel in owned:
            if (ctx.root / rel).stat().st_mtime < p3 - SKEW:
                warns.append(f"{rel} is older than the probe phase")
    return errs, warns, owned


def parse_junit(path: Path):
    out = {}
    root = ET.parse(path).getroot()
    for tc in root.iter("testcase"):
        name = tc.get("name") or ""
        status, msg = "pass", ""
        for child in tc:
            tag = child.tag.lower()
            if tag in ("failure", "error", "skipped"):
                status = tag
                msg = (child.get("message") or child.text or "").strip()
                break
        out[name] = {"status": status, "message": msg}
    return out


def find_case(cases: dict, title: str):
    t = norm(title)
    for name, v in cases.items():
        if t == norm(name) or t in norm(name):
            return v
    return None


def run_tests(ctx: Ctx, state: dict):
    errs, results = [], []
    if (ctx.root / "tests" / "Probes").exists():
        errs.append("tests/Probes/ still exists. Delete it (rm -r tests/Probes), then re-run gate.")
    cur = {rel: sha_text(ctx.root / rel) for rel in state.get("owned_files", {}) if (ctx.root / rel).is_file()}
    if cur != state.get("owned_files"):
        return ["test files changed after the tests gate passed; that phase is re-opened. Run gate again."], [], "reopen"
    if errs:
        return errs, results, None
    prefix = shlex.split(state["test_cmd"])
    blocks, _ = analyze_tests(ctx, state)
    want_kind = "GAP" if state["mode"] == "audit" else "NEW"
    by_file = {}
    for b in blocks:
        by_file.setdefault(b["file"], []).append(b)
    for i, rel in enumerate(state["owned_files"], 1):
        xml = ctx.trace / f"junit-{i}.xml"
        if xml.exists():
            xml.unlink()
        t0 = time.time()
        try:
            p = subprocess.run(prefix + [f"--log-junit={xml}", rel], cwd=ctx.root, capture_output=True, text=True, timeout=900)
            code, out = p.returncode, p.stdout + p.stderr
        except FileNotFoundError as e:
            return [f"cannot run tests: {e}. Set LLTT_TEST_CMD."], results, None
        except subprocess.TimeoutExpired:
            code, out = 124, "timeout after 900s"
        secs = round(time.time() - t0, 1)
        if not xml.is_file():
            errs.append(f"{rel}: the runner produced no JUnit XML (exit {code}). Last output:\n" +
                        "\n".join(out.strip().splitlines()[-8:]))
            continue
        try:
            cases = parse_junit(xml)
        except ET.ParseError:
            errs.append(f"{rel}: JUnit XML is not valid")
            continue
        entries = []
        for b in by_file.get(rel, []):
            exp_fail = bool(b["edge"]) and b["fields"].get("KIND", "").upper() == want_kind
            case = find_case(cases, b["name"])
            w = f"{rel}:{b['line']} '{b['name'][:50]}'"
            if case is None:
                errs.append(f"{w}: the runner did not report this test")
                continue
            st, msg = case["status"], case["message"]
            entries.append({"test": b["name"], "line": b["line"], "expected": "FAIL" if exp_fail else "PASS",
                            "status": st, "message": msg[:200]})
            if exp_fail:
                if st == "pass":
                    errs.append(f"{w}: expected to FAIL (a gap) but PASSED. The behavior already works, or the test asserts the current behavior.")
                elif st == "skipped":
                    errs.append(f"{w}: expected to FAIL but was skipped")
                elif st == "error":
                    errs.append(f"{w}: errored instead of failing an assertion: {msg[:120]}")
                elif WRONG_REASON.search(msg):
                    errs.append(f"{w}: fails for the WRONG reason (not an assertion about behavior): {msg[:120]}")
            elif st != "pass":
                errs.append(f"{w}: expected to PASS but {st}: {msg[:120]}")
        results.append({"file": rel, "exit": code, "seconds": secs, "tests": entries})
    (ctx.trace / "run.json").write_text(json.dumps({"cmd": state["test_cmd"], "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    return errs, results, None


GATES = {
    "trace": gate_trace, "decide": gate_decide, "probe": gate_probe, "existing": gate_existing,
    "expect": gate_expect,
}


# ----------------------------------------------------------------------------- commands
def cmd_init(ctx: Ctx, a):
    state_file = ctx.trace / "state.json"
    if state_file.exists() and not a.reset:
        die("ALREADY INITIALISED. Use: status / next. To start over: init --reset --target ...")
    errs = verify_manifest()
    if errs:
        die("SKILL INTEGRITY FAILED:\n" + "\n".join(" - " + e for e in errs))
    info, stops = detect_env(ctx.root)
    if stops:
        die("STOP:\n" + "\n".join(" - " + s for s in stops))
    if not a.target.strip():
        die("STOP: --target must name ONE endpoint, job, command or class")
    if a.reset and ctx.trace.exists():
        shutil.move(str(ctx.trace), str(ctx.root / f".trace.bak-{int(time.time())}"))
    ctx.trace.mkdir(exist_ok=True)
    (ctx.trace / "probes").mkdir(exist_ok=True)
    (ctx.trace / ".key").write_text(secrets.token_hex(24), encoding="utf-8")
    t = now()
    state = {
        "version": VERSION, "target": a.target, "type": a.type, "lang": a.lang, "mode": a.mode, "web": a.web == "yes",
        "phases": PHASE_SETS[a.mode], "phase": 1, "created_at": iso(t), "phase_started_at": iso(t), "attempts": {},
        "blocked": False, "history": [], "env": info, "test_cmd": info["test_cmd"], "snapshot": snapshot_tests(ctx.root),
        "existing": {}, "owned_files": {},
    }
    save_state(ctx, state)
    lines = [f"{k}: {v}" for k, v in info.items()] + [f"mode: {a.mode}", f"web research: {a.web}"]
    (ctx.trace / "env.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("INIT OK")
    print("\n".join(lines))
    print(f"\nNext: {cmd_prefix()} next")


def cmd_next(ctx: Ctx, state: dict):
    if state["blocked"]:
        die("BLOCKED: too many failed gate attempts. Stop and show the user the failures (run: status).")
    name = cur_name(state)
    if name is None:
        die(f"All phases passed. Run: {cmd_prefix()} finish")
    n, total = state["phase"], len(state["phases"])
    refkey = "expect-spec" if (name == "expect" and state["mode"] == "spec") else name
    body = (SKILL_DIR / "references" / PHASE_REF[refkey]).read_text(encoding="utf-8")
    att = state["attempts"].get(name, 0)
    print(f"================ PHASE {n}/{total}: {name.upper()} ({state['mode']} mode) ================")
    print(f"Target: {state['target']}   gate attempts used: {att}/{MAX_ATTEMPTS}   web research: {'YES' if state['web'] else 'NO'}\n")
    print(body.strip())
    print("\nOUTPUT (the gate checks these):")
    for o in PHASE_OUT[name]:
        print(f"  - {o}")
    print("\n" + STANDING_RULES)
    print(f"\nWHEN DONE, run exactly:\n  {cmd_prefix()} gate")


def advance(state: dict):
    name = cur_name(state)
    t = now()
    state["history"] = [h for h in state["history"] if h["name"] != name]
    state["history"].append({"phase": state["phase"], "name": name, "started_at": state["phase_started_at"],
                             "completed_at": iso(t), "attempts": state["attempts"].get(name, 0) + 1})
    state["phase"] += 1
    state["phase_started_at"] = iso(t)
    state["attempts"][name] = 0


def cmd_gate(ctx: Ctx, state: dict):
    if state["blocked"]:
        die("BLOCKED: too many failed gate attempts. Stop and show the user the failures (run: status).")
    name = cur_name(state)
    if name is None:
        die(f"Nothing to gate. Run: {cmd_prefix()} finish")
    errs = verify_manifest()
    if errs:
        die("SKILL INTEGRITY FAILED (an agent edited the skill?):\n" + "\n".join(" - " + e for e in errs))
    warns, reopen = [], False
    if name in GATES:
        errs, warns = GATES[name](ctx, state)
    elif name == "tests":
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
            state["phase"] = state["phases"].index("tests") + 1
            state["phase_started_at"] = iso(now())
        else:
            state["attempts"][name] = state["attempts"].get(name, 0) + 1
            if state["attempts"][name] >= MAX_ATTEMPTS:
                state["blocked"] = True
        save_state(ctx, state)
        for e in errs:
            print("FAIL " + e)
        print(f"\nGATE {name}: FAIL ({len(errs)}). Fix ONLY these items, then run gate again. Do not move on.")
        if state["blocked"]:
            print(f"BLOCKED: {MAX_ATTEMPTS} failed attempts. Stop and show the user the failures above.")
        sys.exit(1)
    advance(state)
    save_state(ctx, state)
    nxt = f"{cmd_prefix()} next" if cur_name(state) else f"{cmd_prefix()} finish"
    print(f"GATE {name}: PASS.\nNext: {nxt}")


def cmd_status(ctx: Ctx, state: dict):
    print(f"target: {state['target']}  mode: {state['mode']}  phase: {state['phase']}/{len(state['phases'])} "
          f"({cur_name(state) or 'done'})  blocked: {state['blocked']}")
    for h in state["history"]:
        d = (parse_iso(h["completed_at"]) - parse_iso(h["started_at"])).total_seconds()
        print(f" - {h['name']}: passed after {h['attempts']} gate run(s), {int(d)}s")
    open_att = {k: v for k, v in state["attempts"].items() if v}
    if open_att:
        print(f"failed attempts on open phases: {open_att}")


def cell(s: str) -> str:
    return s.replace("|", "/").replace("\n", " ").strip()


def cmd_finish(ctx: Ctx, state: dict):
    if cur_name(state) is not None:
        die(f"NOT FINISHED: phase '{cur_name(state)}' is still open. Run: {cmd_prefix()} next")
    errs = verify_manifest()
    if errs:
        die("SKILL INTEGRITY FAILED:\n" + "\n".join(" - " + e for e in errs))
    blocks, owned = analyze_tests(ctx, state)
    if owned != state["owned_files"]:
        die("test files changed after the run gate. Re-run the gates.")
    audit = state["mode"] == "audit"
    want_kind = "GAP" if audit else "NEW"
    L = LABELS[state["lang"]]
    erows, _ = parse_expect(ctx)
    run = json.loads((ctx.trace / "run.json").read_text(encoding="utf-8"))
    counts = {"MATCH": 0, "GAP": 0, "NEW": 0, "UNKNOWN": 0}
    for r in erows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    edge_blocks = sorted((b for b in blocks if b["edge"]), key=lambda b: int(b["edge"][2:]))
    red = {}
    for res in run["results"]:
        for t in res["tests"]:
            red[(res["file"], t["line"])] = t
    qs = {m.group(1): m.group(2) for m in re.finditer(r"^[-*]\s*(D-\d+):\s*(.+)$",
                                                     (ctx.trace / "expectations.md").read_text(encoding="utf-8"), re.M)}
    unknown = [r for r in erows if r["verdict"] == "UNKNOWN"]
    n_fail_ok = sum(1 for res in run["results"] for t in res["tests"] if t["expected"] == "FAIL" and t["status"] == "failure")
    n_pass_ok = sum(1 for res in run["results"] for t in res["tests"] if t["expected"] == "PASS" and t["status"] == "pass")
    web_rows = [r for r in erows if r["type"] == "web"]
    existing = state.get("existing", {})
    ex_counts = {k: sum(1 for v in existing.values() if v == k) for k in ("STRONG", "WEAK", "NONE")}
    total_s = int((parse_iso(state["history"][-1]["completed_at"]) - parse_iso(state["created_at"])).total_seconds())
    rep = [f"# Behavior report: {state['target']}", "",
           f"Generated by laravel-logic-trace-tests {VERSION} (`lltt.py finish`, mode: {state['mode']}). Not hand-written.", "",
           "## Result", "",
           f"- {n_fail_ok} test(s) fail as intended (red, failed assertion), {n_pass_ok} pass (green)",
           f"- verdicts: {counts}",
           f"- web sources: {len(web_rows)} (URLs and quotes are NOT verified by the script; open them to confirm)"]
    if audit:
        rep.append(f"- existing tests for the decision rows: {ex_counts}")
    rep += ["", "## Failing tests (gaps)" if audit else "## Failing tests (new rules)", "",
            "| Edge | Row | Current | Expected | Why | Source | Red proof |",
            "|------|-----|---------|----------|-----|--------|-----------|"]
    for b in edge_blocks:
        f = b["fields"]
        t = red.get((b["file"], b["line"]), {})
        rep.append(f"| {b['edge']} | {cell(f['COVERS'])} | {cell(f.get('CURRENT', '-'))} | {cell(f['EXPECTED'])} | "
                   f"{cell(f['WHY'])} | {cell(f['SOURCE'])} | {cell(t.get('message', '')[:90])} |")
    rep += ["", "## UNKNOWN (no source found, needs a decision)", ""]
    rep += [f"- {r['id']}: {r['expected']} / question: {qs.get(r['id'], '')}" for r in unknown] or ["- none"]
    rep += ["", "## Test run (executed by the script)", "", f"Command prefix: `{run['cmd']}`", ""]
    for r in run["results"]:
        rep.append(f"- `{r['file']}`: {r['seconds']}s")
    rep += ["", "## Environment", ""] + [f"- {k}: {v}" for k, v in state["env"].items()]
    rep += ["", "## Time per phase", ""]
    for h in state["history"]:
        d = int((parse_iso(h["completed_at"]) - parse_iso(h["started_at"])).total_seconds())
        rep.append(f"- {h['name']}: {d}s ({h['attempts']} gate run(s))")
    rep.append(f"- total: {total_s}s")
    (ctx.trace / "behavior-report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    (ctx.trace / "run-summary.json").write_text(json.dumps(
        {"version": VERSION, "target": state["target"], "mode": state["mode"], "verdicts": counts,
         "red_ok": n_fail_ok, "green_ok": n_pass_ok, "total_seconds": total_s, "history": state["history"]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print("DONE")
    print("=== FINAL ANSWER (print this block verbatim, add nothing else) ===")
    print(f"{L['summary']}: {state['target']} ({state['mode']})")
    gl = L["gaps"] if audit else L["new"]
    print(f"- {gl}: {counts['GAP'] + counts['NEW']}")
    for b in edge_blocks:
        f = b["fields"]
        cur = f"{f.get('CURRENT', '')}  ->  " if audit else ""
        print(f"  * {b['edge']} [{f['COVERS']}]: {cur}{f['EXPECTED']}  (src: {f['SOURCE']})")
    if audit:
        print(f"- {L['match']}: {counts['MATCH']}")
    print(f"- {L['unknown']}: {counts['UNKNOWN']}")
    if unknown:
        print(f"- {L['questions']}:")
        for r in unknown:
            print(f"  ? {r['id']}: {qs.get(r['id'], '')}")
    if audit:
        print(f"- {L['existing']}: STRONG {ex_counts['STRONG']}, WEAK {ex_counts['WEAK']}, NONE {ex_counts['NONE']}")
    print(f"- {L['run']}: {n_fail_ok} fail as intended, {n_pass_ok} pass")
    print(f"- {L['web']}: {'YES, ' + str(len(web_rows)) + ' source(s), not verified by the script' if state['web'] else 'NO (project docs only)'}")
    print(f"- {L['files']}: " + ", ".join(r["file"] for r in run["results"]))
    print(f"- {L['time']}: {total_s}s")
    print(f"- {L['report']}: .trace/behavior-report.md")
    print("=== END FINAL ANSWER ===")


def main():
    ap = argparse.ArgumentParser(prog="lltt.py")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init")
    pi.add_argument("--target", default="")
    pi.add_argument("--mode", choices=["audit", "spec"], default="audit")
    pi.add_argument("--web", choices=["yes", "no"], default="no")
    pi.add_argument("--type", choices=["http", "job", "command"], default="http")
    pi.add_argument("--lang", choices=["en", "ar"], default="en")
    pi.add_argument("--reset", action="store_true")
    ps = sub.add_parser("scan-tests")
    ps.add_argument("paths", nargs="*")
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
    if a.cmd == "scan-tests":
        return cmd_scan_tests(ctx, a.paths)
    state = load_state(ctx)
    {"next": cmd_next, "gate": cmd_gate, "status": cmd_status, "finish": cmd_finish}[a.cmd](ctx, state)


if __name__ == "__main__":
    main()
