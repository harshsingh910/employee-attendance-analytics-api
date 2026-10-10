"""
Security, Password Hashing, and Role-Based Authorization Core Module

Implements NIST SP 800-63B password validation, Argon2id hashing, and role-based
authorization scoping for portfolio-extended architecture.

IMPORTANT ARCHITECTURAL SCOPE NOTE:
The official assignment API specification (openapi.yaml) mandates 12 public, unauthenticated
endpoints without user registration or login routes (/auth/login, /auth/register).
The functions in this module provide verified cryptographic and authorization utilities
designed for future authenticated extensions. They are NOT actively wired into or enforced
on the 12 public HTTP routes, preserving strict parity with the official assignment API contract.
"""
import enum
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

# Standard common passwords to reject (OWASP Top 10 / NIST SP 800-63B guidance)
COMMON_PASSWORDS = {
    "password1234",
    "password12345",
    "admin12345678",
    "qwertyuiop123",
    "welcome123456",
    "changeme12345",
    "letmein123456",
    "iloveyou12345",
    "monkey1234567",
    "dragon1234567",
}

# Module-level PasswordHasher configured for Argon2id
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # 19 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


class Role(str, enum.Enum):
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class PasswordValidationError(ValueError):
    """Raised when password policy criteria are violated."""
    pass


class AuthorizationError(PermissionError):
    """Raised when an actor lacks permission to access target resources."""
    pass


# Generic error message to prevent account enumeration
GENERIC_AUTH_ERROR_DETAIL = "Invalid username or password"


def validate_password(password: str) -> str:
    """
    Validates password against modern NIST SP 800-63B guidelines:
    - Minimum length: 12 characters.
    - Maximum length: 128 characters (supports long passphrases without truncation).
    - No silent truncation.
    - Rejects empty, whitespace-only, and well-known compromised passwords.
    - Avoids arbitrary character combination rules.
    - Never echoes the submitted password in error messages.
    """
    if not password or not isinstance(password, str):
        raise PasswordValidationError("Password must not be empty.")

    if len(password) < 12:
        raise PasswordValidationError("Password must be at least 12 characters long.")

    if len(password) > 128:
        raise PasswordValidationError("Password exceeds maximum allowed length of 128 characters.")

    if password.strip() != password:
        raise PasswordValidationError("Password must not contain leading or trailing whitespace.")

    normalized = password.lower().strip()
    if normalized in COMMON_PASSWORDS:
        raise PasswordValidationError("Password is too common or easily guessable. Please choose a stronger passphrase.")

    return password


def hash_password(password: str) -> str:
    """
    Encodes password using Argon2id with cryptographically random salt.
    Never stores plaintext passwords or uses legacy MD5/SHA-256.
    """
    validate_password(password)
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Constant-time verification of a plaintext password against an Argon2id hash.
    Returns True if valid, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False
    except Exception:
        return False


def verify_employee_scope(
    actor_role: Role,
    actor_emp_code: str,
    target_emp_code: str,
    actor_department: Optional[str] = None,
    target_department: Optional[str] = None,
) -> bool:
    """
    Enforces role-based authorization and employee privacy boundaries:
    - ADMIN: Full access across all employees and departments.
    - MANAGER: Access to employees within permitted department.
    - EMPLOYEE: Strictly limited to own records (actor_emp_code == target_emp_code).
    """
    if actor_role == Role.ADMIN:
        return True

    if actor_role == Role.MANAGER:
        if actor_emp_code == target_emp_code:
            return True
        if actor_department and target_department and actor_department == target_department:
            return True
        return False

    if actor_role == Role.EMPLOYEE:
        return actor_emp_code == target_emp_code

    return False
