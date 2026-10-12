"""Outcome recording, per-report history and the season funnel aggregates."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from data import apiaries as apiary_catalogue
from data import sites as site_catalogue
from db import (
    OUTCOME_RESULTS,
    REPORT_STATUSES,
    STATUS_LABELS,
    Dispatch,
    Outcome,
    SwarmReport,
    User,
    Volunteer,
    utcnow_iso,
)
from services.errors import NotFoundError, ValidationError
from services.reports import get_report

#: Report status each outcome result moves the report to.
RESULT_TO_STATUS = {
    "collected": "collected",
    "rehomed": "rehomed",
    "lost": "lost",
    "not_found": "not_found",
}

RESULT_LABELS = {
    "collected": "Collected",
    "rehomed": "Rehomed",
    "lost": "Lost",
    "not_found": "Not found",
}


def serialize_outcome(outcome: Outcome) -> dict:
    report = outcome.report
    dispatch = None
    for candidate in report.dispatches if report else []:
        if candidate.id == outcome.dispatch_id:
            dispatch = candidate
            break
    return {
        "id": outcome.id,
        "report_id": outcome.report_id,
        "report_site": report.site_name if report else "",
        "report_caller": report.caller_name if report else "",
        "report_status": report.status if report else "",
        "dispatch_id": outcome.dispatch_id,
        "collector": (dispatch.volunteer.name if dispatch and dispatch.volunteer else "Unassigned"),
        "recorded_by": outcome.recorded_by.display_name if outcome.recorded_by else "Unknown",
        "recorded_at": outcome.recorded_at,
        "actual_cluster_size": outcome.actual_cluster_size,
        "hive_box": outcome.hive_box,
        "rehomed_to": outcome.rehomed_to,
        "result": outcome.result,
        "result_label": RESULT_LABELS.get(outcome.result, outcome.result),
        "notes": outcome.notes,
    }


def _outcome_query(db: Session):
    return db.query(Outcome).options(
        joinedload(Outcome.report).joinedload(SwarmReport.dispatches).joinedload(Dispatch.volunteer),
        joinedload(Outcome.recorded_by),
    )


def list_outcomes(db: Session, limit: int = 120) -> list[dict]:
    """Newest outcomes first, with the report, collector and recorder attached."""
    rows = (
        _outcome_query(db)
        .order_by(Outcome.recorded_at.desc(), Outcome.id.desc())
        .limit(limit)
        .all()
    )
    return [serialize_outcome(row) for row in rows]


def report_outcomes(db: Session, report_id: int) -> list[dict]:
    rows = (
        _outcome_query(db)
        .filter(Outcome.report_id == report_id)
        .order_by(Outcome.recorded_at.desc(), Outcome.id.desc())
        .all()
    )
    return [serialize_outcome(row) for row in rows]


def _validate_result(raw: str) -> str:
    result = (raw or "").strip()
    if result not in OUTCOME_RESULTS:
        raise ValidationError("Choose an outcome result.", field="result")
    return result


def _validate_destination(result: str, raw: str) -> str:
    destination = (raw or "").strip()
    if result == "rehomed":
        apiary = apiary_catalogue.lookup(destination)
        if apiary is None:
            raise ValidationError(
                "Pick the apiary the swarm was rehomed to.", field="rehomed_to"
            )
        return apiary["name"]
    return destination if apiary_catalogue.lookup(destination) else ""


def _validate_cluster_size(raw) -> int | None:
    if raw in (None, "", "null"):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError("Actual cluster size must be a whole number.", field="actual_cluster_size") from None
    if value < 0 or value > 200000:
        raise ValidationError(
            "Actual cluster size must be between 0 and 200,000 bees.",
            field="actual_cluster_size",
        )
    return value


def record_outcome(db: Session, report_id: int, payload: dict, user_id: int) -> dict:
    """Persist an outcome and move the report to the matching status."""
    report = get_report(db, report_id)
    result = _validate_result(payload.get("result"))
    destination = _validate_destination(result, payload.get("rehomed_to"))
    cluster_size = _validate_cluster_size(payload.get("actual_cluster_size"))

    hive_box = (payload.get("hive_box") or "").strip()
    if len(hive_box) > 80:
        raise ValidationError("Hive or box reference is limited to 80 characters.", field="hive_box")

    notes = (payload.get("notes") or "").strip()
    if len(notes) > 600:
        raise ValidationError("Notes are limited to 600 characters.", field="notes")

    recorded_at = (payload.get("recorded_at") or "").strip() or utcnow_iso()
    try:
        datetime.fromisoformat(recorded_at)
    except ValueError:
        raise ValidationError("Collection date is not a valid date.", field="collected_on") from None

    active = None
    for candidate in reversed(report.dispatches):
        if candidate.state == "confirmed":
            active = candidate
            break

    outcome = Outcome(
        report_id=report.id,
        dispatch_id=active.id if active else None,
        recorded_by_user_id=user_id,
        recorded_at=recorded_at,
        actual_cluster_size=cluster_size,
        hive_box=hive_box,
        rehomed_to=destination,
        result=result,
        notes=notes,
    )
    db.add(outcome)

    if active is not None:
        # The collector carried the call out; the dispatch is done but the
        # controller stays visible in the 'Assigned volunteer' column.
        active.state = "completed"
        active.closed_at = utcnow_iso()
        active.close_reason = f"Outcome recorded: {RESULT_LABELS[result]}"

    report.status = RESULT_TO_STATUS[result]
    db.flush()
    db.refresh(outcome)
    return {"outcome": serialize_outcome(outcome), "report_status": report.status}


def funnel(db: Session) -> dict:
    """Pipeline counts plus the two separate terminal buckets."""
    counts = {status: 0 for status in REPORT_STATUSES}
    rows = db.execute(
        select(SwarmReport.status, func.count(SwarmReport.id)).group_by(SwarmReport.status)
    ).all()
    for status, total in rows:
        if status in counts:
            counts[status] = int(total)
    counts["all"] = sum(counts[status] for status in REPORT_STATUSES)

    stages = ["new", "assigned", "collected", "rehomed"]
    terminal = ["lost", "not_found"]
    outcome_rows = db.execute(select(Outcome.result, func.count(Outcome.id)).group_by(Outcome.result)).all()
    outcome_counts = {result: 0 for result in OUTCOME_RESULTS}
    for result, total in outcome_rows:
        if result in outcome_counts:
            outcome_counts[result] = int(total)

    return {
        "counts": counts,
        "labels": STATUS_LABELS,
        "stages": [{"status": s, "label": STATUS_LABELS[s], "count": counts[s]} for s in stages],
        "terminal": [{"status": s, "label": STATUS_LABELS[s], "count": counts[s]} for s in terminal],
        "outcome_counts": outcome_counts,
        "outcomes_total": sum(outcome_counts.values()),
        "reports_total": counts["all"],
    }
