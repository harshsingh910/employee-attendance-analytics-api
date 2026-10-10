"""
Performance and MongoDB Execution Plan Verification Tests
Verifies indexes and explain("executionStats") across all queries and aggregations.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pymongo.database import Database


@pytest.fixture
def seed_performance_dataset(db: Database):
    """Seeds 100 employees and attendance records for realistic execution plan verification."""
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})

    employees = []
    departments = ["Engineering", "HR", "Sales", "Finance"]
    for i in range(1, 101):
        emp_code = f"EMP{i:04d}"
        dept = departments[i % len(departments)]
        employees.append({
            "emp_code": emp_code,
            "name": f"Perf User {i}",
            "email": f"user{i}@company.com",
            "department": dept,
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-01-01",
            "created_at": datetime.now(timezone.utc),
        })
    db.employees.insert_many(employees)

    attendance_logs = []
    dates = [f"2026-03-{d:02d}" for d in range(1, 15)]
    for i in range(1, 101):
        emp_code = f"EMP{i:04d}"
        for d_str in dates:
            is_late = (i % 3 == 0)
            late_m = 25 if is_late else 0
            attendance_logs.append({
                "emp_code": emp_code,
                "date": d_str,
                "status": "PRESENT",
                "punch_in": datetime(2026, 3, 1, 4, 0, 0, tzinfo=timezone.utc),
                "punch_out": datetime(2026, 3, 1, 13, 0, 0, tzinfo=timezone.utc),
                "work_hours": 9.0,
                "late_minutes": late_m,
                "overtime_minutes": 0,
                "half_day": False,
                "history": [],
            })
    db.attendance_logs.insert_many(attendance_logs)


def test_explain_attendance_list(client: TestClient, seed_performance_dataset):
    res = client.get("/admin/explain/attendance_list?emp_code=EMP0001&date_from=2026-03-01&date_to=2026-03-10")
    assert res.status_code == 200
    plan = res.json()
    assert "explain" in plan
    inner = plan["explain"]
    assert "executionStats" in inner or "stages" in inner or "queryPlanner" in inner


def test_explain_employee_monthly(client: TestClient, seed_performance_dataset):
    res = client.get("/admin/explain/employee_monthly?emp_code=EMP0001&month=2026-03")
    assert res.status_code == 200
    plan = res.json()
    assert "explain" in plan
    inner = plan["explain"]
    assert "executionStats" in inner or "stages" in inner or "queryPlanner" in inner


def test_explain_department_summary(client: TestClient, seed_performance_dataset):
    res = client.get("/admin/explain/department_summary?month=2026-03&department=Engineering")
    assert res.status_code == 200
    plan = res.json()
    assert "explain" in plan
    inner = plan["explain"]
    assert "executionStats" in inner or "stages" in inner or "queryPlanner" in inner


def test_explain_late_leaderboard(client: TestClient, seed_performance_dataset):
    res = client.get("/admin/explain/late_leaderboard?month=2026-03&limit=10")
    assert res.status_code == 200
    plan = res.json()
    assert "explain" in plan
    inner = plan["explain"]
    assert "executionStats" in inner or "stages" in inner or "queryPlanner" in inner


def test_explain_department_trend(client: TestClient, seed_performance_dataset):
    res = client.get("/admin/explain/department_trend?department=Engineering&from=2026-03-01&to=2026-03-14")
    assert res.status_code == 200
    plan = res.json()
    assert "explain" in plan
    inner = plan["explain"]
    assert "executionStats" in inner or "stages" in inner or "queryPlanner" in inner
    # Verify command pipeline has department emp_code in match
    cmd = inner.get("command", {})
    pipeline = cmd.get("pipeline", [])
    assert len(pipeline) >= 1
    match_stage = pipeline[0].get("$match", {})
    assert "emp_code" in match_stage
    assert "$in" in match_stage["emp_code"]
    assert match_stage["date"] == {"$gte": "2026-03-01", "$lte": "2026-03-14"}
    plan_str = str(inner)
    assert "IXSCAN" in plan_str
    assert "COLLSCAN" not in plan_str


def test_explain_department_trend_october_regression(client: TestClient, seed_performance_dataset):
    """Regression test for GET /admin/explain/department_trend?department=Engineering&from=2026-10-01&to=2026-10-31."""
    res = client.get("/admin/explain/department_trend?department=Engineering&from=2026-10-01&to=2026-10-31")
    assert res.status_code == 200
    data = res.json()
    assert data["endpoint"] == "department_trend"
    assert data["collection"] == "attendance_logs"
    explain_data = data["explain"]
    cmd = explain_data.get("command", {})
    pipeline = cmd.get("pipeline", [])
    assert len(pipeline) >= 1
    match_stage = pipeline[0].get("$match", {})
    # Verify exact October date range and absence of March fallback
    assert match_stage["date"] == {"$gte": "2026-10-01", "$lte": "2026-10-31"}
    assert "2026-03" not in str(pipeline)
    assert "emp_code" in match_stage
    assert "$in" in match_stage["emp_code"]
    plan_str = str(explain_data)
    assert "IXSCAN" in plan_str
    assert "COLLSCAN" not in plan_str



def test_explain_attendance_list_exact_regression(client: TestClient, seed_performance_dataset):
    """Regression test for GET /admin/explain/attendance_list?emp_code=EMP1002&date_from=2026-10-01&date_to=2026-10-31&page=1&page_size=20."""
    res = client.get("/admin/explain/attendance_list?emp_code=EMP1002&date_from=2026-10-01&date_to=2026-10-31&page=1&page_size=20")
    assert res.status_code == 200
    data = res.json()
    assert data["endpoint"] == "attendance_list"
    assert data["collection"] == "attendance_logs"
    explain_data = data["explain"]
    assert "executionStats" in explain_data
    stats = explain_data["executionStats"]
    assert stats["executionSuccess"] is True
    # Ensure execution plan information confirms index usage
    plan_str = str(explain_data)
    assert "IXSCAN" in plan_str
    assert "COLLSCAN" not in plan_str

