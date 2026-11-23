# Decision table: <target>

| ID | Layer | Condition | Code outcome | Source | Probe |
|----|-------|-----------|--------------|--------|-------|
| D-01 | validation | all fields valid | 201, order created | app/Http/Controllers/OrderController.php:30 | P-01 |
| D-02 | validation | quantity missing | 422, key quantity | app/Http/Requests/StoreOrderRequest.php:18 | P-02 |
| D-03 | service | same payload as D-01 | 201 | app/Services/OrderService.php:20 | no:duplicate-of:D-01 |

## NO-BRANCH
- app/Models/Order.php: only casts, no conditional logic
