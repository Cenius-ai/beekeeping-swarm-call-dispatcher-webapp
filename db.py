"""SQLite schema, SQLAlchemy models and session plumbing.

The database is a relative SQLite file (``./data.db``) created and migrated on
the normal boot path, so a fresh clone renders real data with no manual step.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_URL = "sqlite:///./data.db"
DATABASE_URL = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL

SCHEMA_PATH = BASE_DIR / "schema.sql"

#: Canonical swarm-report lifecycle. 'lost' and 'not_found' are both terminal
#: but deliberately distinct everywhere the status is rendered.
REPORT_STATUSES = ("new", "assigned", "collected", "rehomed", "lost", "not_found")

STATUS_LABELS = {
    "new": "New",
    "assigned": "Assigned",
    "collected": "Collected",
    "rehomed": "Rehomed",
    "lost": "Lost",
    "not_found": "Not found",
}

#: Marker / chip / funnel colours. Hex only — chart libraries cannot parse CSS
#: colour functions such as oklch().
STATUS_COLORS = {
    "new": "#f0b429",
    "assigned": "#9884f3",
    "collected": "#38bdf8",
    "rehomed": "#34d399",
    "lost": "#c9302d",
    "not_found": "#9d9da6",
}

DISPATCH_STATES = ("confirmed", "declined", "cancelled", "reassigned", "completed")

OUTCOME_RESULTS = ("collected", "rehomed", "lost", "not_found")

CLUSTER_SIZE_BUCKETS = (
    "Small (fist-sized, <2,000 bees)",
    "Medium (football-sized, 2,000-8,000 bees)",
    "Large (basketball-sized, 8,000-20,000 bees)",
    "Very large (more than 20,000 bees)",
)

URGENCIES = ("Low", "Normal", "High", "Emergency")


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string (the storage format)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    reports: Mapped[list["SwarmReport"]] = relationship(back_populates="logged_by")


class Volunteer(Base):
    __tablename__ = "volunteer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    coverage_radius_km: Mapped[float] = mapped_column(Float, nullable=False)
    skills: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    dispatches: Mapped[list["Dispatch"]] = relationship(back_populates="volunteer")


class SwarmReport(Base):
    __tablename__ = "swarm_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    logged_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    caller_name: Mapped[str] = mapped_column(String, nullable=False)
    caller_phone: Mapped[str] = mapped_column(String, nullable=False)
    site_name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    cluster_size_bucket: Mapped[str] = mapped_column(String, nullable=False)
    urgency: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")

    logged_by: Mapped[User] = relationship(back_populates="reports")
    dispatches: Mapped[list["Dispatch"]] = relationship(
        back_populates="report", order_by="Dispatch.id"
    )
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="report")

    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'assigned', 'collected', 'rehomed', 'lost', 'not_found')",
            name="ck_report_status",
        ),
    )

    def active_dispatch(self) -> "Dispatch | None":
        for dispatch in self.dispatches:
            if dispatch.state == "confirmed":
                return dispatch
        return None


class Dispatch(Base):
    __tablename__ = "dispatch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("swarm_report.id"), nullable=False)
    volunteer_id: Mapped[int] = mapped_column(ForeignKey("volunteer.id"), nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    closed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    report: Mapped[SwarmReport] = relationship(back_populates="dispatches")
    volunteer: Mapped[Volunteer] = relationship(back_populates="dispatches")

    __table_args__ = (
        CheckConstraint(
            "state IN ('confirmed', 'declined', 'cancelled', 'reassigned', 'completed')",
            name="ck_dispatch_state",
        ),
        # Mirrors schema.sql: at most one active dispatch per report.
        Index(
            "ux_dispatch_active_per_report",
            "report_id",
            unique=True,
            sqlite_where=text("state = 'confirmed'"),
        ),
    )


class Outcome(Base):
    __tablename__ = "outcome"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("swarm_report.id"), nullable=False)
    dispatch_id: Mapped[int | None] = mapped_column(ForeignKey("dispatch.id"), nullable=True)
    recorded_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    recorded_at: Mapped[str] = mapped_column(String, nullable=False)
    actual_cluster_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hive_box: Mapped[str] = mapped_column(String, nullable=False, default="")
    rehomed_to: Mapped[str] = mapped_column(String, nullable=False, default="")
    result: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    report: Mapped[SwarmReport] = relationship(back_populates="outcomes")
    dispatch: Mapped["Dispatch | None"] = relationship()
    recorded_by: Mapped[User] = relationship()

    __table_args__ = (
        CheckConstraint(
            "result IN ('collected', 'rehomed', 'lost', 'not_found')", name="ck_outcome_result"
        ),
    )


def _build_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if is_sqlite:
        # Requests are served from Flask/Dash threads; SQLite objects must be
        # shareable across them.
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(target_engine=None) -> None:
    """Create every table and index from ``schema.sql`` (idempotent)."""
    active = target_engine or engine
    raw = active.raw_connection()
    try:
        script = SCHEMA_PATH.read_text(encoding="utf-8")
        raw.executescript(script)
        raw.commit()
    finally:
        raw.close()


@contextmanager
def session_scope():
    """Transactional unit of work: commit on success, roll back on failure."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """A bare session for read-only helpers; callers close it."""
    return SessionLocal()
