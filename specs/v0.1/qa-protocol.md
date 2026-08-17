# QA protocol

QA is a structured JSON report with stable `check_id` values and `PASS`/`FAIL` statuses. Current blocking checks cover GLB header, semantic part identity, triangle budget, finite coordinates, non-degenerate geometry, and declared dimensions.

A failed or stale report must not be presented as a current PASS. A provider candidate is accepted only after this deterministic layer succeeds.
