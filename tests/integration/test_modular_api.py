"""
Integration Tests for Modular REST API Routers
Tests all endpoints, parameters, validations, status codes, and response schemas.
"""
from fastapi.testclient import TestClient


def test_api_health(client: TestClient):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_api_employee_workflow(client: TestClient):
    emp_payload = {
        "emp_code": "EMP8888",
        "name": "Integration Tester",
        "email": "integration@example.com",
        "department": "QA",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-02-01",
    }
    # Create employee
    res = client.post("/employees", json=emp_payload)
    assert res.status_code == 201
    created = res.json()
    assert created["emp_code"] == "EMP8888"
    assert created["name"] == "Integration Tester"

    # Duplicate creation yields 409
    res_dup = client.post("/employees", json=emp_payload)
    assert res_dup.status_code == 409

    # List employees
    res_list = client.get("/employees?department=QA")
    assert res_list.status_code == 200
    data = res_list.json()
    assert data["total"] == 1
    assert data["items"][0]["emp_code"] == "EMP8888"


def test_api_attendance_workflow(client: TestClient):
    # Setup employee
    client.post("/employees", json={
        "emp_code": "EMP9999",
        "name": "Punch Tester",
        "email": "punch@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })

    # Punch-in at 09:35 IST (04:05 UTC) on 2026-03-02 -> epoch ms: 1772424300000
    punch_in_ms = 1772424300000
    res_in = client.post("/attendance/punch-in", json={
        "emp_code": "EMP9999",
        "punched_at": punch_in_ms,
        "status": "PRESENT",
    })
    assert res_in.status_code == 201
    rec_in = res_in.json()
    assert rec_in["emp_code"] == "EMP9999"
    assert rec_in["date"] == "2026-03-02"
    assert rec_in["punch_in"] == punch_in_ms
    assert rec_in["punch_out"] is None
    assert rec_in["late_minutes"] == 0

    # Duplicate punch-in for same date yields 409
    res_in_dup = client.post("/attendance/punch-in", json={
        "emp_code": "EMP9999",
        "punched_at": punch_in_ms + 1000,
    })
    assert res_in_dup.status_code == 409

    # Punch-out at 18:35 IST (13:05 UTC) -> 9.0 hours -> 1772456700000
    punch_out_ms = 1772456700000
    res_out = client.post("/attendance/punch-out", json={
        "emp_code": "EMP9999",
        "punched_at": punch_out_ms,
    })
    assert res_out.status_code == 200
    rec_out = res_out.json()
    assert rec_out["punch_out"] == punch_out_ms
    assert rec_out["work_hours"] == 9.0
    assert rec_out["half_day"] is False

    # Second punch-out yields 409
    res_out_dup = client.post("/attendance/punch-out", json={
        "emp_code": "EMP9999",
        "punched_at": punch_out_ms + 1000,
    })
    assert res_out_dup.status_code == 409

    # Regularize record
    res_reg = client.patch("/attendance/EMP9999/2026-03-02", json={
        "status": "WFH",
        "reason": "Approved work from home request",
        "regularized_by": "Manager Dave",
    })
    assert res_reg.status_code == 200
    rec_reg = res_reg.json()
    assert rec_reg["status"] == "WFH"
    assert len(rec_reg["history"]) == 1
    assert rec_reg["history"][0]["by"] == "Manager Dave"


def test_api_analytics_endpoints(client: TestClient):
    client.post("/employees", json={
        "emp_code": "EMP7777",
        "name": "Analytics User",
        "email": "analytics@example.com",
        "department": "Finance",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-03-01",
    })

    # Punch-in with late minutes: 10:15 IST (04:45 UTC) -> 45 minutes late
    punch_in_ms = 1772426700000
    client.post("/attendance/punch-in", json={
        "emp_code": "EMP7777",
        "punched_at": punch_in_ms,
    })

    # Monthly analytics
    res_m = client.get("/analytics/employees/EMP7777/monthly?month=2026-03")
    assert res_m.status_code == 200
    data_m = res_m.json()
    assert data_m["emp_code"] == "EMP7777"
    assert data_m["late_count"] == 1
    assert data_m["total_late_minutes"] == 45

    # Department summary
    res_dept = client.get("/analytics/departments/summary?month=2026-03&department=Finance")
    assert res_dept.status_code == 200
    data_dept = res_dept.json()
    assert len(data_dept["items"]) == 1
    assert data_dept["items"][0]["department"] == "Finance"
    assert data_dept["items"][0]["headcount"] == 1

    # Leaderboard
    res_lead = client.get("/analytics/leaderboard/late?month=2026-03&limit=5")
    assert res_lead.status_code == 200
    data_lead = res_lead.json()
    assert len(data_lead["items"]) >= 1
    assert data_lead["items"][0]["emp_code"] == "EMP7777"
    assert data_lead["items"][0]["rank"] == 1

    # Department trend
    res_trend = client.get("/analytics/departments/Finance/trend?from=2026-03-01&to=2026-03-07")
    assert res_trend.status_code == 200
    data_trend = res_trend.json()
    assert data_trend["department"] == "Finance"
    assert len(data_trend["items"]) == 7  # densified full 7 days
