"""Beekeeping Swarm Call Dispatcher — a Plotly Dash app served by Flask.

Run it with::

    python3 app.py            # http://0.0.0.0:8050

A server-side session guards every route, including the Dash callback endpoint,
so no write can reach the database without a signed-in coordinator.
"""

from __future__ import annotations

import env_boot  # noqa: F401  (loads .env before anything reads the environment)

import logging
import os
from datetime import timedelta
from pathlib import Path

import dash
from flask import Flask, jsonify, redirect, request, session, url_for

import auth
import seed as seed_module
from auth import (
    PUBLIC_ENDPOINTS,
    authenticate,
    csrf_ok,
    csrf_token,
    current_user,
    current_user_id,
    guard_request,
    login_rate_limited,
    login_user,
    logout_user,
    record_login_attempt,
    safe_next,
    session_secret,
)
from db import REPORT_STATUSES, session_scope
from services import dispatch as dispatch_service
from services import outcomes as outcome_service
from services import ranking as ranking_service
from services import reports as report_service
from services import volunteers as volunteer_service
from services.errors import ServiceError
from ui import layouts
from ui.signin import PRODUCT_NAME, render_signin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("swarm.dispatcher")

BASE_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Flask server: sessions, static assets, security headers
# --------------------------------------------------------------------------- #
flask_server = Flask(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
)
flask_server.config.update(
    SECRET_KEY=session_secret(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,  # the preview and the first local run are plain HTTP
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    TEMPLATES_AUTO_RELOAD=False,
    JSON_SORT_KEYS=False,
)

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


@flask_server.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


flask_server.before_request(guard_request)

# --------------------------------------------------------------------------- #
# Dash app
# --------------------------------------------------------------------------- #
app = dash.Dash(
    __name__,
    server=flask_server,
    url_base_pathname="/app/",
    title=PRODUCT_NAME,
    update_title=None,
    suppress_callback_exceptions=False,
)
server = app.server
# ``flask run`` looks for a module attribute named ``app`` or ``application``
# and, failing that, scans the module for Flask instances. ``app`` here is the
# Dash object and ``flask_server`` is a second Flask instance, so without this
# alias the CLI aborts with "Detected multiple Flask applications in module
# 'app'". ``.flaskenv`` sets FLASK_APP/FLASK_RUN_HOST/FLASK_RUN_PORT for it.
application = server

app.index_string = """<!DOCTYPE html>
<html lang="en">
    <head>
        {%metas%}
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
        <title>Beekeeping Swarm Call Dispatcher</title>
        <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
        <link rel="stylesheet" href="/static/theme.css">
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
        <script src="/static/app-behaviour.js" defer></script>
    </body>
</html>"""


import callbacks  # noqa: E402,F401  (registers every callback exactly once)


# --------------------------------------------------------------------------- #
# Server-rendered routes
# --------------------------------------------------------------------------- #
@server.route("/")
def index():
    """The front door: into the console when signed in, otherwise to sign-in."""
    if current_user_id():
        return redirect("/app/", code=302)
    return redirect(url_for("signin"), code=302)


@server.route("/health")
def health():
    return jsonify({"status": "ok", "app": PRODUCT_NAME}), 200


@server.route("/signin", methods=["GET", "POST"])
def signin():
    next_target = safe_next(request.values.get("next"))
    error = None
    notice = None
    status = 200

    if request.method == "POST":
        identity = (request.form.get("identity") or "").strip()
        password = request.form.get("password") or ""
        client_key = request.remote_addr or "unknown"

        if not csrf_ok(request.form.get("csrf_token")):
            error = "That sign-in form expired. Please try again."
            status = 400
        elif login_rate_limited(client_key):
            error = "Too many sign-in attempts. Please wait a few minutes and try again."
            status = 429
        else:
            user = authenticate(identity, password)
            if user is None:
                record_login_attempt(client_key)
                # One non-enumerating message for every failure mode.
                error = "Those credentials did not match. Check the demo hint below."
                status = 401
            else:
                login_user(user)
                logger.info("coordinator %s signed in", user.username)
                return redirect(next_target, code=302)
    elif request.args.get("signedout"):
        notice = "You have been signed out. Sign in again to reach the console."
    elif request.args.get("expired"):
        notice = "Please sign in again — your session ended."

    return render_signin(csrf_token(), next_target, error, notice), status


@server.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "POST" and not csrf_ok(request.form.get("csrf_token")):
        logger.warning("logout rejected: missing csrf token")
    logout_user()
    return redirect(url_for("signin", signedout=1), code=302)


# --------------------------------------------------------------------------- #
# JSON API over the same service layer the Dash callbacks use
# --------------------------------------------------------------------------- #
def _payload() -> dict:
    return request.get_json(silent=True) or request.form.to_dict() or {}


@server.errorhandler(ServiceError)
def handle_service_error(exc: ServiceError):
    return jsonify(exc.to_dict()), exc.status


@server.route("/api/session", methods=["GET", "POST", "DELETE"])
def api_session():
    if request.method == "POST":
        user = authenticate(_payload().get("identity", ""), _payload().get("password", ""))
        if user is None:
            return jsonify({"error": "Those credentials did not match."}), 401
        login_user(user)
        return jsonify({"username": user.username, "display_name": user.display_name}), 200
    if request.method == "DELETE":
        logout_user()
        return jsonify({"status": "signed out"}), 200

    user = current_user()
    if user is None:
        return jsonify({"error": "unauthenticated"}), 401
    return jsonify({"username": user.username, "display_name": user.display_name}), 200


@server.route("/api/reports", methods=["GET", "POST"])
def api_reports():
    with session_scope() as db:
        if request.method == "POST":
            created = report_service.create_report(db, _payload(), current_user_id())
            return jsonify(created), 201
        rows = report_service.list_reports(
            db,
            request.args.get("status", "all"),
            request.args.get("urgency", "all"),
            request.args.get("q", ""),
        )
        return jsonify({"reports": rows, "counts": report_service.status_counts(db)}), 200


@server.route("/api/status-summary", methods=["GET"])
def api_status_summary():
    with session_scope() as db:
        return jsonify(
            {
                "counts": report_service.status_counts(db),
                "funnel": outcome_service.funnel(db),
                "statuses": list(REPORT_STATUSES),
            }
        ), 200


@server.route("/api/reports/<int:report_id>/candidates", methods=["GET"])
def api_candidates(report_id: int):
    with session_scope() as db:
        return jsonify(ranking_service.rank_candidates(db, report_id)), 200


@server.route("/api/reports/<int:report_id>/dispatch", methods=["POST"])
def api_dispatch(report_id: int):
    payload = _payload()
    with session_scope() as db:
        if payload.get("mode") == "reassign":
            result = dispatch_service.reassign_dispatch(
                db, report_id, int(payload["volunteer_id"]), current_user_id()
            )
        else:
            result = dispatch_service.confirm_dispatch(
                db, report_id, int(payload["volunteer_id"]), current_user_id()
            )
    return jsonify(result), 201


@server.route("/api/dispatches/<int:dispatch_id>/decline", methods=["POST"])
def api_decline(dispatch_id: int):
    with session_scope() as db:
        result = dispatch_service.decline_dispatch(db, dispatch_id, current_user_id())
    return jsonify(result), 200


@server.route("/api/dispatches/<int:dispatch_id>/cancel", methods=["POST"])
def api_cancel(dispatch_id: int):
    with session_scope() as db:
        result = dispatch_service.cancel_dispatch(db, dispatch_id, current_user_id())
    return jsonify(result), 200


@server.route("/api/volunteers", methods=["GET", "POST"])
def api_volunteers():
    with session_scope() as db:
        if request.method == "POST":
            created = volunteer_service.create_volunteer(db, _payload())
            return jsonify(created), 201
        return (
            jsonify({"volunteers": volunteer_service.list_volunteers(db, request.args.get("availability", "all"))}),
            200,
        )


@server.route("/api/volunteers/<int:volunteer_id>", methods=["PATCH"])
def api_volunteer_patch(volunteer_id: int):
    with session_scope() as db:
        updated = volunteer_service.update_volunteer(db, volunteer_id, _payload())
    return jsonify(updated), 200


@server.route("/api/outcomes", methods=["GET"])
def api_outcomes():
    with session_scope() as db:
        return jsonify(
            {
                "outcomes": outcome_service.list_outcomes(db),
                "funnel": outcome_service.funnel(db),
            }
        ), 200


@server.route("/api/reports/<int:report_id>/outcome", methods=["POST"])
def api_record_outcome(report_id: int):
    with session_scope() as db:
        result = outcome_service.record_outcome(db, report_id, _payload(), current_user_id())
    return jsonify(result), 201


# --------------------------------------------------------------------------- #
# Boot
# --------------------------------------------------------------------------- #
def bootstrap() -> None:
    """Create + seed the database on the normal boot path (idempotent)."""
    counts = seed_module.seed_all()
    logger.info(
        "database ready: %s",
        ", ".join(f"{key}={value}" for key, value in counts.items()),
    )


# Any launch path (python app.py, a WSGI server, the test suite) reaches a
# self-healed, seeded database before the layout is built.
bootstrap()
app.layout = layouts.build_layout(None, "reports")


if __name__ == "__main__":
    # bootstrap() already ran at import (line above) — every launch path reaches
    # a created, seeded database without doing the work twice.
    port = int(os.environ.get("PORT", 8050))
    logger.info("listening on 0.0.0.0:%s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
