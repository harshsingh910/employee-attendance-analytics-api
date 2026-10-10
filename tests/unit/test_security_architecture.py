"""
Unit Tests for Security Architecture, Password Policy, and RBAC Scoping
Verifies Argon2id password hashing, NIST SP 800-63B password validation,
and role-based authorization rules.
"""
import pytest

from app.core.security import (
    GENERIC_AUTH_ERROR_DETAIL,
    PasswordValidationError,
    Role,
    hash_password,
    validate_password,
    verify_employee_scope,
    verify_password,
)


def test_password_length_validation():
    """Passwords shorter than 12 characters must be rejected."""
    with pytest.raises(PasswordValidationError) as exc:
        validate_password("Short123456")  # 11 characters
    assert "at least 12 characters" in str(exc.value)

    # Empty and whitespace passwords must be rejected
    with pytest.raises(PasswordValidationError):
        validate_password("")

    with pytest.raises(PasswordValidationError):
        validate_password("   ")


def test_password_whitespace_and_length_boundaries():
    """Passwords with leading/trailing whitespace or exceeding 128 characters must be rejected."""
    with pytest.raises(PasswordValidationError) as exc:
        validate_password("  validpassphrase123  ")
    assert "whitespace" in str(exc.value)

    # Valid 12-character password accepted
    valid_12 = "SecurePass12"
    assert validate_password(valid_12) == valid_12

    # Long passphrases (up to 128 chars) supported without silent truncation
    long_passphrase = "correct-horse-battery-staple-twenty-four-words-long-and-extremely-memorable-secure-passphrase"
    assert validate_password(long_passphrase) == long_passphrase

    # > 128 chars rejected
    too_long = "a" * 129
    with pytest.raises(PasswordValidationError) as exc:
        validate_password(too_long)
    assert "maximum" in str(exc.value)


def test_common_passwords_rejected_without_leaking_plaintext():
    """Common compromised passwords must be rejected without echoing password in error."""
    secret = "password1234"
    with pytest.raises(PasswordValidationError) as exc:
        validate_password(secret)
    # Ensure error message does not echo the submitted secret
    assert secret not in str(exc.value)
    assert "too common" in str(exc.value)


def test_argon2id_hashing_and_verification():
    """Passwords must be hashed with Argon2id and verified in constant time."""
    secret = "MyVeryStrongPassphrase2026!"
    hashed = hash_password(secret)

    # Stored string must be an encoded hash, never plaintext
    assert hashed != secret
    assert hashed.startswith("$argon2id$")

    # Correct password succeeds
    assert verify_password(secret, hashed) is True

    # Incorrect password fails
    assert verify_password("WrongPassword123!", hashed) is False

    # Empty/None password fails safely
    assert verify_password("", hashed) is False
    assert verify_password(secret, "") is False

    # Malformed / corrupted hash fails safely without unhandled exceptions
    assert verify_password(secret, "invalid-raw-hash-format") is False
    assert verify_password(secret, "$argon2id$v=19$m=65536,t=2,p=1$malformed$hash") is False


def test_password_validation_unicode_and_error_leak_prevention():
    """Unicode passphrases with multibyte characters and symbols are supported safely."""
    unicode_pass = "SecurePassphrase🔐WithSpecialChars!#@$"
    assert validate_password(unicode_pass) == unicode_pass

    # Ensure validation error does not leak secret on length failure
    too_short_secret = "Short🔐12"
    with pytest.raises(PasswordValidationError) as exc:
        validate_password(too_short_secret)
    assert too_short_secret not in str(exc.value)


def test_rbac_authorization_scoping():
    """Enforces authorization boundaries between employees, managers, and administrators."""
    # ADMIN: full access across any employee or department
    assert verify_employee_scope(
        actor_role=Role.ADMIN,
        actor_emp_code="ADMIN001",
        target_emp_code="EMP0001",
    ) is True

    # MANAGER: permitted to access employees in same department
    assert verify_employee_scope(
        actor_role=Role.MANAGER,
        actor_emp_code="MGR0001",
        target_emp_code="EMP0002",
        actor_department="Engineering",
        target_department="Engineering",
    ) is True

    # MANAGER: rejected when targeting employee in different department
    assert verify_employee_scope(
        actor_role=Role.MANAGER,
        actor_emp_code="MGR0001",
        target_emp_code="EMP0003",
        actor_department="Engineering",
        target_department="Sales",
    ) is False

    # MANAGER: rejected when actor or target department is missing/None
    assert verify_employee_scope(
        actor_role=Role.MANAGER,
        actor_emp_code="MGR0001",
        target_emp_code="EMP0002",
        actor_department=None,
        target_department="Engineering",
    ) is False

    assert verify_employee_scope(
        actor_role=Role.MANAGER,
        actor_emp_code="MGR0001",
        target_emp_code="EMP0002",
        actor_department="Engineering",
        target_department=None,
    ) is False

    # MANAGER: permitted to access self even if departments are unspecified
    assert verify_employee_scope(
        actor_role=Role.MANAGER,
        actor_emp_code="MGR0001",
        target_emp_code="MGR0001",
        actor_department=None,
        target_department=None,
    ) is True

    # EMPLOYEE: permitted to access self
    assert verify_employee_scope(
        actor_role=Role.EMPLOYEE,
        actor_emp_code="EMP0001",
        target_emp_code="EMP0001",
    ) is True

    # EMPLOYEE: strictly forbidden from accessing another employee's records
    assert verify_employee_scope(
        actor_role=Role.EMPLOYEE,
        actor_emp_code="EMP0001",
        target_emp_code="EMP0002",
    ) is False


def test_generic_auth_failure_message_prevents_enumeration():
    """Authentication failures must use a generic message to prevent account enumeration."""
    assert GENERIC_AUTH_ERROR_DETAIL == "Invalid username or password"
    assert "not found" not in GENERIC_AUTH_ERROR_DETAIL.lower()
    assert "user" in GENERIC_AUTH_ERROR_DETAIL.lower() and "password" in GENERIC_AUTH_ERROR_DETAIL.lower()

