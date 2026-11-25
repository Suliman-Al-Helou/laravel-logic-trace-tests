Decide what the CORRECT behavior is, from DOCUMENTED sources, never from your own memory.
Write `.trace/expectations.md` (copy `assets/expectations.template.md`):

| ID | Expected | Type | Source | Quote | Verdict |

One row for every decision row that has a P-xx probe (same ID).

Type and Source:
- `doc`: a document in THIS project (ticket, spec, ADR, README, docs/). Source = `docs/file.md:LINE`.
  Quote = a verbatim excerpt (max 25 words) found within 4 lines of that line. The gate checks it.
- `web`: only if the run has web research (the header says so). Source = the https URL of a page you OPENED.
  Quote = a verbatim excerpt (max 25 words) from it. The script cannot open the URL: the report flags web sources
  as unverified, so quote exactly.
- `unknown`: you found nothing. Source and Quote = `-`, Verdict = UNKNOWN.

Verdict (audit mode): MATCH (the probe's observed behavior equals Expected), GAP (it differs: this becomes a
failing test), UNKNOWN. Compare Expected with the PROBE result, not with your reading of the code.

Order of sources (stop at the first that answers the question):
1. Project docs: grep `docs/` for the feature, ticket, ADR, acceptance criteria.
2. Official docs: laravel.com/docs (validation, authorization, eloquent, database transactions, queues, http-tests),
   spatie.be docs for roles/permissions, pestphp.com, phpunit.de.
3. Standards and security references: owasp.org (API Security Top 10 2023: API1 object-level authorization,
   API3 property-level authorization and mass assignment, API4 resource consumption, API5 function-level
   authorization, API6 sensitive business flows), datatracker.ietf.org or developer.mozilla.org for HTTP semantics.
4. Practice guides: martinfowler.com, blog.ploeh.dk, laracasts.com, laravel-news.com.

How to search (web research, at most 2 searches per layer, 12 in total):
- validation rule behavior: `laravel validation <rule> rule` and open laravel.com/docs/validation.
- who may do what: `laravel authorization policies gates`, `OWASP API1 BOLA`, `OWASP API5 BFLA`.
- extra fields accepted by create/update: `laravel mass assignment fillable`, `OWASP API3`.
- duplicate submit / retries: `idempotent POST duplicate 409 conflict`.
- transactions and rollback: `laravel database transactions`. Queues: `laravel queue afterCommit`.
- how to assert it: `laravel http tests <assertion>`.
Ignore pages you cannot open. Never cite a URL you did not open. No source found = UNKNOWN.

Also look for edge cases the sources warn about for THIS kind of feature (not only what the code branches on).
If you find a case that has no decision row, list it under `## MISSING` as `- <case> (source)`. The gate does not
block on it, but the final answer reports it.

Under `## QUESTIONS` write, for every UNKNOWN row: `- D-xx: <question for the user, 4+ words>`.

Rules: Expected must state observable behavior (status code, error key, stored state). If Expected has an
HTTP status, write the number. MATCH is checked against the probe's observed status.
