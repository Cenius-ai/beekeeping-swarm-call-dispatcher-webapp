"""Swarm report intake, triage queries and the canonical status summary."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from data import sites as site_catalogue
from db import (
    CLUSTER_SIZE_BUCKETS,
    REPORT_STATUSES,
    STATUS_LABELS,
    URGENCIES,
    Dispatch,
    SwarmReport,
    User,
    Volunteer,
    utcnow_iso,
)
from services.errors import NotFoundError, ValidationError

#: How long an identical intake payload is treated as a double submit.
DUPLICATE_WINDOW_SECONDS = 6

PHONE_RE = re.compile(r"^[0-9]{7,15}$")


def _digits(value: str) -> str:
    return re.sub(r"[^0-9]", "", value or "")


def normalise_phone(value: str) -> str:
    """Keep the human formatting but reject anything that is not 7-15 digits."""
    raw = (value or "").strip()
    digits = _digits(raw)
    if not PHONE_RE.match(digits):
        raise ValidationError("Enter a phone number with 7 to 15 digits.", field="caller_phone")
    return raw


def display_volunteer(report: SwarmReport) -> Volunteer | None:
    """The collector shown in the 'Assigned volunteer' column.

    Only the dispatch that is still active (``confirmed``) or that actually
    carried out the work (``completed``) counts. Declined, cancelled and
    reassigned-away dispatches never surface here.
    """
    confirmed = [d for d in report.dispatches if d.state == "confirmed"]
    if confirmed:
        return confirmed[-1].volunteer
    completed = [d for d in report.dispatches if d.state == "completed"]
    if completed:
        return completed[-1].volunteer
    return None


def active_dispatch(report: SwarmReport) -> Dispatch | None:
    """The single open dispatch for *report*, or ``None``."""
    for dispatch in reversed(report.dispatches):
        if dispatch.state == "confirmed":
            return dispatch
    return None


def serialize_report(report: SwarmReport) -> dict:
    """Plain-dict view of a report, including its logger and collector."""
    logger_name = report.logged_by.display_name if report.logged_by else "Unknown"
    volunteer = display_volunteer(report)
    dispatch = active_dispatch(report)
    return {
        "id": report.id,
        "created_at": report.created_at,
        "caller_name": report.caller_name,
        "caller_phone": report.caller_phone,
        "site_name": report.site_name,
        "lat": report.lat,
        "lon": report.lon,
        "cluster_size_bucket": report.cluster_size_bucket,
        "urgency": report.urgency,
        "notes": report.notes,
        "status": report.status,
        "status_label": STATUS_LABELS.get(report.status, report.status),
        "logged_by": logger_name,
        "assigned_volunteer": volunteer.name if volunteer else None,
        "assigned_volunteer_id": volunteer.id if volunteer else None,
        "active_dispatch_id": dispatch.id if dispatch else None,
        "active_dispatch_since": dispatch.created_at if dispatch else None,
    }


def _report_query(db: Session):
    return db.query(SwarmReport).options(
        joinedload(SwarmReport.logged_by),
        joinedload(SwarmReport.dispatches).joinedload(Dispatch.volunteer),
    )


def list_reports(
    db: Session,
    status: str | None = None,
    urgency: str | None = None,
    search: str | None = None,
    limit: int = 250,
) -> list[dict]:
    """Reports newest first, filtered by the triage controls."""
    query = _report_query(db)
    if status and status != "all":
        if status not in REPORT_STATUSES:
            raise ValidationError(f"Unknown status filter '{status}'.", field="status")
        query = query.filter(SwarmReport.status == status)
    if urgency and urgency != "all":
        if urgency not in URGENCIES:
            raise ValidationError(f"Unknown urgency filter '{urgency}'.", field="urgency")
        query = query.filter(SwarmReport.urgency == urgency)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SwarmReport.caller_name.ilike(like),
                SwarmReport.caller_phone.ilike(like),
                SwarmReport.site_name.ilike(like),
                SwarmReport.notes.ilike(like),
            )
        )
    rows = query.order_by(SwarmReport.created_at.desc(), SwarmReport.id.desc()).limit(limit).all()
    return [serialize_report(row) for row in rows]


def get_report(db: Session, report_id: int) -> SwarmReport:
    """Load one report or raise :class:`NotFoundError`."""
    report = _report_query(db).filter(SwarmReport.id == report_id).one_or_none()
    if report is None:
        raise NotFoundError("That swarm report no longer exists.")
    return report


def status_counts(db: Session) -> dict:
    """Live count per canonical status, plus the 'all' total."""
    rows = db.execute(
        select(SwarmReport.status, func.count(SwarmReport.id)).group_by(SwarmReport.status)
    ).all()
    counts = {status: 0 for status in REPORT_STATUSES}
    for status, total in rows:
        if status in counts:
            counts[status] = int(total)
    counts["all"] = sum(counts[status] for status in REPORT_STATUSES)
    return counts


def dispatchable_reports(db: Session) -> list[dict]:
    """Reports with no active dispatch that still need a collector."""
    open_reports = (
        _report_query(db)
        .filter(SwarmReport.status == "new")
        .order_by(SwarmReport.created_at.desc(), SwarmReport.id.desc())
        .all()
    )
    return [serialize_report(report) for report in open_reports if active_dispatch(report) is None]


def create_report(db: Session, payload: dict, user_id: int) -> dict:
    """Validate and persist a new swarm report with status ``new``."""
    caller_name = (payload.get("caller_name") or "").strip()
    if len(caller_name) < 2:
        raise ValidationError("Caller name is required.", field="caller_name")
    if len(caller_name) > 120:
        raise ValidationError("Caller name is too long.", field="caller_name")

    caller_phone = normalise_phone(payload.get("caller_phone") or "")

    site_name = (payload.get("site_name") or "").strip()
    site = site_catalogue.lookup(site_name)
    if site is None:
        raise ValidationError("Pick the site the swarm was reported from.", field="site_name")

    cluster_size = (payload.get("cluster_size_bucket") or "").strip()
    if cluster_size not in CLUSTER_SIZE_BUCKETS:
        raise ValidationError("Pick a cluster size bucket.", field="cluster_size_bucket")

    urgency = (payload.get("urgency") or "").strip() or "Normal"
    if urgency not in URGENCIES:
        raise ValidationError("Pick a valid urgency.", field="urgency")

    notes = (payload.get("notes") or "").strip()
    if len(notes) > 600:
        raise ValidationError("Notes are limited to 600 characters.", field="notes")

    duplicate = _recent_duplicate(db, user_id, caller_name, caller_phone, site_name, cluster_size)
    if duplicate is not None:
        return serialize_report(duplicate)

    report = SwarmReport(
        created_at=utcnow_iso(),
        logged_by_user_id=user_id,
        caller_name=caller_name,
        caller_phone=caller_phone,
        site_name=site["name"],
        lat=float(site["lat"]),
        lon=float(site["lon"]),
        cluster_size_bucket=cluster_size,
        urgency=urgency,
        notes=notes,
        status="new",
    )
    db.add(report)
    db.flush()
    db.refresh(report)
    return serialize_report(report)


def _recent_duplicate(
    db: Session, user_id: int, caller_name: str, caller_phone: str, site_name: str, cluster_size: str
) -> SwarmReport | None:
    """Guard against a double-clicked intake form creating two rows."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
    ).replace(microsecond=0).isoformat()
    return (
        _report_query(db)
        .filter(
            SwarmReport.logged_by_user_id == user_id,
            SwarmReport.caller_name == caller_name,
            SwarmReport.caller_phone == caller_phone,
            SwarmReport.site_name == site_name,
            SwarmReport.cluster_size_bucket == cluster_size,
            SwarmReport.created_at >= cutoff,
        )
        .order_by(SwarmReport.id.desc())
        .first()
    )


def logger_choices(db: Session) -> list[dict]:
    """Every coordinator that has ever logged a report (for the detail panel)."""
    users = db.query(User).order_by(User.display_name).all()
    return [{"id": u.id, "display_name": u.display_name, "username": u.username} for u in users]


def assigned_reports(db: Session) -> list[dict]:
    """Reports that currently have an active (confirmed) dispatch."""
    rows = (
        _report_query(db)
        .filter(SwarmReport.status == "assigned")
        .order_by(SwarmReport.created_at.desc(), SwarmReport.id.desc())
        .all()
    )
    return [serialize_report(row) for row in rows if active_dispatch(row) is not None]
