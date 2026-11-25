# Expectations: <target>

| ID | Expected | Type | Source | Quote | Verdict |
|----|----------|------|--------|-------|---------|
| D-01 | 201 and the order is stored | doc | docs/tickets/01-orders.md:12 | A valid request creates the order | MATCH |
| D-03 | 409 and no second order | web | https://laravel.com/docs/master/http-tests | assertConflict | GAP |
| D-07 | - | unknown | - | - | UNKNOWN |

## QUESTIONS
- D-07: Should a retried request after a timeout create a second order?

## MISSING
- (optional) a case the sources mention that has no decision row (source)
