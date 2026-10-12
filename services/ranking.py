"""Candidate ranking: available collectors ordered by straight-line distance."""

from __future__ import annotations

from sqlalchemy.orm import Session

from db import Volunteer
from services.dispatch import serialize_dispatch
from services.geo import haversine_km
from services.reports import active_dispatch, get_report, serialize_report

NO_COVERAGE_MESSAGE = "No available collectors within their coverage radius of this site."


def rank_candidates(db: Session, report_id: int) -> dict:
    """Rank collectors for one report.

    A collector qualifies when they are available and their own coverage radius
    reaches the swarm site; the distance shown and stored is the collector's
    great-circle distance to the site, computed server-side.
    """
    report = get_report(db, report_id)
    dispatch = active_dispatch(report)
    if dispatch is not None:
        return {
            "report": serialize_report(report),
            "status": "assigned",
            "dispatch": serialize_dispatch(dispatch),
            "candidates": [],
            "available_volunteers": None,
            "message": None,
        }

    volunteers = db.query(Volunteer).filter(Volunteer.is_available.is_(True)).all()
    candidates = []
    for volunteer in volunteers:
        distance = haversine_km(volunteer.lat, volunteer.lon, report.lat, report.lon)
        if distance > volunteer.coverage_radius_km:
            continue
        candidates.append(
            {
                "volunteer_id": volunteer.id,
                "name": volunteer.name,
                "phone": volunteer.phone,
                "skills": volunteer.skills or "General swarm collection",
                "distance_km": round(distance, 2),
                "coverage_radius_km": volunteer.coverage_radius_km,
            }
        )
    candidates.sort(key=lambda row: (row["distance_km"], row["name"].lower()))

    message = None
    if not candidates:
        if not volunteers:
            message = (
                "No collectors are marked available right now - update the roster to continue."
            )
        else:
            message = NO_COVERAGE_MESSAGE

    return {
        "report": serialize_report(report),
        "status": "unassigned",
        "dispatch": None,
        "candidates": candidates,
        "available_volunteers": len(volunteers),
        "message": message,
    }
