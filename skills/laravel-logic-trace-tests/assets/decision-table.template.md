# Decision table — <entry point>

| ID | Layer | Condition | Code outcome (from reading) | Source |
|----|-------|-----------|-----------------------------|--------|
| D-01 | validation | all fields valid | 201, order created | app/Http/Controllers/OrderController.php:30 |
| D-02 | validation | `quantity` missing | 422, key `quantity` | app/Http/Requests/StoreOrderRequest.php:18 |
