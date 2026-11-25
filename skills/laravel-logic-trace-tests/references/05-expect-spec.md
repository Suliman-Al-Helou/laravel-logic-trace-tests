There is no code yet. Decide, from DOCUMENTED sources, what the feature MUST do, then the next phase turns
every rule into a test that fails now. Write `.trace/expectations.md` (copy `assets/expectations.template.md`):

| ID | Expected | Type | Source | Quote | Verdict |

IDs are D-01, D-02 ... (one rule per row, sequential). Verdict is NEW (a rule to be built) or UNKNOWN.

Type and Source:
- `doc`: a project document (ticket, spec, ADR). Source = `docs/file.md:LINE`; Quote = a verbatim excerpt (max 25
  words) within 4 lines of that line. The gate checks it.
- `web`: only if the header says web research is on. Source = https URL of a page you OPENED; Quote = verbatim
  excerpt (max 25 words). Flagged as unverified in the report.
- `unknown`: nothing found. Source and Quote = `-`, Verdict = UNKNOWN.

Start from the ticket: every acceptance criterion is a rule. Then add the edge cases that DOCUMENTED guidance
says matter for this kind of feature (see the sources and searches in the audit-mode list: laravel.com/docs,
owasp.org API Security Top 10 2023, HTTP semantics, official package docs). Examples of the kinds of rules to
look for: who may call it (guest, wrong role, another user's object), invalid and boundary input, duplicates,
extra fields in the request, what is stored and what side effects happen, what the response exposes to each role.

Expected must state observable behavior with an HTTP status number when it is an HTTP rule.
Under `## QUESTIONS` write, for every UNKNOWN row: `- D-xx: <question for the user, 4+ words>`.
If you cannot tell what the behavior should be, that is UNKNOWN. Do not guess.
