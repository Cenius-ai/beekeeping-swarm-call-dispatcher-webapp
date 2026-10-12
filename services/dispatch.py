"""Dispatch lifecycle: confirm, decline, cancel and reassign.

At most one *active* dispatch (state ``confirmed``) may exist per report — the
service layer checks it explicitly and the partial unique index in schema.sql
enforces it as a second line of defence.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from db import Dispatch, SwarmReport, Volunteer, utcnow_iso
from services.errors import ConflictError, NotFoundError, ValidationError
from services.geo import haversine_km
from services.reports import display_volunteer, get_report, serialize_report

CLOSED_STATES = ("declined", "cancelled", "reassigned")
ACTIVE_STATE = "confirmed"


def serialize_dispatch(dispatch: Dispatch) -> dict:
    volunteer = dispatch.volunteer
    return {
        "id": dispatch.id,
        "report_id": dispatch.report_id,
        "volunteer_id": dispatch.volunteer_id,
        "volunteer_name": volunteer.name if volunteer else "Unknown collector",
        "volunteer_phone": volunteer.phone if volunteer else "",
        "state": dispatch.state,
        "distance_km": dispatch.distance_km,
        "confirmed_by_user_id": dispatch.confirmed_by_user_id,
        "created_at": dispatch.created_at,
        "closed_at": dispatch.closed_at,
        "close_reason": dispatch.close_reason,
    }


def _dispatch_query(db: Session):
    return db.query(Dispatch).options(joinedload(Dispatch.volunteer))


def load_dispatch(db: Session, dispatch_id: int) -> Dispatch:
    dispatch = _dispatch_query(db).filter(Dispatch.id == dispatch_id).one_or_none()
    if dispatch is None:
        raise NotFoundError("That dispatch no longer exists - refresh the report list.")
    return dispatch


def active_dispatch_for(db: Session, report_id: int) -> Dispatch | None:
    return (
        _dispatch_query(db)
        .filter(Dispatch.report_id == report_id, Dispatch.state == ACTIVE_STATE)
        .order_by(Dispatch.id.desc())
        .first()
    )


def _require_available(db: Session, volunteer_id: int) -> Volunteer:
    volunteer = db.get(Volunteer, volunteer_id)
    if volunteer is None:
        raise NotFoundError("That collector is no longer on the roster.")
    if not volunteer.is_available:
        raise ConflictError(
            f"{volunteer.name} is no longer marked available - pick another collector."
        )
    return volunteer


def _apply_dispatch(db: Session, report: SwarmReport, volunteer: Volunteer, user_id: int) -> Dispatch:
    """Create the single active dispatch row and move the report to assigned."""
    distance = haversine_km(volunteer.lat, volunteer.lon, report.lat, report.lon)
    if distance > volunteer.coverage_radius_km:
        raise ConflictError(
            f"{volunteer.name}'s {volunteer.coverage_radius_km:.0f} km coverage radius does not "
            f"reach {report.site_name} ({distance:.1f} km away)."
        )
    dispatch = Dispatch(
        report_id=report.id,
        volunteer_id=volunteer.id,
        state=ACTIVE_STATE,
        distance_km=round(distance, 2),
        confirmed_by_user_id=user_id,
        created_at=utcnow_iso(),
    )
    # Append through the relationship so the in-memory report stays consistent
    # for the serialization that follows (a bare db.add leaves it stale).
    report.dispatches.append(dispatch)
    db.add(dispatch)
    report.status = "assigned"
    try:
        db.flush()
    except IntegrityError as exc:  # the partial unique index fired
        db.rollback()
        raise ConflictError(
            "That report already has an active dispatch - refresh and try again."
        ) from exc
    db.refresh(dispatch)
    return dispatch


def confirm_dispatch(db: Session, report_id: int, volunteer_id: int, user_id: int) -> dict:
    """Confirm a collector for a report that has no active dispatch."""
    report = get_report(db, report_id)
    existing = active_dispatch_for(db, report_id)
    if existing is not None:
        raise ConflictError(
            f"Already assigned to {existing.volunteer.name} - use Reassign to change the collector."
        )
    if report.status not in ("new", "lost", "not_found"):
        raise ConflictError(
            f"Report #{report.id} is '{report.status.replace('_', ' ')}' and cannot be dispatched."
        )
    volunteer = _require_available(db, volunteer_id)
    dispatch = _apply_dispatch(db, report, volunteer, user_id)
    return {"dispatch": serialize_dispatch(dispatch), "report": serialize_report(report)}


def _close(db: Session, dispatch: Dispatch, state: str, reason: str) -> None:
    dispatch.state = state
    dispatch.closed_at = utcnow_iso()
    dispatch.close_reason = reason


def _revert_report(db: Session, dispatch: Dispatch) -> SwarmReport:
    report = get_report(db, dispatch.report_id)
    # Only an outcome (collected/rehomed/lost/not_found) outranks a reverted
    # dispatch; anything else goes back to the pending list.
    if report.status in ("new", "assigned"):
        report.status = "new"
    _close(db, dispatch, "declined", "Declined by collector")
    return report


def decline_dispatch(db: Session, dispatch_id: int, user_id: int, reason: str = "") -> dict:
    """Collector declined: close the dispatch and return the report to 'new'."""
    dispatch = load_dispatch(db, dispatch_id)
    if dispatch.state != ACTIVE_STATE:
        raise ConflictError(
            f"That dispatch is already '{dispatch.state}' - refresh the Dispatch tab."
        )
    report = _revert_report(db, dispatch)
    dispatch.close_reason = reason.strip() or "Declined by collector"
    db.flush()
    return {"dispatch": serialize_dispatch(dispatch), "report": serialize_report(report)}


def cancel_dispatch(db: Session, dispatch_id: int, user_id: int, reason: str = "") -> dict:
    """Coordinator cancelled: close the dispatch and revert the report to 'new'."""
    dispatch = load_dispatch(db, dispatch_id)
    if dispatch.state != ACTIVE_STATE:
        raise ConflictError(
            f"That dispatch is already '{dispatch.state}' - refresh the Dispatch tab."
        )
    report = get_report(db, dispatch.report_id)
    if report.status in ("new", "assigned"):
        report.status = "new"
    _close(db, dispatch, "cancelled", reason.strip() or "Cancelled by coordinator")
    db.flush()
    return {"dispatch": serialize_dispatch(dispatch), "report": serialize_report(report)}


def reassign_dispatch(db: Session, report_id: int, volunteer_id: int, user_id: int) -> dict:
    """Close the current active dispatch as 'reassigned' and confirm a new one."""
    report = get_report(db, report_id)
    current = active_dispatch_for(db, report_id)
    if current is None:
        raise ConflictError(
            "That report has no active dispatch to reassign - confirm a collector instead."
        )
    if current.volunteer_id == volunteer_id:
        raise ValidationError(
            f"{report.site_name} is already assigned to {current.volunteer.name}.",
            field="volunteer_id",
        )
    volunteer = _require_available(db, volunteer_id)
    _close(db, current, "reassigned", f"Reassigned to {volunteer.name}")
    db.flush()
    dispatch = _apply_dispatch(db, report, volunteer, user_id)
    return {
        "dispatch": serialize_dispatch(dispatch),
        "previous": serialize_dispatch(current),
        "report": serialize_report(report),
    }


def dispatch_history(db: Session, report_id: int) -> list[dict]:
    rows = (
        _dispatch_query(db)
        .filter(Dispatch.report_id == report_id)
        .order_by(Dispatch.id.desc())
        .all()
    )
    return [serialize_dispatch(row) for row in rows]


def assigned_volunteer_name(report: SwarmReport) -> str | None:
    volunteer = display_volunteer(report)
    return volunteer.name if volunteer else None
