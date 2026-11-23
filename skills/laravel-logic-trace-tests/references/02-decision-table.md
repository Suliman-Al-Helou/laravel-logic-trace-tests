Write `.trace/decision-table.md` (copy `assets/decision-table.template.md`).
One row per branch/rule recorded in the logic map. Six columns, exactly:

| ID | Layer | Condition | Code outcome | Source | Probe |

- ID: D-01, D-02 ... sequential, no gaps.
- Layer: route, middleware, request, validation, controller, service, model, database, event, job, policy, auth, response, cache, storage.
- Code outcome: what the CODE says happens, with the status code if HTTP (e.g. `422, key quantity`).
- Source: `path/file.php:line` that exists.
- Probe: `P-01`, `P-02` ... (one unique id per probed row), OR one of:
  `no:duplicate-of:D-xx` | `no:external:<reason, 3+ words>` | `no:unreachable:<reason, 3+ words>`.
  At least 60% of rows must have a P-xx probe.

Rows come only from the logic map: each validation rule, each if/else/match/early return/abort/
exception/catch, each middleware rejection and policy ability, each DB constraint that can reject a
write, each side effect and its trigger.

Where to LOOK (look in the code, do not assume): boundaries (min, max, between, >=), nullable vs
missing vs "" vs "0", find()/first() returning null, firstOrCreate/updateOrCreate and
read-then-write (duplicate submit), soft-deleted records, another user's record id, dates and
timezones, pagination and sort input, uploads, queued work (afterCommit, retries), caught-and-ignored
exceptions, mass assignment (`$request->all()`), update vs create paths, unlink/delete paths and
their side effects, other roles the user may already have.

Every `app/...php` file cited in the logic map must have at least one row, or a line
`- app/Path/File.php: <reason, 3+ words>` under a `## NO-BRANCH` heading.
