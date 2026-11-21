# Phase 2 — Decision table

Output: `.trace/decision-table.md` (use `assets/decision-table.template.md`).

Every branch and every rule recorded in the logic map becomes ONE row with an ID
`D-01`, `D-02`, ... A row is: the condition, and the outcome the code gives.

## Where rows come from (only from the logic map)

- each validation rule (one row per rule that can fail, plus one "all valid" row)
- each `if/else`, `match`, early return, `abort*`, thrown exception, `catch`
- each middleware rejection and each policy ability
- each DB constraint that can reject a write (unique, FK, not-null)
- each side effect and the condition that triggers it (event, job, mail)

## "Where to look" checklist (look, do not assume)

For each item, grep/open the code. If the code has no such thing, do not add a row.

- value boundaries used in code: `min`, `max`, `size`, `between`, `>=`, `<`
- `nullable` / `sometimes` / `required_if` interplay with missing vs null vs ""
- numeric strings and booleans: `"0"`, `"false"`, `0`, `""` in conditions or `casts`
- `find` / `first` that can return null and what happens next
- `firstOrCreate` / `updateOrCreate` / read-then-write sequences (duplicate submit)
- soft-deleted records in route binding or queries
- another user's / tenant's record id (policy, scope, or missing check)
- dates: timezone, inclusive/exclusive end, "now" comparisons
- pagination: `per_page` limit, page past the end, sort field from input
- uploads: size, mime, missing file
- queued work: `afterCommit`, retries, failure handler
- exceptions caught and ignored (`catch` with no rethrow)
- mass assignment: `$request->all()` or `$request->input()` reaching `create/update`

## Output rules

- Columns: ID | Layer | Condition | Code outcome | Source `file.php:line`
- "Code outcome" is what the CODE says it does. It is not yet observed behavior.
- Mark `SKIP: <reason>` in the outcome column for rows you decide not to test.
