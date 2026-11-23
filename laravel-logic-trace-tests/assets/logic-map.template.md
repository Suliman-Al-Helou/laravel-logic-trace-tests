# Logic map — <entry point, e.g. POST /api/orders>

Only facts you opened. Format: `fact — file.php:line`. Unknown: `NOT FOUND: <what you searched>`. Nothing there: `none`.

## 1. Route
- verbs / URI / action:
- middleware list:
- binding / where():

## 2. Middleware (one line each: what it can reject, status code)

## 3. Request class (authorize / rules / prepareForValidation / hooks)

## 4. Controller branches

## 5. Service / Action branches (exceptions thrown or swallowed, external calls)

## 6. Models (fillable/guarded, casts, mutators, scopes, soft deletes, observers, transactions)

## 7. Database (unique, FK + onDelete, nullable, defaults)

## 8. Side effects (events, listeners queued?, jobs, mail, notifications, cache, storage)

## 9. Authorization (policies / gates actually reached)

## 10. Response (shape and status per branch)
