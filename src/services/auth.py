# src/services/auth.py
"""Аутентификация: PBKDF2-пароли и сессии в БД (только stdlib).

- Пароль: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
- Сессия: случайный токен в httpOnly-cookie `sid`, в БД — sha256(токен).
"""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta

PBKDF2_ITERATIONS = 200_000
SESSION_TTL = timedelta(days=30)
COOKIE_NAME = "sid"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
