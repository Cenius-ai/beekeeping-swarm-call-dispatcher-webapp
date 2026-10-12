"""Coordinator authentication: password hashing, session sign-in, CSRF and the
server-side guard that protects *every* route — including the Dash callback
endpoint.

There is a single seeded coordinator account for the MVP; every helper here
works through the same hashing path so the seed can never create a credential
the sign-in rejects.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time

from flask import jsonify, redirect, request, session, url_for
from sqlalchemy import func, or_, select
from werkzeug.security import check_password_hash, generate_password_hash

from db import User, get_session

logger = logging.getLogger(__name__)

#: Session key holding the signed-in coordinator's primary key.
SESSION_USER_KEY = "coordinator_id"
SESSION_CSRF_KEY = "csrf_token"
SESSION_STARTED_KEY = "signed_in_at"

#: True only when the request is an unauthenticated *page load*.
PAGE_METHODS = ("GET", "HEAD", "OPTIONS")

# Paths that never require a session. Everything else is denied by default.
PUBLIC_PATH_PREFIXES = ("/static/",)
PUBLIC_ENDPOINTS = {"signin", "logout", "health"}

#: Endpoints Dash talks to during a callback round trip.
DASH_CALLBACK_SUFFIX = "_dash-update-component"

# Login throttling: per-IP sliding window held in process (single instance).
LOGIN_WINDOW_SECONDS = 900
LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[str, list[float]] = {}


def hash_password(password: str) -> str:
    """Hash a password with werkzeug's PBKDF2-SHA256 (the login scheme)."""
    return generate_password_hash(password, method="pbkdf2:sha256:600000")


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time password verification against a stored hash."""
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def find_user_by_identity(session_db, identity: str) -> User | None:
    """Look a coordinator up by username *or* email (case-insensitive)."""
    needle = (identity or "").strip().lower()
    if not needle:
        return None
    return session_db.execute(
        select(User).where(
            or_(func.lower(User.username) == needle, func.lower(User.email) == needle)
        )
    ).scalar_one_or_none()


def authenticate(identity: str, password: str) -> User | None:
    """Return the matching coordinator, or ``None`` for bad credentials."""
    db = get_session()
    try:
        user = find_user_by_identity(db, identity)
        if user is None:
            # Still burn a hash comparison so a missing account and a wrong
            # password take the same time (no account enumeration).
            verify_password(hash_password("placeholder"), password)
            return None
        if not verify_password(user.password_hash, password):
            return None
        db.expunge(user)
        return user
    finally:
        db.close()


def login_user(user: User) -> None:
    """Start a fresh server-side session for *user* (rotates the session id)."""
    session.clear()
    session.permanent = True
    session[SESSION_USER_KEY] = int(user.id)
    session[SESSION_STARTED_KEY] = int(time.time())
    session[SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def logout_user() -> None:
    """Invalidate the session server-side."""
    session.clear()


def current_user_id() -> int | None:
    value = session.get(SESSION_USER_KEY)
    return int(value) if value else None


def current_user() -> User | None:
    """The signed-in coordinator, or ``None``."""
    user_id = current_user_id()
    if not user_id:
        return None
    db = get_session()
    try:
        user = db.get(User, user_id)
        if user is not None:
            db.expunge(user)
        return user
    finally:
        db.close()


def csrf_token() -> str:
    """Session-bound CSRF token, minted on first use."""
    token = session.get(SESSION_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[SESSION_CSRF_KEY] = token
    return token


def csrf_ok(submitted: str | None) -> bool:
    expected = session.get(SESSION_CSRF_KEY)
    if not expected or not submitted:
        return False
    return hmac.compare_digest(str(expected), str(submitted))


def login_rate_limited(client_key: str) -> bool:
    """True when *client_key* has burnt through its sign-in attempts."""
    now = time.monotonic()
    window = [t for t in _login_attempts.get(client_key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[client_key] = window
    return len(window) >= LOGIN_MAX_ATTEMPTS


def record_login_attempt(client_key: str) -> None:
    """Count one failed sign-in attempt for throttling."""
    attempts = _login_attempts.setdefault(client_key, [])
    attempts.append(time.monotonic())
    # Keep the map from growing without bound on a long-lived process.
    if len(_login_attempts) > 2048:
        for key in [k for k, v in _login_attempts.items() if not v]:
            _login_attempts.pop(key, None)


def _wants_json() -> bool:
    if request.path.startswith("/api/"):
        return True
    if request.path.endswith(DASH_CALLBACK_SUFFIX):
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    return request.accept_mimetypes.best == "application/json"


def guard_request():
    """Fail closed: deny every request that has no valid server-side session.

    Page loads are redirected to the sign-in screen; API and Dash callback
    calls get a 401 JSON body so the browser never mistakes a rejected write
    for a successful one.
    """
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    for prefix in PUBLIC_PATH_PREFIXES:
        if request.path.startswith(prefix):
            return None

    if current_user_id():
        return None

    if _wants_json() or request.method not in PAGE_METHODS:
        return jsonify({"error": "unauthenticated", "message": "Sign in to continue."}), 401

    # Remember where they were headed so sign-in can return them there.
    target = request.full_path if request.query_string else request.path
    return redirect(url_for("signin", next=target), code=302)


def safe_next(target: str | None) -> str:
    """Only ever bounce to a same-site path (no open redirects)."""
    if not target:
        return "/app"
    if not target.startswith("/") or target.startswith("//"):
        return "/app"
    if target.startswith("/signin"):
        return "/app"
    return target


def session_secret() -> str:
    """Session signing key: env-supplied, with a clearly-marked dev fallback."""
    return os.environ.get("SECRET_KEY") or "cenius-dev-9f2c41a7bd6e5038"
