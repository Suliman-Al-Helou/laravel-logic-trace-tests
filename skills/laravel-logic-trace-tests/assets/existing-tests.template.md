# Existing tests: <target>

| ID | Existing test | Strength | Reason |
|----|---------------|----------|--------|
| D-01 | tests/Feature/OrderTest.php:12 | WEAK | only checks 201, not the stored order |
| D-02 | tests/Feature/OrderTest.php:30 | STRONG | asserts 422 and the quantity error key |
| D-03 | - | NONE | no test sends the same payload twice |
