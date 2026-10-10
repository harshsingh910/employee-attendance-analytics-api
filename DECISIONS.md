# DECISIONS.md

## 1. Assignment Core Decisions

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

---

## 2. Architecture & Extended Mode Decisions

### Dual Mode Strategy
- **Strict Assignment Mode (`assignment-submission` branch & initial commit):**
  Complies 100% with the HROne rule requiring all submitted application code in `app/main.py` with zero external system requirements (no Redis/Celery/Docker required for grading).
- **Portfolio Extended Mode (`portfolio-extended` branch):**
  Production-grade layered architecture with clean modular packages (`core`, `db`, `schemas`, `repositories`, `services`, `middleware`, `workers`, `utils`), Redis rate limiting, Celery workers, and Docker Compose.

### Timezone and Instant Normalization
- All stored timestamps (`punch_in`, `punch_out`, `created_at`, `history[].at`) are UTC instants stored as whole-second truncated BSON datetimes and serialized to integer epoch milliseconds.
- Shift boundaries and attendance dates are evaluated strictly in `Asia/Kolkata` (IST, UTC+05:30).
- Overnight shifts (where `shift_end <= shift_start`, e.g. 22:00 to 06:00) map punch-in events occurring before `shift_end` IST to the previous calendar date (R1).

### Decimal Half-Up Rounding
- Python's standard `round()` uses Banker's rounding (round-half-to-even), which causes silent rounding discrepancies (e.g. 4.255 -> 4.25 instead of 4.26).
- All calculations (`work_hours`, `attendance_pct`, `avg_work_hours`) utilize Python's `decimal.Decimal` with `ROUND_HALF_UP` quantized to 2 decimal places (4 places for trends), fulfilling R4, R8, and R9.

### Concurrency and Locking Strategy
- **Punch-In:** Guaranteed by unique compound index `idx_attendance_emp_date_unique`.
- **Punch-Out:** Handled via atomic `find_one_and_update({"_id": target_id, "punch_out": None}, ...)` at the database level. Simultaneous punch-outs yield exactly one 200 OK and one 409 Conflict.
- **Attendance Regularization:** Utilizes optimistic concurrency control by matching `{"_id": rec_id, "history": current_history}` to guarantee no lost updates from concurrent administrative corrections.

### Redis Rate Limiting Design
- Utilizes an atomic Lua script executing `INCR` + conditional `EXPIRE` + `TTL`.
- Protects downstream APIs from burst traffic while injecting standard rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`).
- Rejections return HTTP 429 Too Many Requests with a compliant `Retry-After` header.
- **Fail-Closed Outage Handling:** If Redis encounters connection timeouts or outages while rate limiting is active, the middleware rejects requests with HTTP 503 rather than silently bypassing protection.
- System endpoints (`/health`) and OpenAPI documentation are exempted from rate limiting.

### Celery Background Processing and Worker Resiliency
- Background workers handle heavy analytical tasks (`tasks.generate_monthly_attendance_report`, `tasks.export_department_analytics`).
- Tasks are strictly idempotent, utilizing MongoDB `$set` upserts on unique task compound keys (`emp_code + year + month`).
- Bounded retries (3 attempts) with exponential backoff and jitter handle transient network or storage delays without duplicated side effects.
