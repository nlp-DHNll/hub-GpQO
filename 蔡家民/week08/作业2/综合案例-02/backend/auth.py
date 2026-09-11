# -*- coding: utf-8 -*-
"""共享密码认证：PBKDF2 哈希、24 小时签名 HttpOnly Cookie。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request, status

from . import config

COOKIE_NAME = "research_session"


def hash_password(password: str, iterations: int = 260_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str) -> bool:
    configured = config.SHARED_PASSWORD_HASH
    if not configured:
        return False
    try:
        scheme, count, salt_b64, digest_b64 = configured.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(count))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_session() -> str:
    expires = int(time.time()) + config.SESSION_TTL_SECONDS
    payload = str(expires)
    signature = hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def is_valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.split(".", 1)
    expected = hmac.new(config.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(signature, expected) and int(payload) > int(time.time())
    except ValueError:
        return False


def require_auth(request: Request) -> None:
    if not is_valid_session(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")


if __name__ == "__main__":
    print("示例密码哈希（请复制到 SHARED_PASSWORD_HASH）:")
    print(hash_password(os.getenv("PASSWORD", "change-me")))
