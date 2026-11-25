"""Fake test runner for the lltt tests. Behaves like `php artisan test --log-junit=x file`.

Reads .fake-results.json in the current directory: {"<test title>": {"status": "failure|error|skipped", "message": "..."}}.
Tests not listed pass. Tests are discovered with a regex over the test file.
"""
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

xml_path, test_file = None, None
for a in sys.argv[1:]:
    if a.startswith("--log-junit="):
        xml_path = a.split("=", 1)[1]
    else:
        test_file = a
if "--no-xml" in sys.argv or xml_path is None:
    sys.exit(0)
results = {}
rf = Path(".fake-results.json")
if rf.exists():
    results = json.loads(rf.read_text())
titles = re.findall(r"(?:it|test)\(\s*['\"]([^'\"]+)['\"]", Path(test_file).read_text())
out = ['<?xml version="1.0"?><testsuites><testsuite name="fake">']
for t in titles:
    r = results.get(t)
    if r is None:
        out.append(f'<testcase name="it {t}" file="{test_file}"/>')
    else:
        tag = r["status"]
        msg = r.get("message", "")
        out.append(f'<testcase name={quoteattr("it " + t)} file={quoteattr(test_file)}><{tag} message={quoteattr(msg)}>{escape(msg)}</{tag}></testcase>')
out.append("</testsuite></testsuites>")
Path(xml_path).write_text("".join(out))
sys.exit(1 if any(results.get(t, {}).get("status") in ("failure", "error") for t in titles) else 0)
