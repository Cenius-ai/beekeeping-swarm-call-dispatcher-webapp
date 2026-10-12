"""Idempotent demo seed.

Running this twice changes nothing. It is safe on the boot path (app.py calls
:func:`seed_all` when the database is empty) and as a standalone command:

    python3 seed.py

The script never starts an HTTP server.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from data import apiaries as apiary_catalogue
from data import sites as site_catalogue
from db import (
    CLUSTER_SIZE_BUCKETS,
    URGENCIES,
    Dispatch,
    Outcome,
    SwarmReport,
    User,
    Volunteer,
    engine,
    init_db,
    session_scope,
    utcnow_iso,
)
from services.geo import haversine_km
from services.reports import display_volunteer

RNG_SEED = 20240614

DEMO_USERNAME = "cenius"
DEMO_EMAIL = "cenius@cenius.ai"
DEMO_PASSWORD = "cenius"
DEMO_DISPLAY_NAME = "Dana Whitfield"

VOLUNTEERS = [
    # name, phone, home site, coverage radius km, skills, available
    ("Priya Raman", "07700 900118", "Clifton Down Allotments", 34.0, "Cut-outs, ladders, bee-vac", True),
    ("Ravi Deshmukh", "07700 900231", "Horfield Common Orchard", 22.0, "Tree swarms, ladders", True),
    ("Nia Bennett", "07700 900347", "St Werburghs City Farm", 18.0, "Nucleus hives, gentle handling", True),
    ("Marcus Oyelaran", "07700 900455", "Victoria Park Primary", 35.0, "Cut-outs, building access", True),
    ("Sofia Lindqvist", "07700 900562", "Eastville Park Lodge", 16.0, "Swarm lures, observation hives", True),
    ("Tomasz Wójcik", "07700 900673", "Blaise Castle Museum Lawn", 24.0, "High work, rope access", True),
    ("Grace Achebe", "07700 900781", "Fishponds Hive Yard", 30.0, "Bee-vac, chimney swarms", True),
    ("Duncan Fraser", "07700 900894", "Oldbury Court Walled Garden", 14.0, "Nucleus hives, beginners mentoring", True),
    ("Yasmin Haddad", "07700 900902", "Keynsham Memorial Park", 20.0, "Orchard swarms, transport", True),
    ("Callum Reid", "07700 900933", "Portishead Marina Gardens", 18.0, "Coastal swarms, kayak access", True),
    ("Elinor Pryce", "07700 900944", "Whitchurch Garden Centre", 12.0, "Nucleus hives, queen catching", False),
    ("Ben Nakamura", "07700 900955", "Snuff Mills Riverside Cafe", 26.0, "Bee-vac, riverside access", False),
]

VOLUNTEER_LOCATIONS = {row[2]: row for row in VOLUNTEERS}

# Reports are spread over the last ~90 days. Terminal reports are older than
# pending ones so the season reads like a real pipeline.
STATUS_PLAN = [
    ("rehomed", 9),
    ("collected", 4),
    ("lost", 5),
    ("not_found", 7),
    ("assigned", 15),
    ("new", 20),
]

CALLER_GIVEN = [
    "Alison", "Bilal", "Cheryl", "Deepa", "Ewan", "Fiona", "Gethin", "Hana",
    "Ivan", "Joanne", "Kwame", "Lena", "Marek", "Nadia", "Oliver", "Priti",
    "Quentin", "Rhiannon", "Samir", "Tessa", "Umar", "Vivienne", "Wesley",
    "Ximena", "Yusuf", "Zara", "Bridget", "Callum", "Delia", "Ethan",
]

CALLER_SURNAMES = [
    "Ashworth", "Bhardwaj", "Cornish", "Duarte", "Ellery", "Fairbrother",
    "Grieve", "Hartley", "Iles", "Jarvis", "Kirby", "Lindley", "Moorcroft",
    "Nkemelu", "Oatley", "Prowse", "Quinnell", "Radcliffe", "Steadman",
    "Trelawney", "Underhill", "Vickery", "Wainwright", "Yeates",
]

NOTES = [
    "Swarm on the shed gable about two metres up; easy ladder access from the path.",
    "Caller is anxious about children playing nearby - asked for a same-day visit.",
    "Cluster hanging from a cherry branch over the car park entrance.",
    "Bees went into a compost bin lid last week; caller resealed it for now.",
    "Chimney swarm, visible from the street, no smoke used yet.",
    "Settled under a wheelbarrow in the polytunnel; caller has closed the door.",
    "On the fence post by the allotment gate, calm and not defensive.",
    "Caller reports a large cluster entering a soffit vent.",
    "Swarm on a picnic bench; site staff have taped off the area.",
    "Two clusters on the same hedge, roughly a metre apart.",
    "Old hive box on the plot has been reoccupied.",
    "In a bird box on the back wall of the pavilion.",
]

HIVE_BOXES = [
    "Nuc box 3 (5-frame)", "Nuc box 7 (5-frame)", "BS National brood box 2",
    "BS National brood box 5", "Poly nuc 4", "Warré box B", "Skep (transferred)",
    "Cardboard travel box 2",
]


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0, tzinfo=timezone.utc).isoformat()


def ensure_demo_user(db: Session) -> User:
    """Create the seeded coordinator if it is missing (hashed like any user)."""
    from auth import hash_password

    user = db.execute(select(User).where(User.username == DEMO_USERNAME)).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        username=DEMO_USERNAME,
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        display_name=DEMO_DISPLAY_NAME,
        created_at=utcnow_iso(),
    )
    db.add(user)
    db.flush()
    return user


def ensure_volunteers(db: Session, rng: random.Random) -> list[Volunteer]:
    existing = db.execute(select(func.count(Volunteer.id))).scalar_one()
    if existing:
        return db.execute(select(Volunteer).order_by(Volunteer.id)).scalars().all()

    volunteers = []
    for index, (name, phone, site_name, radius, skills, available) in enumerate(VOLUNTEERS):
        home = site_catalogue.lookup(site_name)
        jitter = rng.uniform(-0.004, 0.004)
        volunteer = Volunteer(
            name=name,
            phone=phone,
            lat=home["lat"] + jitter,
            lon=home["lon"] + jitter,
            coverage_radius_km=radius,
            skills=skills,
            is_available=available,
            updated_at=_iso(datetime.now(timezone.utc) - timedelta(hours=6 + index * 11)),
        )
        volunteers.append(volunteer)
        db.add(volunteer)
    db.flush()
    return volunteers


def _covering_volunteers(volunteers: list[Volunteer], site: dict) -> list[tuple[float, Volunteer]]:
    reaching = []
    for volunteer in volunteers:
        distance = haversine_km(volunteer.lat, volunteer.lon, site["lat"], site["lon"])
        if distance <= volunteer.coverage_radius_km:
            reaching.append((distance, volunteer))
    reaching.sort(key=lambda pair: pair[0])
    return reaching


def _allocate_statuses() -> list[str]:
    plan = []
    for status, count in STATUS_PLAN:
        plan.extend([status] * count)
    return plan


def ensure_reports(db: Session, user: User, volunteers: list[Volunteer], rng: random.Random) -> int:
    existing = db.execute(select(func.count(SwarmReport.id))).scalar_one()
    if existing:
        return 0

    sites = list(site_catalogue.SITES)
    statuses = _allocate_statuses()
    now = datetime.now(timezone.utc)

    # Terminal reports happened earlier in the season; pending ones are recent.
    terminal_days = (8, 92)
    assigned_days = (1, 21)
    new_days = (0, 12)

    outcomes_created = 0
    for index, status in enumerate(statuses):
        site = sites[index % len(sites)]
        if status in ("rehomed", "collected", "lost", "not_found"):
            days_ago = rng.uniform(*terminal_days)
        elif status == "assigned":
            days_ago = rng.uniform(*assigned_days)
        else:
            days_ago = rng.uniform(*new_days)

        created = now - timedelta(days=days_ago, hours=rng.uniform(0, 20))
        caller_name = f"{rng.choice(CALLER_GIVEN)} {rng.choice(CALLER_SURNAMES)}"
        report = SwarmReport(
            created_at=_iso(created),
            logged_by_user_id=user.id,
            caller_name=caller_name,
            caller_phone=f"0770{rng.randint(100000, 999999)}",
            site_name=site["name"],
            lat=site["lat"],
            lon=site["lon"],
            cluster_size_bucket=rng.choice(CLUSTER_SIZE_BUCKETS),
            urgency=rng.choice(URGENCIES),
            notes=rng.choice(NOTES),
            status="new",
        )
        db.add(report)
        db.flush()

        reaching = _covering_volunteers(volunteers, site)
        if not reaching:
            # Every site has cover by construction; guard anyway.
            report.status = "not_found"
            continue

        distance, volunteer = reaching[0]
        dispatch_at = created + timedelta(minutes=rng.randint(12, 95))

        if status in ("rehomed", "collected", "lost", "not_found"):
            _build_history(db, report, reaching, dispatch_at, rng, include_reassign=False)
            outcomes_created += _record_seed_outcome(db, report, user, status, created, rng)
        elif status == "assigned":
            if index % 5 == 0:
                _build_history(db, report, reaching, dispatch_at, rng, include_reassign=True)
            else:
                _confirm(db, report, volunteer, distance, user, dispatch_at)
        else:  # new
            if index % 7 == 0:
                _build_history(db, report, reaching, dispatch_at, rng, include_reassign=False, close_only=True)

    db.flush()
    return outcomes_created


def _confirm(
    db: Session,
    report: SwarmReport,
    volunteer: Volunteer,
    distance: float,
    user: User,
    at: datetime,
) -> Dispatch:
    dispatch = Dispatch(
        report_id=report.id,
        volunteer_id=volunteer.id,
        state="confirmed",
        distance_km=round(distance, 2),
        confirmed_by_user_id=user.id,
        created_at=_iso(at),
    )
    db.add(dispatch)
    report.status = "assigned"
    db.flush()
    return dispatch


def _build_history(
    db: Session,
    report: SwarmReport,
    reaching: list[tuple[float, Volunteer]],
    at: datetime,
    rng: random.Random,
    include_reassign: bool,
    close_only: bool = False,
) -> None:
    """Give a report a believable dispatch history.

    ``close_only`` leaves the report pending after a declined dispatch, which is
    exactly how a cancelled or declined call returns to the intake list.
    """
    distance, volunteer = reaching[0]
    alternatives = [pair for pair in reaching if pair[1].id != volunteer.id]

    if include_reassign and alternatives:
        first_distance, first = alternatives[0]
        stale = _confirm(db, report, first, first_distance, _seed_user(db), at)
        stale.state = "reassigned"
        stale.closed_at = _iso(at + timedelta(hours=2))
        stale.close_reason = f"Reassigned to {volunteer.name}"
        db.flush()
        _confirm(db, report, volunteer, distance, _seed_user(db), at + timedelta(hours=2, minutes=15))
        return

    closed = _confirm(db, report, volunteer, distance, _seed_user(db), at)
    if close_only:
        closed.state = "declined" if rng.random() < 0.5 else "cancelled"
        closed.closed_at = _iso(at + timedelta(minutes=rng.randint(20, 200)))
        closed.close_reason = (
            "Declined by collector" if closed.state == "declined" else "Cancelled by coordinator"
        )
        report.status = "new"
    else:
        closed.state = "completed"
        closed.closed_at = _iso(at + timedelta(hours=rng.randint(2, 30)))
        closed.close_reason = "Call attended"
    db.flush()


def _seed_user(db: Session) -> User:
    return db.execute(select(User).where(User.username == DEMO_USERNAME)).scalar_one()


def _record_seed_outcome(
    db: Session,
    report: SwarmReport,
    user: User,
    status: str,
    created: datetime,
    rng: random.Random,
) -> int:
    """One outcome row per terminal report, plus a 'collected' step for rehomes."""
    dispatch = next((d for d in report.dispatches if d.state == "completed"), None)
    recorded_at = created + timedelta(hours=rng.randint(3, 40))
    created_count = 0

    if status == "rehomed" and rng.random() < 0.55:
        db.add(
            Outcome(
                report_id=report.id,
                dispatch_id=dispatch.id if dispatch else None,
                recorded_by_user_id=user.id,
                recorded_at=_iso(recorded_at),
                actual_cluster_size=rng.randint(1800, 22000),
                hive_box=rng.choice(HIVE_BOXES),
                rehomed_to="",
                result="collected",
                notes="Removed to a travel box; queen confirmed present.",
            )
        )
        created_count += 1
        recorded_at = recorded_at + timedelta(days=rng.randint(0, 2), hours=rng.randint(1, 9))

    result = status
    if status == "rehomed":
        destination = rng.choice(apiary_catalogue.apiary_names()[:-1])
        notes = "Hived at the out-apiary and left to settle with a feeder on."
    elif status == "collected":
        destination = ""
        notes = "Swarms hived into a nucleus box, awaiting a permanent site."
    elif status == "lost":
        destination = ""
        notes = "Bees had already absconded by the time the collector arrived."
    else:
        destination = ""
        notes = "No swarm found at the reported location; caller advised to call back if it returns."

    db.add(
        Outcome(
            report_id=report.id,
            dispatch_id=dispatch.id if dispatch else None,
            recorded_by_user_id=user.id,
            recorded_at=_iso(recorded_at),
            actual_cluster_size=rng.randint(1500, 24000) if status != "not_found" else None,
            hive_box=rng.choice(HIVE_BOXES) if status in ("rehomed", "collected") else "",
            rehomed_to=destination,
            result=result,
            notes=notes,
        )
    )
    created_count += 1
    report.status = status
    db.flush()
    return created_count


def seed_all(verbose: bool = True) -> dict:
    """Create the schema and load demo data if it is missing. Idempotent."""
    init_db()
    rng = random.Random(RNG_SEED)
    with session_scope() as db:
        user = ensure_demo_user(db)
        volunteers = ensure_volunteers(db, rng)
        outcomes_created = ensure_reports(db, user, volunteers, rng)
        counts = {
            "users": db.execute(select(func.count(User.id))).scalar_one(),
            "volunteers": db.execute(select(func.count(Volunteer.id))).scalar_one(),
            "reports": db.execute(select(func.count(SwarmReport.id))).scalar_one(),
            "dispatches": db.execute(select(func.count(Dispatch.id))).scalar_one(),
            "outcomes": db.execute(select(func.count(Outcome.id))).scalar_one(),
        }
    if verbose:
        print("Seed summary:", ", ".join(f"{k}={v}" for k, v in counts.items()))
        if outcomes_created:
            print(f"  (inserted outcomes during this run: {outcomes_created})")
    return counts


def main() -> None:
    counts = seed_all()
    if counts["reports"]:
        # Never echo credentials: the coordinator hint lives on the sign-in card
        # and in README.md -> "## Demo accounts".
        print("Demo data ready. See README.md -> '## Demo accounts' for the sign-in.")


if __name__ == "__main__":
    main()
