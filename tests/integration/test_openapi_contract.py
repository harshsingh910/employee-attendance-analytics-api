"""
Automated OpenAPI Contract Verification Test
Validates runtime FastAPI OpenAPI schema against the supplied official openapi.yaml.
Ensures path parity, HTTP method parity, status code parity, and schema compatibility.
"""
from pathlib import Path

import yaml

from app.main import app


def test_openapi_schema_path_and_method_parity():
    spec_path = Path(__file__).parent.parent.parent / "openapi.yaml"
    assert spec_path.exists(), f"Official openapi.yaml not found at {spec_path}"

    with open(spec_path, "r", encoding="utf-8") as f:
        official_spec = yaml.safe_load(f)

    runtime_spec = app.openapi()

    official_paths = set(official_spec.get("paths", {}).keys())
    runtime_paths = set(runtime_spec.get("paths", {}).keys())

    # Check path parity
    missing_paths = official_paths - runtime_paths
    extra_paths = runtime_paths - official_paths
    assert not missing_paths, f"Missing OpenAPI paths in runtime application: {missing_paths}"
    assert not extra_paths, f"Unexpected extra OpenAPI paths in runtime application: {extra_paths}"

    # Check operation methods parity for each path
    for path in official_paths:
        official_methods = {
            m.lower() for m in official_spec["paths"][path].keys() if m != "parameters"
        }
        runtime_methods = {
            m.lower() for m in runtime_spec["paths"][path].keys() if m != "parameters"
        }
        assert official_methods == runtime_methods, (
            f"HTTP Method mismatch on path '{path}': "
            f"official={official_methods}, runtime={runtime_methods}"
        )


def test_openapi_all_12_operations_defined():
    runtime_spec = app.openapi()
    total_operations = 0
    paths = runtime_spec.get("paths", {})
    for path, methods in paths.items():
        for method, details in methods.items():
            if method.lower() in ("get", "post", "put", "patch", "delete"):
                total_operations += 1

    # Exactly 12 operations across 11 path endpoints
    assert total_operations == 12, f"Expected 12 endpoint operations, found {total_operations}"


def test_openapi_explain_endpoint_response_schema():
    runtime_spec = app.openapi()
    explain_path = runtime_spec.get("paths", {}).get("/admin/explain/{endpoint}", {})
    assert "get" in explain_path, "GET /admin/explain/{endpoint} not registered"
    get_op = explain_path["get"]

    # Verify 200 response exists
    responses = get_op.get("responses", {})
    assert "200" in responses, "200 response not defined for /admin/explain/{endpoint}"


def test_openapi_response_status_codes_parity():
    spec_path = Path(__file__).parent.parent.parent / "openapi.yaml"
    with open(spec_path, "r", encoding="utf-8") as f:
        official_spec = yaml.safe_load(f)

    runtime_spec = app.openapi()

    for path, path_item in official_spec["paths"].items():
        for method, op in path_item.items():
            if method == "parameters":
                continue
            official_responses = set(op.get("responses", {}).keys())
            runtime_responses = set(runtime_spec["paths"][path][method.lower()].get("responses", {}).keys())

            # All official response status codes must be documented in runtime schema
            missing_codes = official_responses - runtime_responses
            assert not missing_codes, (
                f"Missing response status codes for {method.upper()} {path}: {missing_codes}"
            )


def test_openapi_request_body_schemas_and_required_fields():
    runtime_spec = app.openapi()
    components = runtime_spec.get("components", {}).get("schemas", {})

    # Check EmployeeCreate required fields exactly match openapi.yaml
    emp_create = components.get("EmployeeCreate", {})
    required_emp_fields = set(emp_create.get("required", []))
    expected_emp_fields = {"emp_code", "name", "email", "department", "joined_on"}
    assert required_emp_fields == expected_emp_fields, (
        f"EmployeeCreate required fields mismatch: found {required_emp_fields}, expected {expected_emp_fields}"
    )

    # Check PunchInRequest required fields exactly match openapi.yaml
    punch_in = components.get("PunchInRequest", {})
    assert set(punch_in.get("required", [])) == {"emp_code"}

    # Check PunchOutRequest required fields exactly match openapi.yaml
    punch_out = components.get("PunchOutRequest", {})
    assert set(punch_out.get("required", [])) == {"emp_code"}

    # Check RegularizeRequest required fields exactly match openapi.yaml
    regularize = components.get("RegularizeRequest", {})
    assert set(regularize.get("required", [])) == {"regularized_by", "reason"}
