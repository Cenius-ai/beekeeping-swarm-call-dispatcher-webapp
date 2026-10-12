"""Service-layer tests: the invariants the UI depends on, asserted directly."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db import Dispatch, Outcome, SwarmReport, Volunteer, session_scope, utcnow_iso
from services import dispatch as dispatch_service
from services import outcomes as outcome_service
from services import ranking as ranking_service
from services import reports as report_service
from services import volunteers as volunteer_service
from services.errors import ConflictError, NotFoundError, ValidationError
from services.geo import haversine_km


def demo_user_id() -> int:
    from db import User

    with session_scope() as db:
        return db.execute(select(User.id).where(User.username == "cenius")).scalar_one()


@pytest.fixture()
def fresh_report(app_module, request):
    """A brand-new, undispatched swarm report, unique per test."""
    fingerprint = abs(hash(request.node.name)) % 10_000_000
    with session_scope() as db:
        created = report_service.create_report(
            db,
            {
                "caller_name": "Service Layer",
                "caller_phone": f"0770{fingerprint:07d}"[-11:],
                "site_name": "Redland Green Pavilion",
                "cluster_size_bucket": "Large (basketball-sized, 8,000-20,000 bees)",
                "urgency": "Normal",
                "notes": "Service test fixture.",
            },
            demo_user_id(),
        )
    return created["id"]


def test_haversine_is_sane():
    # Bristol city centre to Bath, roughly 20 km in a straight line.
    distance = haversine_km(51.4545, -2.5879, 51.3811, -2.3590)
    assert 17 < distance < 19
    assert haversine_km(51.4, -2.6, 51.4, -2.6) == 0


def test_report_validation_rejects_a_short_phone(app_module):
    with session_scope() as db:
        with pytest.raises(ValidationError) as excinfo:
            report_service.create_report(
                db,
                {
                    "caller_name": "Short Phone",
                    "caller_phone": "123",
                    "site_name": "Redland Green Pavilion",
                    "cluster_size_bucket": "Small (fist-sized, <2,000 bees)",
                },
                demo_user_id(),
            )
    assert excinfo.value.field == "caller_phone"


def test_report_validation_rejects_an_unknown_site(app_module):
    with session_scope() as db:
        with pytest.raises(ValidationError) as excinfo:
            report_service.create_report(
                db,
                {
                    "caller_name": "Unknown Site",
                    "caller_phone": "07700 900333",
                    "site_name": "Somewhere Else",
                    "cluster_size_bucket": "Small (fist-sized, <2,000 bees)",
                },
                demo_user_id(),
            )
    assert excinfo.value.field == "site_name"


def test_duplicate_submit_guard_creates_one_row(app_module):
    payload = {
        "caller_name": "Double Click",
        "caller_phone": "07700 900444",
        "site_name": "Horfield Common Orchard",
        "cluster_size_bucket": "Medium (football-sized, 2,000-8,000 bees)",
        "urgency": "Normal",
    }
    with session_scope() as db:
        before = db.execute(select(func.count(SwarmReport.id))).scalar_one()
        first = report_service.create_report(db, payload, demo_user_id())
        second = report_service.create_report(db, payload, demo_user_id())
        after = db.execute(select(func.count(SwarmReport.id))).scalar_one()
    assert first["id"] == second["id"]
    assert after == before + 1


def test_ranking_only_offers_available_collectors_in_range(app_module, fresh_report):
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        report = ranked["report"]
        for candidate in ranked["candidates"]:
            volunteer = db.get(Volunteer, candidate["volunteer_id"])
            assert volunteer.is_available
            distance = haversine_km(volunteer.lat, volunteer.lon, report["lat"], report["lon"])
            assert distance <= volunteer.coverage_radius_km + 0.01

        available_ids = {c["volunteer_id"] for c in ranked["candidates"]}
        for volunteer in db.query(Volunteer).filter(Volunteer.is_available.is_(False)).all():
            assert volunteer.id not in available_ids


def test_ranking_reports_when_nothing_reaches_the_site(app_module, fresh_report):
    with session_scope() as db:
        scoped = ranking_service.rank_candidates(db, fresh_report)
        assert "message" in scoped
        db.query(Volunteer).update({Volunteer.is_available: False})
        db.flush()
        empty = ranking_service.rank_candidates(db, fresh_report)
        assert empty["candidates"] == []
        assert "available" in empty["message"]
        db.rollback()


def test_confirm_dispatch_sets_the_single_active_dispatch(app_module, fresh_report):
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        candidate = ranked["candidates"][0]
        result = dispatch_service.confirm_dispatch(
            db, fresh_report, candidate["volunteer_id"], demo_user_id()
        )
        assert result["dispatch"]["state"] == "confirmed"
        assert result["report"]["status"] == "assigned"
        assert result["report"]["assigned_volunteer"] == candidate["name"]

        with pytest.raises(ConflictError):
            dispatch_service.confirm_dispatch(
                db, fresh_report, candidate["volunteer_id"], demo_user_id()
            )


def test_partial_unique_index_blocks_a_second_active_dispatch(app_module, fresh_report):
    """The database itself refuses two confirmed dispatches for one report."""
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        volunteer_id = ranked["candidates"][0]["volunteer_id"]
        dispatch_service.confirm_dispatch(db, fresh_report, volunteer_id, demo_user_id())
        db.add(
            Dispatch(
                report_id=fresh_report,
                volunteer_id=volunteer_id,
                state="confirmed",
                distance_km=1.0,
                confirmed_by_user_id=demo_user_id(),
                created_at=utcnow_iso(),
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_decline_returns_the_report_to_new(app_module, fresh_report):
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        confirmed = dispatch_service.confirm_dispatch(
            db, fresh_report, ranked["candidates"][0]["volunteer_id"], demo_user_id()
        )
        declined = dispatch_service.decline_dispatch(
            db, confirmed["dispatch"]["id"], demo_user_id()
        )
        assert declined["dispatch"]["state"] == "declined"
        assert declined["report"]["status"] == "new"
        assert declined["report"]["assigned_volunteer"] is None
        # a stale decline is refused rather than silently applied
        with pytest.raises(ConflictError):
            dispatch_service.decline_dispatch(db, confirmed["dispatch"]["id"], demo_user_id())


def test_cancel_is_distinct_from_decline(app_module, fresh_report):
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        confirmed = dispatch_service.confirm_dispatch(
            db, fresh_report, ranked["candidates"][0]["volunteer_id"], demo_user_id()
        )
        cancelled = dispatch_service.cancel_dispatch(db, confirmed["dispatch"]["id"], demo_user_id())
        assert cancelled["dispatch"]["state"] == "cancelled"
        assert cancelled["report"]["status"] == "new"


def test_reassign_keeps_the_old_row_in_history(app_module, fresh_report):
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        first, second = ranked["candidates"][0], ranked["candidates"][-1]
        dispatch_service.confirm_dispatch(db, fresh_report, first["volunteer_id"], demo_user_id())
        result = dispatch_service.reassign_dispatch(
            db, fresh_report, second["volunteer_id"], demo_user_id()
        )
        assert result["previous"]["state"] == "reassigned"
        assert result["dispatch"]["state"] == "confirmed"
        assert result["report"]["assigned_volunteer"] == second["name"]

        history = dispatch_service.dispatch_history(db, fresh_report)
        states = sorted(row["state"] for row in history)
        assert states == ["confirmed", "reassigned"]


def test_outcome_moves_the_report_and_closes_the_dispatch(app_module, fresh_report):
    with session_scope() as db:
        ranked = ranking_service.rank_candidates(db, fresh_report)
        confirmed = dispatch_service.confirm_dispatch(
            db, fresh_report, ranked["candidates"][0]["volunteer_id"], demo_user_id()
        )
        recorded = outcome_service.record_outcome(
            db,
            fresh_report,
            {
                "result": "rehomed",
                "rehomed_to": "Avon Valley Apiary",
                "actual_cluster_size": "7200",
                "hive_box": "Nuc box 3 (5-frame)",
                "notes": "Hived and fed.",
            },
            demo_user_id(),
        )
        assert recorded["report_status"] == "rehomed"
        assert recorded["outcome"]["rehomed_to"] == "Avon Valley Apiary"
        dispatch = db.get(Dispatch, confirmed["dispatch"]["id"])
        assert dispatch.state == "completed"
        # the collector stays visible after the dispatch is closed
        report = report_service.get_report(db, fresh_report)
        assert report_service.display_volunteer(report).id == ranked["candidates"][0]["volunteer_id"]


def test_rehomed_outcome_requires_a_known_apiary(app_module, fresh_report):
    with session_scope() as db:
        with pytest.raises(ValidationError) as excinfo:
            outcome_service.record_outcome(
                db, fresh_report, {"result": "rehomed", "rehomed_to": ""}, demo_user_id()
            )
        assert excinfo.value.field == "rehomed_to"
        assert db.execute(select(func.count(Outcome.id))).scalar_one() >= 0


def test_funnel_keeps_lost_and_not_found_separate(app_module):
    with session_scope() as db:
        funnel = outcome_service.funnel(db)
        statuses = [row["status"] for row in funnel["terminal"]]
        assert statuses == ["lost", "not_found"]
        assert [row["status"] for row in funnel["stages"]] == [
            "new",
            "assigned",
            "collected",
            "rehomed",
        ]
        counted = sum(row["count"] for row in funnel["stages"]) + sum(
            row["count"] for row in funnel["terminal"]
        )
        assert counted == funnel["reports_total"]


def test_volunteer_validation(app_module):
    with session_scope() as db:
        with pytest.raises(ValidationError) as radius_error:
            volunteer_service.create_volunteer(
                db,
                {
                    "name": "Far Too Wide",
                    "phone": "07700 900555",
                    "lat": 51.4545,
                    "lon": -2.5879,
                    "coverage_radius_km": 90,
                },
            )
        assert radius_error.value.field == "coverage_radius_km"

        with pytest.raises(ValidationError) as area_error:
            volunteer_service.create_volunteer(
                db,
                {
                    "name": "Wrong Country",
                    "phone": "07700 900556",
                    "lat": 55.9533,
                    "lon": -3.1883,
                    "coverage_radius_km": 10,
                },
            )
        assert area_error.value.field == "lat"


def test_unknown_report_is_a_not_found_error(app_module):
    with session_scope() as db:
        with pytest.raises(NotFoundError):
            report_service.get_report(db, 10_000_000)


def test_seed_is_idempotent(app_module):
    import seed

    first = seed.seed_all(verbose=False)
    second = seed.seed_all(verbose=False)
    assert first == second
    assert first["users"] >= 1
    assert first["volunteers"] >= 8
    assert first["reports"] >= 30
    assert first["outcomes"] >= 10


def test_assigned_reports_only_lists_active_dispatches(app_module):
    with session_scope() as db:
        for row in report_service.assigned_reports(db):
            report = report_service.get_report(db, row["id"])
            assert report_service.active_dispatch(report) is not None
            assert row["assigned_volunteer"]


def test_dispatchable_reports_have_no_active_dispatch(app_module):
    with session_scope() as db:
        for row in report_service.dispatchable_reports(db):
            report = report_service.get_report(db, row["id"])
            assert report_service.active_dispatch(report) is None
            assert row["status"] == "new"
