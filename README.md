# Employee Attendance & Analytics API

A high-performance, robust REST API for managing employee attendance, punch-in/out workflows, regularization audit trails, and departmental analytics built with FastAPI and MongoDB.

Developed for the HROne Software Engineer Trainee assignment adhering to the official OpenAPI 3.0 specification, strict business rules (R1–R10), database-level concurrency protections, and MongoDB aggregation pipelines.

---

## 1. Features

- **Health & Readiness Monitoring**: `/health` probes MongoDB with bounded ping timeouts, returning `200 OK` only when MongoDB responds, and `503 Service Unavailable` otherwise.
- **Employee Management**: Paginated and filtered employee catalog with database-enforced unique `emp_code` constraints, format validation, and deterministic sorting.
- **Attendance Workflows**:
  - **Punch-In**: Automatic attendance date assignment in Indian Standard Time (`Asia/Kolkata`, UTC+05:30) with overnight shift support (R1) and 10-minute grace period late arrival calculations (R2).
  - **Punch-Out**: Atomic closure with Decimal Half-Up work hour calculation (R4), 30-minute threshold overtime calculation (R3), and half-day derivation (R5).
  - **Race Condition Safety**: Database unique compound indexes and atomic updates ensure concurrent requests yield exactly one success and appropriate HTTP 409 conflict responses.
  - **Manual Regularization (PATCH)**: Recomputes dependent metrics upon updates and maintains an append-only audit history of changed fields with optimistic concurrency locking.
- **Advanced Aggregation Analytics**:
  - **Employee Monthly Summary**: Working days computed dynamically from `joined_on` for mid-month joiners (R7), Mon–Fri presence counts, and half-up attendance percentages.
  - **Department Summary**: Cross-collection aggregation including eligible employees with zero attendance records, calculating true record-level work hour averages.
  - **Late Leaderboard**: Standard competition ranking (`1, 2, 2, 4`) via MongoDB `$setWindowFields` and `$rank`, applying limits post-ranking to preserve ties.
  - **Department Trend**: Gap-filled daily time series from `from` to `to` using MongoDB `$densify` and rolling 7-day moving averages via `$setWindowFields`.
- **Query Execution Inspection**: `/admin/explain/{endpoint}` returns raw execution statistics confirming index coverage (`IXSCAN`) and absence of collection scans (`COLLSCAN`).

---

## 2. Technology Stack

- **Language**: Python 3.11+ (Tested on Python 3.12)
- **Framework**: FastAPI 0.110+, Starlette, Pydantic v2
- **Database**: MongoDB 6.0+ (Tested on MongoDB 9.0.2)
- **Driver**: PyMongo 4.7+ (Timezone-aware BSON date handling)
- **Testing**: pytest, pytest-asyncio, HTTPX

---

## 3. Prerequisites

- Python 3.11 or newer
- MongoDB 6.0 or newer running locally or accessible via network URI

---

## 4. Setup & Installation

### Step 1: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
pip install pytest httpx
```

### Step 3: Configure Environment Variables
Configure the MongoDB connection via environment variables (or an optional `.env` file):
```bash
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB="attendance_db"
```

*Note: Real environment variables take priority over `.env` files. Never commit passwords or connection strings to Git.*

### Step 4: Seed Sample Data
Load the initial sample documents from `sample_data/`:
```bash
python sample_seed.py
```

---

## 5. Running the Application

Start the API server using Uvicorn:
```bash
uvicorn app.main:app --port 8000 --reload
```

The application creates all required database indexes idempotently at startup.

### Interactive Documentation & Swagger UI
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI Schema**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 6. API Endpoint Inventory

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | MongoDB readiness probe (`200 OK` or `503 Unavailable`) |
| `POST` | `/employees` | Create employee (`201 Created`, `409 Conflict`, `422 Unprocessable`) |
| `GET` | `/employees` | List employees with pagination and department filter |
| `POST` | `/attendance/punch-in` | Punch in, assign IST attendance date, compute late minutes |
| `POST` | `/attendance/punch-out` | Punch out, compute work hours, overtime, and half day |
| `GET` | `/attendance` | List attendance logs with date ranges, employee, and status filters |
| `PATCH` | `/attendance/{emp_code}/{date}` | Manual regularization with append-only history audit trail |
| `GET` | `/analytics/employees/{emp_code}/monthly` | Monthly employee attendance summary and percentage |
| `GET` | `/analytics/departments/summary` | Department-level monthly summary including zero-log employees |
| `GET` | `/analytics/leaderboard/late` | Competition-ranked late arrivals leaderboard with tie preservation |
| `GET` | `/analytics/departments/{department}/trend` | Daily gap-filled attendance trend with 7-day rolling average |
| `GET` | `/admin/explain/{endpoint}` | MongoDB query execution plan with `executionStats` |

---

## 7. Example Requests & Responses

### 1. Punch In
```bash
curl -X POST "http://localhost:8000/attendance/punch-in" \
     -H "Content-Type: application/json" \
     -d '{
       "emp_code": "EMP0001",
       "punched_at": 1783310280000,
       "status": "PRESENT"
     }'
```
**Response (201 Created):**
```json
{
  "emp_code": "EMP0001",
  "date": "2026-07-06",
  "status": "PRESENT",
  "punch_in": 1783310280000,
  "punch_out": null,
  "work_hours": null,
  "late_minutes": 0,
  "overtime_minutes": 0,
  "half_day": false,
  "history": []
}
```

### 2. Punch Out
```bash
curl -X POST "http://localhost:8000/attendance/punch-out" \
     -H "Content-Type: application/json" \
     -d '{
       "emp_code": "EMP0001",
       "punched_at": 1783343100000
     }'
```
**Response (200 OK):**
```json
{
  "emp_code": "EMP0001",
  "date": "2026-07-06",
  "status": "PRESENT",
  "punch_in": 1783310280000,
  "punch_out": 1783343100000,
  "work_hours": 9.12,
  "late_minutes": 0,
  "overtime_minutes": 0,
  "half_day": false,
  "history": []
}
```

### 3. Department Summary
```bash
curl -X GET "http://localhost:8000/analytics/departments/summary?month=2026-07"
```
**Response (200 OK):**
```json
{
  "month": "2026-07",
  "items": [
    {
      "department": "Engineering",
      "headcount": 2,
      "present_days": 3.0,
      "avg_work_hours": 9.04,
      "late_count": 0,
      "total_late_minutes": 0,
      "leave_count": 0,
      "on_duty_count": 0
    }
  ]
}
```

---

## 8. Index Strategy & Performance

The application creates the following indexes at startup:

1. **`employees`**:
   - `{"emp_code": 1}` (`unique=True`): Enforces employee code uniqueness and guarantees zero race condition duplicates.
   - `{"department": 1}`: Speeds up department filtering.
   - `{"joined_on": 1}`: Accelerates headcount eligibility filtering.
   - `{"department": 1, "joined_on": 1}`: Backs department-filtered headcount calculations.

2. **`attendance_logs`**:
   - `{"emp_code": 1, "date": 1}` (`unique=True`): Guarantees at most one log per employee-day and serializes concurrent punch-in attempts.
   - `{"date": -1, "emp_code": 1}`: Provides index-covered deterministic pagination for `/attendance`.
   - `{"emp_code": 1, "punch_in": -1}`: Accelerates punch-out lookup of the most recent open record.
   - `{"date": 1, "late_minutes": 1, "emp_code": 1}`: Enables index scans for the late arrival leaderboard.
   - `{"status": 1, "date": -1, "emp_code": 1}`: Optimizes status-filtered attendance queries.

---

## 9. Running Tests

Execute the automated test suite covering endpoints, business rules (R1–R10), concurrency, and query execution plans:
```bash
PYTHONPATH=. pytest tests/test_api.py -v
```

All 20 test cases execute and pass in under 1 second against local MongoDB.
