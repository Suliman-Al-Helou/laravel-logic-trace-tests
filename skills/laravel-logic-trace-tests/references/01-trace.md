Trace ONE entry point from input to final side effect. Write `.trace/logic-map.md`
using `assets/logic-map.template.md` (copy it, fill it in).

Every line you write must end with the source `path/file.php:line` that you opened.
Nothing found: write `none`. Searched and could not find: `NOT FOUND: <what you searched>`.
Do not interpret, do not judge. Facts only.

Steps, in order. Run the command, open the file, record the line:
1. Route: `php artisan route:list --json --path=<uri>`; then open `routes/*.php` for the line.
   Record verbs, action, middleware list, route-model binding, where() constraints.
2. Middleware: open each middleware class (bootstrap/app.php, Kernel, package). What can it reject, which status?
3. Request class: authorize(), rules(), prepareForValidation(), hooks. Inline `validate()` counts too.
4. Controller method: every branch (if/else, early return, abort, findOrFail vs find, try/catch, match).
5. Service/Action/Repository: every branch, exception thrown or swallowed, external call.
6. Models: fillable/guarded, casts, mutators, global scopes, SoftDeletes, observers (`php artisan model:show <Model>`), transactions.
7. Database: open the migrations of touched tables: unique, foreign keys and onDelete, nullable, defaults.
8. Side effects: `php artisan event:list`, listeners (queued? afterCommit?), jobs, mail, notifications, cache, storage.
9. Authorization: policies/gates actually reached and the abilities.
10. Response: resource/shape and status code per branch.

The gate rejects: missing sections, empty sections, statements without a file:line, template
placeholders, citations that do not exist, fewer than 4 distinct sources (3 for job/command),
and (for http) a Route section without a routes/ line.
