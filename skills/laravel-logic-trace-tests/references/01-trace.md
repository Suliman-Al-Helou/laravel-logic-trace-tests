# Phase 1 — Trace the real flow

Output: `.trace/logic-map.md` (use `assets/logic-map.template.md`).

Trace ONE entry point (a route, a job, or a console command) from input to final
side effect. At every step, open the file and record `file.php:line`.

## Steps (in this order)

1. **Route.** `php artisan route:list --json --path=<uri>` (or `--name=`).
   Record: verbs, URI, controller@method, middleware list, route-model binding,
   `where()` constraints. Also open `routes/*.php` for the line number.
2. **Middleware.** For each middleware in the list, find its class
   (`bootstrap/app.php`, `app/Http/Kernel.php`, or the package). Record what it
   can reject and with which status code.
3. **Request class.** Open the FormRequest used by the controller method.
   Record: `authorize()` logic, `rules()`, `prepareForValidation()`, custom
   messages, `after()` hooks. If the controller uses `$request->validate(...)`
   inline, record those rules instead.
4. **Controller method.** Record every branch: `if/else`, early `return`,
   `abort*`, `findOrFail` vs `find`, `try/catch`, `match/switch`. One line each.
5. **Service / Action / Repository** called from the controller. Same: every
   branch, every exception thrown or swallowed, every external call.
6. **Models touched.** For each: `$fillable/$guarded`, `$casts`, accessors and
   mutators used, global scopes, SoftDeletes, observers (`php artisan model:show
   <Model>` helps), relationships loaded, DB transactions.
7. **Database.** Open the migrations for touched tables: unique indexes, foreign
   keys and `onDelete`, nullable columns, defaults.
8. **Side effects.** `php artisan event:list` for events fired. Record listeners,
   whether they are queued, `afterCommit`, jobs dispatched, notifications, mail,
   cache writes, file storage.
9. **Authorization.** Policies / Gates / `authorize()` calls actually reached,
   and which abilities. Check `AuthServiceProvider` or auto-discovery.
10. **Response.** Resource / JSON shape / redirect, status codes per branch.

## Rules

- A step with nothing to record: write `none`. Do not skip the line.
- Only record what you opened. If you could not find the file, write
  `NOT FOUND: <what you searched>`.
- Do not interpret yet. No "this is a bug". Only facts.
