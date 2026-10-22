"""Password hashing (PBKDF2-SHA256, stdlib only) and login helpers."""

import hashlib
import hmac
import re
import secrets

import db

ITERATIONS = 260_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(check, digest)


def signup(name, email, phone, password, confirm):
    """Returns (user, error)."""
    if not name.strip() or not email.strip() or not password:
        return None, "Name, email and password are required."
    if not EMAIL_RE.match(email.strip()):
        return None, "Enter a valid email address."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."
    if password != confirm:
        return None, "Passwords don't match."
    if db.get_user_by_email(email):
        return None, "An account with this email already exists. Please log in."
    db.create_user(name, email, phone, hash_password(password))
    return db.get_user_by_email(email), None


def login(email, password):
    """Returns (user, error)."""
    user = db.get_user_by_email(email or "")
    if not user or not verify_password(password or "", user["password_hash"]):
        return None, "Invalid email or password."
    return user, None
