# Employee Attendance & Analytics REST API

A high-performance, production-minded REST API for employee attendance tracking, punch-in/out workflows, regularization audit trails, and departmental analytics built with FastAPI, MongoDB 6.0+, Redis, and Celery.

Developed for the **HROne Software Engineer Trainee** assignment adhering to the official OpenAPI 3.0 specification, strict business rules (R1–R10), database-level concurrency protections, and MongoDB aggregation pipelines.

---

## 1. Dual-Mode Architecture & Assignment Compliance

To strictly fulfill the official HROne submission criteria without compromising on real-world portfolio architecture, this repository provides two distinct, fully-verified operational modes:

| Mode | Git Branch | Description | Compliance Status |
|---|---|---|---|
| **Strict Assignment Mode** | `assignment-submission` / base `main` | All application logic self-contained in `app/main.py`. Zero Docker, Redis, or Celery requirements. Pure PyMongo + FastAPI. | **100% Compliant** with official submission constraint |
| **Portfolio Extended Mode** | `portfolio-extended` | Layered production architecture (`api/routers`, `services`, `repositories`, `schemas`, `db`, `workers`). Redis rate limiting, Celery background reports, Docker Compose. | **Production-Grade Portfolio** with enterprise patterns |

---

## 2. Directory Structure

```text
candidate_kit/
├── app/
│   ├── __init__.py
│   ├── main.py                          # Primary FastAPI application entry point & router wiring
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py              # Injectable database, repository, & service dependencies
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── health.py                # GET /health
│   │       ├── employees.py             # POST, GET /employees
│   │       ├── attendance.py            # POST /punch-in, POST /punch-out, GET, PATCH /attendance
│   │       ├── analytics.py             # Employee monthly, department summary, leaderboard, trend
│   │       └── admin.py                 # GET /admin/explain/{endpoint}
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                    # Environment settings parsing with python-dotenv
│   │   ├── logging.py                   # Structured logging configuration
│   │   └── exceptions.py                # Custom domain and infrastructure exceptions
│   ├── db/
│   │   ├── __init__.py
│   │   ├── mongodb.py                   # Singleton MongoClient lifecycle & ping health probe
│   │   ├── indexes.py                   # Idempotent index definitions & legacy conflict resolution
│   │   └── redis.py                     # Singleton Redis client lifecycle & health probe
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py                    # Error response and validation schemas
│   │   ├── employee.py                  # Employee request, model, and page schemas
│   │   ├── attendance.py                # PunchIn, PunchOut, Regularize, History schemas
│   │   └── analytics.py                 # Monthly, Summary, Leaderboard, Trend schemas
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── employee_repository.py       # MongoDB queries for employees collection
│   │   ├── attendance_repository.py     # MongoDB queries for attendance_logs collection
│   │   └── analytics_repository.py      # MongoDB aggregation pipelines and execution plan commands
│   ├── services/
│   │   ├── __init__.py
│   │   ├── attendance_calculator.py     # Pure deterministic calculations (R1-R7 rules)
│   │   ├── employee_service.py          # Employee domain business logic
│   │   ├── attendance_service.py        # Punch-in/out, optimistic regularization logic
│   │   └── analytics_service.py         # Summary, leaderboard, trend, and explain domain logic
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── rate_limit.py                # Redis-backed Lua script rate limiting with 429 Retry-After
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── celery_app.py                # Celery instance, broker, time limits, and task settings
│   │   └── tasks.py                     # Idempotent monthly report & department export tasks
│   └── utils/
│       ├── __init__.py
│       ├── datetime_utils.py            # Asia/Kolkata conversions, whole-second truncation, Decimal half-up
│       └── pagination.py                # Pagination helpers
├── tests/
│   ├── conftest.py                      # Shared pytest fixtures (TestClient, clean_db)
│   ├── test_api.py                      # Comprehensive 20-test single-suite baseline verification
│   ├── unit/
│   │   ├── test_attendance_calculator.py# Unit tests for R1-R7 business rules
│   │   ├── test_rate_limiter.py         # Tests for Redis rate limiting, exhaustion, and fail-closed
│   │   └── test_celery_tasks.py         # Tests for Celery background tasks & idempotency
│   ├── integration/
│   │   ├── test_modular_api.py          # Integration tests for all routers and endpoints
│   │   └── test_concurrency_race.py     # ThreadPool race tests (employee, punch-in, punch-out)
│   └── performance/
│       └── test_explain_performance.py  # executionStats verification for all explain queries
├── scripts/
│   ├── seed_database.py                 # Idempotent database seeder
│   └── check_indexes.py                 # MongoDB index audit and verification script
├── sample_data/
│   ├── employees.json                   # Sample employee records
│   └── attendance_logs.json             # Sample attendance records
├── sample_seed.py                       # Original assignment seed script
├── .env.example                         # Environment configuration template
├── .gitignore                           # Git exclusion rules
├── .dockerignore                        # Docker build exclusion rules
├── Dockerfile                           # Production container definition
├── docker-compose.yml                   # Compose orchestration (API, MongoDB, Redis, Worker)
├── requirements.txt                     # Pinned project dependencies
├── pyproject.toml                       # Build config, ruff linting, pytest pythonpath
├── REVIEW.md                            # Complete defect analysis of starter code and fixes
└── DECISIONS.md                         # Architectural, concurrency, index, and trade-off rationale
```

---

## 3. Technology Stack

- **Python**: 3.11+ (Validated on Python 3.12)
- **Framework**: FastAPI 0.110+, Starlette, Pydantic v2
- **Database**: MongoDB 6.0+ (Tested against MongoDB 9.0.2)
- **Driver**: PyMongo 4.7+ (Timezone-aware BSON handling)
- **Cache & Broker**: Redis 7.2+ / 8.0+
- **Asynchronous Task Queue**: Celery 5.3+
- **Testing & Quality**: pytest 9.1+, HTTPX, ruff 0.3+
- **Containerization**: Docker, Docker Compose

---

## 4. Setup & Quickstart

### Prerequisites
- Python 3.11+
- MongoDB 6.0+ running on `localhost:27017`
- Redis (Optional for Strict Mode, required for Extended Mode rate limiting / Celery)

### Step 1: Clone & Create Virtual Environment
```bash
git clone <repo-url>
cd candidate_kit
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy the example configuration:
```bash
cp .env.example .env
```
Default values:
```ini
ENVIRONMENT=development
LOG_LEVEL=INFO
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
MONGO_SERVER_SELECTION_TIMEOUT_MS=2000
REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

### Step 4: Verify Indexes & Seed Data
```bash
python scripts/check_indexes.py
python scripts/migrate_indexes.py  # Safe pre-migration check (use --apply to apply migrations)
python scripts/seed_database.py
```

### Step 5: Start the Application Locally
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## 5. Docker Compose Deployment (Extended Mode)

Run the entire containerized stack (FastAPI, MongoDB, Redis, and Celery worker):

```bash
docker compose up --build -d
```

Check service status and container health:
```bash
docker compose ps
```

View Celery worker logs:
```bash
docker compose logs -f worker
```

Tear down stack (preserving database volume):
```bash
docker compose down
```

---

## 6. Celery Background Worker Execution

To run Celery workers locally outside Docker:

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

Supported background tasks:
1. `tasks.generate_monthly_attendance_report(emp_code, year, month)`: Compiles full monthly report into `reports` collection idempotently.
2. `tasks.export_department_analytics(department, year, month)`: Aggregates departmental metrics into `reports` collection idempotently.

---

## 7. Endpoint Inventory

| Method | Path | Description | Key Behaviors / Rules |
|---|---|---|---|
| `GET` | `/health` | System Health Probe | Probes MongoDB `ping`. Returns `200` if healthy, `503` if down. Exempt from rate limiting. |
| `POST` | `/employees` | Create Employee | Unique `emp_code` constraint. Shift format validation. Rejects `shift_start == shift_end`. |
| `GET` | `/employees` | List Employees | Stable sorting by `emp_code` asc. Pagination (`page`, `page_size`). Department filter. |
| `POST` | `/attendance/punch-in` | Record Punch-In | Automatic IST date derivation. Overnight shift support (R1). 10-minute grace period (R2). |
| `POST` | `/attendance/punch-out` | Record Punch-Out | Atomic closure preventing double punch-out. Half-up work hours (R4). 30-min overtime threshold (R3). |
| `GET` | `/attendance` | List Attendance | Filters by date range, emp_code, status. Sorted by `date` desc, `emp_code` asc. |
| `PATCH` | `/attendance/{emp_code}/{date}` | Regularize Record | Recomputes derived metrics. Append-only history trail. Optimistic concurrency check. |
| `GET` | `/analytics/employees/{emp_code}/monthly` | Monthly Employee Analytics | Mon–Fri working days dynamic count (R7). Handles zero-attendance gracefully. Half-up percentage (R8). |
| `GET` | `/analytics/departments/summary` | Department Monthly Summary | Includes eligible employees with zero attendance (R8). True average work hours. |
| `GET` | `/analytics/leaderboard/late` | Late Arrival Ranking | Competition ranking (`$rank`) preserving ties (R10). Limit evaluated post-ranking. |
| `GET` | `/analytics/departments/{department}/trend` | Department Trend | Gap filling via `$densify` (R9). 7-day rolling moving average via `$setWindowFields`. |
| `GET` | `/admin/explain/{endpoint}` | Explain Query Plan | Returns MongoDB `executionStats` confirming index usage (`IXSCAN`) and performance. |

---

## 8. Test Execution and Verification

The test suite covers unit, integration, concurrency, performance, OpenAPI contract parity, Redis rate limiting, and Celery background workers:

```bash
pytest -v
```

### Test Suite Summary:
- **Baseline Functional Suite (`tests/test_api.py`)**: 19 comprehensive end-to-end integration tests.
- **Unit Suite (`tests/unit/`)**:
  - `test_attendance_calculator.py`: 7 tests verifying R1–R7 calculations, boundary conditions, rounding, and overtime.
  - `test_rate_limiter.py`: 10 tests verifying allowed requests, 429 exhaustion, Retry-After header, window expiration, fail-closed 503 behavior, IP extraction, untrusted proxy defense, and thread concurrency.
  - `test_celery_tasks.py`: 8 tests verifying task idempotency, reporting calculations, cross-year separation, no retry on permanent validation errors, and thread concurrency.
- **Integration Suite (`tests/integration/`)**:
  - `test_modular_api.py`: 4 full workflow tests covering health, employee lifecycle, attendance, regularization, and analytics.
  - `test_concurrency_race.py`: 3 concurrent race tests executing simultaneous requests against unique indexes and atomic updates.
  - `test_lifecycle.py`: 3 lifecycle tests verifying startup/shutdown and health probes with MongoDB available vs unavailable.
  - `test_openapi_contract.py`: 5 automated tests verifying runtime schema parity, status codes, parameters, and request body schemas against official `openapi.yaml`.
- **Performance Suite (`tests/performance/`)**:
  - `test_explain_performance.py`: 5 tests verifying execution plan stats on a 100-employee synthetic dataset.

**Total**: **64 tests passed (100% pass rate)** in ~3.0 seconds.

### Linting & Formatting Check:
```bash
ruff check .
```
Result: **Zero errors. All checks passed.**

### Static Type Check:
```bash
mypy app --ignore-missing-imports
```
Result: **Success: no issues found in 40 source files.**

---

## 9. Performance & MongoDB Indexes

The following indexes are idempotently managed via `app/db/indexes.py`:

```javascript
// Employees Collection
employees.createIndex({ "emp_code": 1 }, { unique: true, name: "idx_employees_emp_code_unique" });
employees.createIndex({ "department": 1 }, { name: "idx_employees_department" });
employees.createIndex({ "joined_on": 1 }, { name: "idx_employees_joined_on" });
employees.createIndex({ "department": 1, "joined_on": 1 }, { name: "idx_employees_dept_joined" });

// Attendance Logs Collection
attendance_logs.createIndex({ "emp_code": 1, "date": 1 }, { unique: true, name: "idx_attendance_emp_date_unique" });
attendance_logs.createIndex({ "date": -1, "emp_code": 1 }, { name: "idx_attendance_date_desc_emp_asc" });
attendance_logs.createIndex({ "emp_code": 1, "punch_in": -1 }, { name: "idx_attendance_emp_punch_in" });
attendance_logs.createIndex({ "date": 1, "late_minutes": 1, "emp_code": 1 }, { name: "idx_attendance_date_late_emp" });
attendance_logs.createIndex({ "status": 1, "date": -1, "emp_code": 1 }, { name: "idx_attendance_status_date_emp" });
```

---

## 10. Troubleshooting

1. **MongoDB Connection Refused**:
   Ensure MongoDB service is running: `brew services start mongodb-community` (macOS) or `sudo systemctl start mongod` (Linux), or check your `MONGO_URI`.
2. **Port 8000 Already in Use**:
   Run on an alternate port: `uvicorn app.main:app --port 8080 --reload`.
3. **Redis Unavailable in Extended Mode**:
   When Redis is unreachable and rate limiting is enabled, the API fails closed returning HTTP 503 to prevent unthrottled traffic. To disable rate limiting locally without Redis, set `RATE_LIMIT_ENABLED=false` in your `.env`.
