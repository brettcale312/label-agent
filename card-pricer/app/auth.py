"""
auth.py
-------
Authentication primitives for the multi-tenant card-pricer:

- `hash_password` / `verify_password` — bcrypt
- `make_session_token` / `read_session_token` — itsdangerous-signed (user_id, ts) tuples
- `make_invite_token` — 32-byte URL-safe token for invite emails
- `AuthMiddleware` — validates the session cookie on every request and attaches
  `request.state.user` + `request.state.account_id`. Unauthenticated HTML
  requests redirect to /login; unauthenticated API requests get 401.
"""

import os
import secrets
import time
import logging
from typing import Optional

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import database

logger = logging.getLogger("auth")

SESSION_COOKIE = "card_pricer_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days

# Paths that bypass auth entirely.
PUBLIC_PATHS = (
    "/login",
    "/logout",
    "/invite/accept",
    "/static/",
    "/favicon.ico",
    "/health",
)


def _get_serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError(
            "SESSION_SECRET env var is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return URLSafeTimedSerializer(secret, salt="card-pricer-session")


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Session tokens
# ─────────────────────────────────────────────────────────────────────────────

def make_session_token(user_id: int) -> str:
    return _get_serializer().dumps(user_id)


def read_session_token(token: str) -> Optional[int]:
    try:
        return _get_serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def set_session_cookie(response: Response, user_id: int):
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.getenv("RAILWAY_ENVIRONMENT") is not None,  # HTTPS-only in prod
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE)


# ─────────────────────────────────────────────────────────────────────────────
# Invite tokens
# ─────────────────────────────────────────────────────────────────────────────

def make_invite_token() -> str:
    return secrets.token_urlsafe(32)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public paths skip auth entirely.
        if any(path == p or path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        user_id = read_session_token(token) if token else None
        user = database.get_user(user_id) if user_id else None

        if not user:
            # Unauthenticated. Redirect HTML, 401 API.
            if path.startswith("/api/"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse(url=f"/login?next={path}", status_code=302)

        request.state.user = user
        request.state.account_id = user["account_id"]
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience for routes
# ─────────────────────────────────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    """Returns the logged-in user dict. Assumes AuthMiddleware has run.
    Raises if called on a public path where state isn't set."""
    return request.state.user


def current_account_id(request: Request) -> int:
    return request.state.account_id


def require_owner(request: Request):
    """Raise 403 if the current user is not an owner."""
    from fastapi import HTTPException
    if request.state.user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
