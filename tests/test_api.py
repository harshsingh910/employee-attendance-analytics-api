"""
Comprehensive Test Suite for HROne Employee Attendance & Analytics API
Covers R1-R10, all endpoints, edge cases, race conditions, explain query plans, and concurrency.
"""
import concurrent.futures
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["MONGO_URI"] = "mongodb://localhost:27017"
os.environ["MONGO_DB"] = "test_attendance_db"

from app.main import app, create_indexes, get_db


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    database = get_db()
    database.employees.delete_many({})
    database.attendance_logs.delete_many({})
    create_indexes(database)
    yield
    database.employees.delete_many({})
    database.attendance_logs.delete_many({})


# --------------------------------------------------------------------------- #
# 1. Health Probe
# --------------------------------------------------------------------------- #
def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


# --------------------------------------------------------------------------- #
# 2. Employee CRUD & Business Rules
# --------------------------------------------------------------------------- #
def test_create_and_list_employee(client):
    payload = {
        "emp_code": "EMP0001",
        "name": "Asha Rao",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    }
    res = client.post("/employees", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["emp_code"] == "EMP0001"
    assert "_id" not in data
    assert isinstance(data["created_at"], int)
    assert data["created_at"] >= 100000000000

    # Duplicate emp_code -> 409
    res_dup = client.post("/employees", json=payload)
    assert res_dup.status_code == 409

    # List employees
    res_list = client.get("/employees?department=Engineering")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["total"] == 1
    assert list_data["page"] == 1
    assert len(list_data["items"]) == 1
    assert list_data["items"][0]["emp_code"] == "EMP0001"


def test_employee_validation(client):
    # shift_start == shift_end -> 422
    payload_equal_shifts = {
        "emp_code": "EMP0002",
        "name": "Vikram",
        "email": "vikram@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "09:30",
        "joined_on": "2026-07-13",
    }
    res = client.post("/employees", json=payload_equal_shifts)
    assert res.status_code == 422

    # Invalid emp_code format -> 422
    payload_bad_code = {
        "emp_code": "INVALID_CODE",
        "name": "Vikram",
        "email": "vikram@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-13",
    }
    assert client.post("/employees", json=payload_bad_code).status_code == 422


# --------------------------------------------------------------------------- #
# 3. Punch-In, R1, R2
# --------------------------------------------------------------------------- #
def test_punch_in_and_late_minutes(client):
    # Setup employee
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })

    # Case 1: Punch in at exactly 09:40:00 IST on 2026-07-06 (10 minutes grace) -> late_minutes = 0
    # 2026-07-06 09:40:00 IST = 2026-07-06 04:10:00 UTC
    dt_0940 = datetime(2026, 7, 6, 4, 10, 0, tzinfo=timezone.utc)
    ms_0940 = int(dt_0940.timestamp() * 1000)

    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0001",
        "punched_at": ms_0940,
        "status": "PRESENT"
    })
    assert res.status_code == 201
    data = res.json()
    assert data["date"] == "2026-07-06"
    assert data["late_minutes"] == 0
    assert data["work_hours"] is None
    assert data["half_day"] is False
    assert data["history"] == []

    # Duplicate punch in for same day -> 409
    res_dup = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0001",
        "punched_at": ms_0940,
    })
    assert res_dup.status_code == 409


def test_punch_in_late_boundary_r2(client):
    client.post("/employees", json={
        "emp_code": "EMP0003",
        "name": "Neha",
        "email": "neha@example.com",
        "department": "Sales",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-02-01",
    })

    # Case 2: 09:40:01 IST -> 10 minutes late!
    # 2026-07-06 09:40:01 IST = 2026-07-06 04:10:01 UTC
    dt_late10 = datetime(2026, 7, 6, 4, 10, 1, tzinfo=timezone.utc)
    ms_late10 = int(dt_late10.timestamp() * 1000)

    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0003",
        "punched_at": ms_late10,
    })
    assert res.status_code == 201
    assert res.json()["late_minutes"] == 10


def test_punch_in_overnight_shift_r1(client):
    # Overnight shift: 22:00 - 06:00
    client.post("/employees", json={
        "emp_code": "EMP0005",
        "name": "Meera",
        "email": "meera@example.com",
        "department": "Support",
        "shift_start": "22:00",
        "shift_end": "06:00",
        "joined_on": "2026-03-10",
    })

    # Punch in at 01:30 IST on 2026-07-07 (earlier than shift_end 06:00)
    # belongs to shift starting on 2026-07-06!
    # 2026-07-07 01:30:00 IST = 2026-07-06 20:00:00 UTC
    dt_early = datetime(2026, 7, 6, 20, 0, 0, tzinfo=timezone.utc)
    ms_early = int(dt_early.timestamp() * 1000)

    res = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0005",
        "punched_at": ms_early,
    })
    assert res.status_code == 201
    assert res.json()["date"] == "2026-07-06"


# --------------------------------------------------------------------------- #
# 4. Punch-Out, R3, R4, R5
# --------------------------------------------------------------------------- #
def test_punch_out_work_hours_and_overtime(client):
    # Employee setup
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })

    # Punch in 09:28 IST (03:58 UTC) on 2026-07-06
    t_in = int(datetime(2026, 7, 6, 3, 58, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": t_in})

    # Punch out 18:35 IST (13:05 UTC) on 2026-07-06
    # 5 min after shift end -> overtime under 30 -> overtime_minutes = 0
    # duration 9h 7m = 32820s / 3600 = 9.11666... -> 9.12 half-up
    t_out = int(datetime(2026, 7, 6, 13, 5, 0, tzinfo=timezone.utc).timestamp() * 1000)
    res = client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": t_out})
    assert res.status_code == 200
    data = res.json()
    assert data["work_hours"] == 9.12
    assert data["overtime_minutes"] == 0
    assert data["half_day"] is False

    # Second punch-out attempt -> 409
    res_again = client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": t_out})
    assert res_again.status_code == 409


def test_punch_out_half_day_and_overtime(client):
    client.post("/employees", json={
        "emp_code": "EMP0004",
        "name": "Rohit",
        "email": "rohit@example.com",
        "department": "Sales",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-02-01",
    })

    # Punch in 04:00 UTC
    t_in = int(datetime(2026, 7, 7, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0004", "punched_at": t_in, "status": "WFH"})

    # Punch out 07:30 UTC (3.5 hours worked < 4.50 -> half_day = True)
    t_out = int(datetime(2026, 7, 7, 7, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
    res = client.post("/attendance/punch-out", json={"emp_code": "EMP0004", "punched_at": t_out})
    assert res.status_code == 200
    data = res.json()
    assert data["work_hours"] == 3.5
    assert data["half_day"] is True


# --------------------------------------------------------------------------- #
# 5. List Attendance
# --------------------------------------------------------------------------- #
def test_list_attendance_pagination_and_sorting(client):
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })
    t_in = int(datetime(2026, 7, 6, 3, 58, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": t_in})

    # Query with date_from > date_to -> 422
    res_bad = client.get("/attendance?date_from=2026-07-10&date_to=2026-07-05")
    assert res_bad.status_code == 422

    # Successful list
    res = client.get("/attendance?emp_code=EMP0001&date_from=2026-07-01&date_to=2026-07-31")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["date"] == "2026-07-06"


# --------------------------------------------------------------------------- #
# 6. Manual Regularization (PATCH) & History Audit Trail
# --------------------------------------------------------------------------- #
def test_regularize_attendance(client):
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })
    # Punch in at 10:05 IST (late by 35m)
    t_in = int(datetime(2026, 7, 7, 4, 35, 0, tzinfo=timezone.utc).timestamp() * 1000)
    t_out = int(datetime(2026, 7, 7, 13, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": t_in})
    client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": t_out})

    # Correct punch-in to 09:28 IST (03:58 UTC)
    t_in_new = int(datetime(2026, 7, 7, 3, 58, 0, tzinfo=timezone.utc).timestamp() * 1000)
    patch_payload = {
        "punch_in": t_in_new,
        "reason": "biometric glitch",
        "regularized_by": "hr.admin",
    }
    res = client.patch("/attendance/EMP0001/2026-07-07", json=patch_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["late_minutes"] == 0
    assert len(data["history"]) == 1
    hist = data["history"][0]
    assert hist["by"] == "hr.admin"
    assert hist["reason"] == "biometric glitch"
    assert "late_minutes" in hist["changes"]
    assert hist["changes"]["late_minutes"]["from"] == 35
    assert hist["changes"]["late_minutes"]["to"] == 0

    # Changing nothing -> 422
    res_no_change = client.patch("/attendance/EMP0001/2026-07-07", json=patch_payload)
    assert res_no_change.status_code == 422


# --------------------------------------------------------------------------- #
# 7. Employee Monthly Analytics
# --------------------------------------------------------------------------- #
def test_employee_monthly_analytics(client):
    # EMP0002 joined mid-month 2026-07-13
    client.post("/employees", json={
        "emp_code": "EMP0002",
        "name": "Vikram",
        "email": "vikram@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-13",
    })

    # Punch in on 2026-07-14 (Tuesday)
    t_in = int(datetime(2026, 7, 14, 4, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)
    t_out = int(datetime(2026, 7, 14, 13, 1, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0002", "punched_at": t_in})
    client.post("/attendance/punch-out", json={"emp_code": "EMP0002", "punched_at": t_out})

    res = client.get("/analytics/employees/EMP0002/monthly?month=2026-07")
    assert res.status_code == 200
    data = res.json()
    # Working days from July 13 to July 31 = 15 working days (weekdays)
    assert data["working_days"] == 15
    assert data["present_days"] == 1.0
    assert data["leave_days"] == 0
    assert data["late_count"] == 0
    # 1.0 / 15 * 100 = 6.6666... -> 6.67 half-up
    assert data["attendance_pct"] == 6.67


# --------------------------------------------------------------------------- #
# 8. Department Summary Analytics
# --------------------------------------------------------------------------- #
def test_department_summary(client):
    # Two employees in Engineering
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })
    client.post("/employees", json={
        "emp_code": "EMP0002",
        "name": "Vikram",
        "email": "vikram@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-13",
    })

    # EMP0001 worked on 2026-07-06 (Mon, 9.12 hours)
    t_in = int(datetime(2026, 7, 6, 3, 58, 0, tzinfo=timezone.utc).timestamp() * 1000)
    t_out = int(datetime(2026, 7, 6, 13, 5, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": t_in})
    client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": t_out})

    res = client.get("/analytics/departments/summary?month=2026-07")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["department"] == "Engineering"
    assert item["headcount"] == 2  # Includes EMP0002 even though EMP0002 has 0 logs on July 6!
    assert item["present_days"] == 1.0
    assert item["avg_work_hours"] == 9.12


# --------------------------------------------------------------------------- #
# 9. Late Leaderboard & Ties
# --------------------------------------------------------------------------- #
def test_late_leaderboard_ties(client):
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })
    client.post("/employees", json={
        "emp_code": "EMP0002",
        "name": "Vikram",
        "email": "vikram@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })

    # Both punch in with exactly 35 minutes late
    # 10:05 IST on 2026-07-06
    t1 = int(datetime(2026, 7, 6, 4, 35, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": t1})
    client.post("/attendance/punch-in", json={"emp_code": "EMP0002", "punched_at": t1})

    res = client.get("/analytics/leaderboard/late?month=2026-07&limit=1")
    assert res.status_code == 200
    items = res.json()["items"]
    # Ties share rank 1, so BOTH are returned even though limit is 1!
    assert len(items) == 2
    assert items[0]["rank"] == 1
    assert items[1]["rank"] == 1
    assert items[0]["emp_code"] == "EMP0001"
    assert items[1]["emp_code"] == "EMP0002"


# --------------------------------------------------------------------------- #
# 10. Department Trend & Gap Filling
# --------------------------------------------------------------------------- #
def test_department_trend_gap_filling(client):
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })

    # Punch in only on 2026-07-06 (Mon)
    t_in = int(datetime(2026, 7, 6, 3, 58, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": t_in})

    # Query from July 6 to July 10 (5 days)
    res = client.get("/analytics/departments/Engineering/trend?from=2026-07-06&to=2026-07-10")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 5  # Every single day present via $densify
    assert items[0]["date"] == "2026-07-06"
    assert items[0]["present_count"] == 1.0
    assert items[0]["attendance_rate"] == 1.0

    assert items[1]["date"] == "2026-07-07"
    assert items[1]["present_count"] == 0.0
    assert items[1]["attendance_rate"] == 0.0


# --------------------------------------------------------------------------- #
# 11. Explain Endpoints
# --------------------------------------------------------------------------- #
def test_explain_endpoints(client):
    client.post("/employees", json={
        "emp_code": "EMP0001",
        "name": "Asha",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    })

    # 1. attendance_list explain
    res1 = client.get("/admin/explain/attendance_list")
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["collection"] == "attendance_logs"
    assert "explain" in d1

    # 2. employee_monthly explain
    res2 = client.get("/admin/explain/employee_monthly?emp_code=EMP0001&month=2026-07")
    assert res2.status_code == 200
    assert res2.json()["collection"] == "attendance_logs"

    # 3. department_summary explain
    res3 = client.get("/admin/explain/department_summary?month=2026-07")
    assert res3.status_code == 200
    assert res3.json()["collection"] == "employees"

    # 4. late_leaderboard explain
    res4 = client.get("/admin/explain/late_leaderboard?month=2026-07")
    assert res4.status_code == 200
    assert res4.json()["collection"] == "attendance_logs"

    # 5. department_trend explain
    res5 = client.get("/admin/explain/department_trend?department=Engineering&from=2026-07-06&to=2026-07-10")
    assert res5.status_code == 200
    assert res5.json()["collection"] == "attendance_logs"


# --------------------------------------------------------------------------- #
# 12. Concurrency and Race Condition Tests
# --------------------------------------------------------------------------- #


def test_concurrent_employee_creation(client):
    payload = {
        "emp_code": "EMP9999",
        "name": "Race Tester",
        "email": "race@example.com",
        "department": "QA",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    }
    def make_req():
        return client.post("/employees", json=payload).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_req) for _ in range(5)]
        codes = [f.result() for f in futures]

    assert codes.count(201) == 1
    assert codes.count(409) == 4


def test_concurrent_punch_in(client):
    client.post("/employees", json={
        "emp_code": "EMP8888",
        "name": "Punch Racer",
        "email": "punchrace@example.com",
        "department": "QA",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })
    t_in = int(datetime(2026, 7, 6, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    payload = {
        "emp_code": "EMP8888",
        "punched_at": t_in,
    }

    def make_punch():
        return client.post("/attendance/punch-in", json=payload).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_punch) for _ in range(5)]
        codes = [f.result() for f in futures]

    assert codes.count(201) == 1
    assert codes.count(409) == 4


def test_concurrent_punch_out(client):
    client.post("/employees", json={
        "emp_code": "EMP7777",
        "name": "Out Racer",
        "email": "outrace@example.com",
        "department": "QA",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })
    t_in = int(datetime(2026, 7, 6, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    t_out = int(datetime(2026, 7, 6, 13, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP7777", "punched_at": t_in})

    def make_punch_out():
        return client.post("/attendance/punch-out", json={"emp_code": "EMP7777", "punched_at": t_out}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_punch_out) for _ in range(5)]
        codes = [f.result() for f in futures]

    assert codes.count(200) == 1
    assert codes.count(409) == 4


# --------------------------------------------------------------------------- #
# 13. Weekend and Overtime Rules (R7, R3)
# --------------------------------------------------------------------------- #
def test_weekend_records_business_rule_r7(client):
    client.post("/employees", json={
        "emp_code": "EMP6666",
        "name": "Weekend Worker",
        "email": "weekend@example.com",
        "department": "Support",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-01",
    })

    # Saturday record: 2026-07-11
    # 2026-07-11 10:15:59 IST (45 min late!)
    # 2026-07-11 19:30:00 IST (60 min overtime!)
    t_in = int(datetime(2026, 7, 11, 4, 45, 59, tzinfo=timezone.utc).timestamp() * 1000)
    t_out = int(datetime(2026, 7, 11, 14, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP6666", "punched_at": t_in})
    client.post("/attendance/punch-out", json={"emp_code": "EMP6666", "punched_at": t_out})

    # Monthly analytics
    res = client.get("/analytics/employees/EMP6666/monthly?month=2026-07")
    assert res.status_code == 200
    data = res.json()
    # R7: "present_days counts only Mon - Fri records; weekend records still add to late and overtime totals."
    assert data["present_days"] == 0.0  # Saturday does not count as present day!
    assert data["late_count"] == 1
    assert data["total_late_minutes"] == 45
    assert data["total_overtime_minutes"] == 60


def test_overtime_threshold_r3(client):
    client.post("/employees", json={
        "emp_code": "EMP5555",
        "name": "OT Tester",
        "email": "ot@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-01",
    })

    # Punch in 09:30 IST on 2026-07-06
    t_in = int(datetime(2026, 7, 6, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    client.post("/attendance/punch-in", json={"emp_code": "EMP5555", "punched_at": t_in})

    # 18:59:00 IST -> 29 minutes after shift_end (under 30 threshold) -> overtime = 0
    t_out_29 = int(datetime(2026, 7, 6, 13, 29, 0, tzinfo=timezone.utc).timestamp() * 1000)
    res = client.post("/attendance/punch-out", json={"emp_code": "EMP5555", "punched_at": t_out_29})
    assert res.status_code == 200
    assert res.json()["overtime_minutes"] == 0

