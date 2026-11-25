Write `.trace/decision-table.md` (copy `assets/decision-table.template.md`).
One row per branch/rule in the logic map. Seven columns, exactly:

| ID | Layer | Condition | Code outcome | Source | Snippet | Probe |

- ID: D-01, D-02 ... sequential, no gaps.
- Layer: route, middleware, request, validation, controller, service, model, database, event, job, policy, auth, response, cache, storage.
- Code outcome: what the CODE does, with the status code if HTTP (e.g. `422, key quantity`).
- Source: `path/file.php:line` that exists.
- Snippet: 6 to 120 characters COPIED from the code at (or within 3 lines of) that line. It must not contain
  the `|` character. The gate searches the file for it, so a wrong line number is caught.
- Probe: `P-01`, `P-02` ... (unique per probed row), OR `no:duplicate-of:D-xx` |
  `no:external:<reason, 3+ words>` | `no:unreachable:<reason, 3+ words>`. At least 60% of rows need a P-xx.

Every `app/...php:line` cited in the logic map must have a row whose Source is within 2 lines, or a line
under `## NO-BRANCH`: `- app/Path/File.php:LINE: <reason, 3+ words>` (or `- app/Path/File.php: <reason>` for
a whole file with no conditions).

Where to LOOK for rows (look in the code, do not assume): boundaries (min, max, between), nullable vs missing
vs "" vs "0", find()/first() returning null, firstOrCreate/updateOrCreate and read-then-write (duplicate
submit), soft-deleted records, another user's record id, dates and timezones, pagination and sort input,
uploads, queued work (afterCommit, retries), caught-and-ignored exceptions, mass assignment
(`$request->all()`), optional relations synced from input (ids that do not exist), a user who already has
other roles, transaction rollback when a later step fails, cache invalidation on every write path.
