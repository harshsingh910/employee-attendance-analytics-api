"""
Concurrency and Race Condition Tests
Tests thread-level concurrent requests against MongoDB unique indexes and atomic updates:
1. Concurrent employee creations with identical emp_code.
2. Concurrent punch-ins on identical date.
3. Concurrent punch-outs on open punch-in record.
"""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


def test_concurrent_employee_creation_race(client: TestClient):
    payload = {
        "emp_code": "EMP4444",
        "name": "Race Employee",
        "email": "race@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    }

    def attempt_create(_):
        return client.post("/employees", json=payload)

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(attempt_create, range(8)))

    status_codes = [r.status_code for r in responses]
    assert status_codes.count(201) == 1
    assert status_codes.count(409) == 7


def test_concurrent_punch_in_race(client: TestClient):
    client.post("/employees", json={
        "emp_code": "EMP5555",
        "name": "Punch In Race",
        "email": "racein@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })

    punch_ms = 1772424300000

    def attempt_punch_in(_):
        return client.post("/attendance/punch-in", json={
            "emp_code": "EMP5555",
            "punched_at": punch_ms,
        })

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(attempt_punch_in, range(8)))

    status_codes = [r.status_code for r in responses]
    assert status_codes.count(201) == 1
    assert status_codes.count(409) == 7


def test_concurrent_punch_out_race(client: TestClient):
    client.post("/employees", json={
        "emp_code": "EMP6666",
        "name": "Punch Out Race",
        "email": "raceout@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01",
    })

    punch_in_ms = 1772424300000
    client.post("/attendance/punch-in", json={
        "emp_code": "EMP6666",
        "punched_at": punch_in_ms,
    })

    punch_out_ms = 1772456700000

    def attempt_punch_out(_):
        return client.post("/attendance/punch-out", json={
            "emp_code": "EMP6666",
            "punched_at": punch_out_ms,
        })

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(attempt_punch_out, range(8)))

    status_codes = [r.status_code for r in responses]
    assert status_codes.count(200) == 1
    assert status_codes.count(409) == 7
