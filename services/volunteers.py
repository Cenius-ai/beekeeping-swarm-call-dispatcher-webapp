"""Volunteer roster: listing, availability toggling and additions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from data.sites import SERVICE_CENTRE, SERVICE_RADIUS_KM
from db import Volunteer, utcnow_iso
from services.errors import NotFoundError, ValidationError
from services.geo import haversine_km
from services.reports import normalise_phone

MIN_RADIUS_KM = 1.0
MAX_RADIUS_KM = 50.0


def serialize_volunteer(volunteer: Volunteer) -> dict:
    return {
        "id": volunteer.id,
        "name": volunteer.name,
        "phone": volunteer.phone,
        "lat": volunteer.lat,
        "lon": volunteer.lon,
        "coverage_radius_km": volunteer.coverage_radius_km,
        "skills": volunteer.skills,
        "is_available": bool(volunteer.is_available),
        "updated_at": volunteer.updated_at,
    }


def list_volunteers(db: Session, availability: str = "all") -> list[dict]:
    """Roster sorted by name; optionally filtered by availability."""
    query = db.query(Volunteer)
    if availability == "available":
        query = query.filter(Volunteer.is_available.is_(True))
    elif availability == "unavailable":
        query = query.filter(Volunteer.is_available.is_(False))
    rows = query.order_by(Volunteer.name.asc()).all()
    return [serialize_volunteer(row) for row in rows]


def get_volunteer(db: Session, volunteer_id: int) -> Volunteer:
    volunteer = db.get(Volunteer, volunteer_id)
    if volunteer is None:
        raise NotFoundError("That collector is no longer on the roster.")
    return volunteer


def _validate_name(raw: str) -> str:
    name = (raw or "").strip()
    if len(name) < 2:
        raise ValidationError("Collector name is required.", field="name")
    if len(name) > 120:
        raise ValidationError("Collector name is too long.", field="name")
    return name


def _validate_coordinates(lat_raw, lon_raw) -> tuple[float, float]:
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except (TypeError, ValueError):
        raise ValidationError("Latitude and longitude must be numbers.", field="lat") from None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValidationError("Latitude or longitude is out of range.", field="lat")
    distance = haversine_km(lat, lon, SERVICE_CENTRE["lat"], SERVICE_CENTRE["lon"])
    if distance > SERVICE_RADIUS_KM:
        raise ValidationError(
            f"Home location must be inside the {SERVICE_RADIUS_KM:.0f} km service area.",
            field="lat",
        )
    return lat, lon


def _validate_radius(raw) -> float:
    try:
        radius = float(raw)
    except (TypeError, ValueError):
        raise ValidationError("Coverage radius must be a number of kilometres.", field="coverage_radius_km") from None
    if radius < MIN_RADIUS_KM or radius > MAX_RADIUS_KM:
        raise ValidationError(
            f"Coverage radius must be between {MIN_RADIUS_KM:.0f} and {MAX_RADIUS_KM:.0f} km.",
            field="coverage_radius_km",
        )
    return radius


def _validate_skills(raw: str) -> str:
    skills = (raw or "").strip()
    if len(skills) > 160:
        raise ValidationError("Skills are limited to 160 characters.", field="skills")
    return skills


def create_volunteer(db: Session, payload: dict, default_available: bool = True) -> dict:
    name = _validate_name(payload.get("name"))
    phone = normalise_phone(payload.get("phone") or "")
    lat, lon = _validate_coordinates(payload.get("lat"), payload.get("lon"))
    radius = _validate_radius(payload.get("coverage_radius_km"))
    skills = _validate_skills(payload.get("skills"))

    available_raw = payload.get("is_available", default_available)
    is_available = bool(available_raw) if not isinstance(available_raw, str) else available_raw.lower() not in ("false", "0", "no", "")

    volunteer = Volunteer(
        name=name,
        phone=phone,
        lat=lat,
        lon=lon,
        coverage_radius_km=radius,
        skills=skills,
        is_available=is_available,
        updated_at=utcnow_iso(),
    )
    db.add(volunteer)
    db.flush()
    db.refresh(volunteer)
    return serialize_volunteer(volunteer)


def update_volunteer(db: Session, volunteer_id: int, payload: dict) -> dict:
    """Patch availability and/or coverage details for one collector."""
    volunteer = get_volunteer(db, volunteer_id)
    changed = False

    if "is_available" in payload:
        value = payload["is_available"]
        if isinstance(value, str):
            value = value.strip().lower() not in ("false", "0", "no", "")
        volunteer.is_available = bool(value)
        changed = True
    if "coverage_radius_km" in payload:
        volunteer.coverage_radius_km = _validate_radius(payload["coverage_radius_km"])
        changed = True
    if "skills" in payload:
        volunteer.skills = _validate_skills(payload["skills"])
        changed = True
    if "phone" in payload:
        volunteer.phone = normalise_phone(payload["phone"])
        changed = True
    if "lat" in payload or "lon" in payload:
        volunteer.lat, volunteer.lon = _validate_coordinates(
            payload.get("lat", volunteer.lat), payload.get("lon", volunteer.lon)
        )
        changed = True

    if not changed:
        raise ValidationError("Nothing to update.", field="is_available")

    volunteer.updated_at = utcnow_iso()
    db.flush()
    db.refresh(volunteer)
    return serialize_volunteer(volunteer)
