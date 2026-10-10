# DECISIONS.md

1. **Indexes.**
We created a unique index on `employees.emp_code` to enforce employee code uniqueness, and a unique compound index on `attendance_logs.(emp_code, date)` to guarantee at most one record per employee-day. Compound index `attendance_logs.(date: -1, emp_code: 1)` backs paginated listing with stable sorting. For analytics, `attendance_logs.(date, late_minutes, emp_code)` enables covered index scans for late leaderboard ranking, while `employees.(joined_on)` and `employees.(department, joined_on)` accelerate headcount filtering. We considered and rejected a standalone index on `attendance_logs.status` due to low cardinality and poor selectivity.

2. **Punch-in race.**
Both concurrent requests compute the IST attendance date and attempt `insert_one`. MongoDB's unique compound index on `(emp_code, date)` guarantees atomic serialization at the storage engine level. Exactly one insert succeeds with HTTP 201; the other raises `DuplicateKeyError`, which our handler intercepts to return HTTP 409 (`already punched in for this date`). This database-level guarantee eliminates check-then-act race conditions.

3. **Ties.**
Our pipeline applies `$setWindowFields` with `$rank` for competition ranking (1, 2, 2, 4). The `limit` filter (`rank <= limit`) is evaluated *after* ranking. When two employees tie at the cutoff, both satisfy `rank <= limit` and are returned, ordered by `emp_code` ascending. The response may exceed `limit` rows, preserving exact contract semantics.

4. **Headcount.**
The department summary pipeline originates on `employees` (filtering `joined_on <= end_of_month`) and performs an index-backed `$lookup` into `attendance_logs`. Grouping by department counts each employee toward `headcount` via `$sum: 1`, whether their joined log array is populated or empty.

5. **One thing you would change for 100x the data.**
At 100x data (~10M logs), we would maintain asynchronous pre-aggregated monthly departmental summary rollups via MongoDB Change Streams, turning multi-stage cross-collection aggregations into sub-millisecond point reads.
