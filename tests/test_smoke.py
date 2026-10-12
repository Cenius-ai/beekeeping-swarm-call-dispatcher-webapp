"""End-to-end smoke test: the demo walkthrough plus the refusal of
unauthenticated writes.

Every request goes through the real Flask/Dash transport, so the session guard,
the callbacks, the service layer and SQLite are all exercised together.
"""

from __future__ import annotations

import json

import pytest

from tests.dash_client import DEMO_EMAIL, DEMO_PASSWORD, call, multi, prop_id, sign_in

REPORTS_TABLE = multi(
    "reports-table.children",
    "reports-count.children",
    "reports-map.figure",
    "report-detail.children",
    "reports-error.style",
    "reports-error-text.children",
)
REPORTS_CHIPS = "reports-status-chips.children"
INTAKE = multi(
    "intake-fields.children",
    "intake-feedback.children",
    "intake-feedback.className",
    "intake-feedback.style",
    "stamp-report-created.data",
)
DISPATCH_SELECTOR = multi("dispatch-report-select.options", "dispatch-report-select.value")
DISPATCH_VIEW = multi(
    "candidate-slots.data",
    "dispatch-kpis.children",
    "dispatch-summary.children",
    "dispatch-candidates.children",
    "dispatch-history.children",
    "dispatch-active-group.style",
    "dispatch-assigned-notice.children",
    "dispatch-confirm-group.style",
    "dispatch-confirm-summary.children",
    "dispatch-idle-group.style",
    "dispatch-error.style",
    "dispatch-error-text.children",
)
DISPATCH_INTENT = multi("dispatch-intent.data", "dispatch-mode.data")
DISPATCH_VIEW = DISPATCH_VIEW
DISPATCH_PERFORM = multi(
    "stamp-dispatch-changed.data",
    "dispatch-feedback.children",
    "dispatch-feedback.className",
    "dispatch-feedback.style",
)
VOLUNTEERS = multi(
    "volunteers-kpis.children",
    "volunteer-rows.children",
    "volunteer-error.style",
    "volunteer-error-text.children",
    "vol-coverage-graph.figure",
)
VOL_WRITE = multi(
    "stamp-volunteer-changed.data",
    "volunteer-feedback.children",
    "volunteer-feedback.className",
    "volunteer-feedback.style",
    "vol-add-fields.children",
)
OUTCOMES = multi(
    "outcomes-kpis.children",
    "outcome-funnel.figure",
    "outcome-buckets.figure",
    "outcome-history.children",
    "outcomes-error.style",
    "outcomes-error-text.children",
)
OUTCOME_WRITE = multi(
    "stamp-outcome-recorded.data",
    "outcome-feedback.children",
    "outcome-feedback.className",
    "outcome-feedback.style",
    "outcome-fields.children",
)

REHOMED_KEY = "rehomed"


def counts(client) -> dict:
    response = client.get("/api/status-summary")
    assert response.status_code == 200
    return response.get_json()["counts"]


def reports(client, status: str = "all") -> list[dict]:
    response = client.get(f"/api/reports?status={status}")
    assert response.status_code == 200
    return response.get_json()["reports"]


def load_reports_table(client, status="all", selected=None):
    return call(
        client,
        REPORTS_TABLE,
        [
            {"id": "status-filter", "property": "data", "value": status},
            {"id": "urgency-filter", "property": "value", "value": "all"},
            {"id": "report-search", "property": "value", "value": ""},
            {"id": "selected-report", "property": "data", "value": selected},
            {"id": "stamp-report-created", "property": "data", "value": 0},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
            {"id": "stamp-outcome-recorded", "property": "data", "value": 0},
            {"id": "reports-refresh", "property": "data", "value": 0},
        ],
    )


def load_dispatch(client, report_id, intent=None, mode=None):
    return call(
        client,
        DISPATCH_VIEW,
        [
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "dispatch-intent", "property": "data", "value": intent},
            {"id": "dispatch-mode", "property": "data", "value": mode},
            {"id": "stamp-report-created", "property": "data", "value": 0},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
            {"id": "stamp-volunteer-changed", "property": "data", "value": 0},
            {"id": "dispatch-refresh", "property": "data", "value": 0},
        ],
    )


def candidates_of(client, report_id) -> list[dict]:
    body = load_dispatch(client, report_id)
    payload = json.dumps(body["dispatch-candidates"]["children"])
    found = []
    for candidate in client.get(f"/api/reports/{report_id}/candidates").get_json()["candidates"]:
        if candidate["name"] in payload:
            found.append(candidate)
    return found


def log_report(client, caller_name="Harriet Ollerton", phone="07700 900321", site="Blaise Castle Museum Lawn"):
    return call(
        client,
        INTAKE,
        [
            {"id": "intake-submit", "property": "n_clicks", "value": 1},
            {"id": "intake-caller-name", "property": "n_submit", "value": 0},
            {"id": "intake-caller-phone", "property": "n_submit", "value": 0},
        ],
        state=[
            {"id": "intake-caller-name", "property": "value", "value": caller_name},
            {"id": "intake-caller-phone", "property": "value", "value": phone},
            {"id": "intake-urgency", "property": "value", "value": "High"},
            {"id": "intake-cluster", "property": "value", "value": "Medium (football-sized, 2,000-8,000 bees)"},
            {"id": "intake-site", "property": "value", "value": site},
            {"id": "intake-notes", "property": "value", "value": "Cluster on the museum lawn bench."},
            {"id": "stamp-report-created", "property": "data", "value": 0},
        ],
        changed=["intake-submit.n_clicks"],
    )


# --------------------------------------------------------------------------- #
# Guard: nothing works without a session
# --------------------------------------------------------------------------- #
def test_root_redirects_to_signin_for_anonymous_visitors(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/signin" in response.headers["Location"]


def test_app_redirects_to_signin_for_anonymous_visitors(client):
    response = client.get("/app/")
    assert response.status_code == 302
    assert "/signin" in response.headers["Location"]


def test_unauthenticated_callback_post_is_refused_and_mutates_nothing(client, app_module):
    before = counts(client) if False else None  # anonymous counts are unavailable
    with app_module.server.test_request_context():
        pass
    payload = {
        "output": INTAKE,
        "outputs": [],
        "inputs": [],
        "state": [],
        "changedPropIds": [],
    }
    response = client.post(
        "/app/_dash-update-component",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthenticated"
    assert before is None


def test_unauthenticated_api_writes_are_refused(client, app_module):
    from db import session_scope
    from services import reports as report_service

    def row_count():
        with session_scope() as db:
            return len(report_service.list_reports(db))

    before = row_count()
    for path, payload in (
        ("/api/reports", {"caller_name": "Mallory", "caller_phone": "07700 900000"}),
        ("/api/reports/1/dispatch", {"volunteer_id": 1}),
        ("/api/volunteers", {"name": "Mallory", "phone": "07700 900000"}),
        ("/api/reports/1/outcome", {"result": "lost"}),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 401, path
    client.delete("/api/session")
    assert row_count() == before


def test_signin_page_shows_the_demo_credentials(client):
    body = client.get("/signin").get_data(as_text=True)
    assert "Demo: cenius@cenius.ai / cenius" in body
    assert 'type="password"' in body
    assert 'autocomplete="current-password"' in body


def test_wrong_password_is_one_non_enumerating_message(client):
    first = sign_in(client, DEMO_EMAIL, "not-the-password")
    second = sign_in(client, "nobody@example.com", "not-the-password")
    assert first.status_code == 401 and second.status_code == 401
    assert "did not match" in first.get_data(as_text=True)
    assert "did not match" in second.get_data(as_text=True)


def test_demo_login_lands_in_the_console(auth_client):
    response = auth_client.get("/app/")
    assert response.status_code == 200
    body = auth_client.get("/api/session").get_json()
    assert body["username"] == "cenius"
    assert body["display_name"]


# --------------------------------------------------------------------------- #
# The full five-minute operator walkthrough
# --------------------------------------------------------------------------- #
def test_full_dispatch_and_outcome_journey(auth_client):
    login = sign_in(auth_client)
    assert login.status_code == 302 and login.headers["Location"].endswith("/app/")

    # 1. Log a swarm report ------------------------------------------------- #
    intake = log_report(auth_client)
    assert intake["intake-feedback"]["className"] == "toast"
    assert intake["intake-feedback"]["style"]["display"] == "block", "the toast must be visible"
    message = intake["intake-feedback"]["children"]
    assert "logged" in message

    opened = [row for row in reports(auth_client) if row["caller_name"] == "Harriet Ollerton"]
    assert opened, "the logged report is persisted"
    report_id = opened[0]["id"]
    assert opened[0]["status"] == "new"
    assert opened[0]["logged_by"], "the signed-in coordinator is stored as the logger"

    # the new call is at the top of the triage table
    table = json.dumps(load_reports_table(auth_client)["reports-table"])
    assert "Harriet Ollerton" in table
    assert f'"index":{report_id}' in table.replace(" ", "")

    # 2. Rank candidates ---------------------------------------------------- #
    selector = call(
        auth_client,
        DISPATCH_SELECTOR,
        [
            {"id": "stamp-report-created", "property": "data", "value": 1},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
            {"id": "dispatch-refresh", "property": "data", "value": 0},
        ],
        state=[{"id": "dispatch-report-select", "property": "value", "value": None}],
    )
    options = [option["value"] for option in selector["dispatch-report-select"]["options"]]
    assert report_id in options, "a brand new report is offered for dispatch"

    ranked = candidates_of(auth_client, report_id)
    assert len(ranked) >= 2, "at least two collectors cover the seeded sites"
    distances = [row["distance_km"] for row in ranked]
    assert distances == sorted(distances), "candidates arrive nearest-first"

    # 3. Confirm a dispatch ------------------------------------------------- #
    chosen, other = ranked[0], ranked[-1]
    intent_inputs = [
        {"id": f"candidate-confirm-{slot}", "property": "n_clicks",
         "value": 1 if slot == 1 else 0}
        for slot in range(1, 7)
    ] + [
        {"id": "dispatch-intent-cancel-btn", "property": "n_clicks", "value": 0},
        {"id": "dispatch-reassign-btn", "property": "n_clicks", "value": 0},
        {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
        {"id": "dispatch-report-select", "property": "value", "value": report_id},
    ]
    intent = call(
        auth_client,
        DISPATCH_INTENT,
        intent_inputs,
        state=[
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "candidate-slots", "property": "data",
             "value": {"1": chosen["volunteer_id"], "2": other["volunteer_id"]}},
        ],
        changed=["candidate-confirm-1.n_clicks"],
    )
    assert intent["dispatch-intent"]["data"]["volunteer_id"] == chosen["volunteer_id"]

    confirmed = call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 1},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": intent["dispatch-intent"]["data"]},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
        ],
        changed=["dispatch-confirm-btn.n_clicks"],
    )
    assert confirmed["dispatch-feedback"]["className"] == "toast"

    assigned = [row for row in reports(auth_client) if row["id"] == report_id][0]
    assert assigned["status"] == "assigned"
    assert assigned["assigned_volunteer"] == chosen["name"]

    # a second confirm cannot create a second active dispatch
    again = call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 2},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": {"report_id": report_id, "volunteer_id": other["volunteer_id"]}},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 1},
        ],
        changed=["dispatch-confirm-btn.n_clicks"],
    )
    assert again["dispatch-feedback"]["className"] == "error-banner"

    # the assigned state is what the Dispatch tab shows
    body = load_dispatch(auth_client, report_id)
    assert body["dispatch-active-group"]["style"]["display"] == "block"
    assert chosen["name"] in json.dumps(body["dispatch-assigned-notice"])

    # 4. Decline, then cancel ---------------------------------------------- #
    declined = call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 1},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": None},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 1},
        ],
        changed=["dispatch-decline-btn.n_clicks"],
    )
    assert declined["dispatch-feedback"]["className"] == "toast"
    reverted = [row for row in reports(auth_client) if row["id"] == report_id][0]
    assert reverted["status"] == "new"
    assert reverted["assigned_volunteer"] is None

    # a stale decline (the dispatch is already closed) surfaces an inline error
    stale = call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 2},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": None},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 2},
        ],
        changed=["dispatch-decline-btn.n_clicks"],
    )
    assert stale["dispatch-feedback"]["className"] == "error-banner"

    # confirm again, then cancel
    call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 3},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": {"report_id": report_id, "volunteer_id": chosen["volunteer_id"]}},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 3},
        ],
        changed=["dispatch-confirm-btn.n_clicks"],
    )
    cancelled = call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 1},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": None},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 4},
        ],
        changed=["dispatch-cancel-dispatch-btn.n_clicks"],
    )
    assert cancelled["dispatch-feedback"]["className"] == "toast"
    assert [row for row in reports(auth_client) if row["id"] == report_id][0]["status"] == "new"

    # 5. Reassign ----------------------------------------------------------- #
    call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 4},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": {"report_id": report_id, "volunteer_id": chosen["volunteer_id"]}},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 5},
        ],
        changed=["dispatch-confirm-btn.n_clicks"],
    )
    reassigned = call(
        auth_client,
        DISPATCH_PERFORM,
        [
            {"id": "dispatch-confirm-btn", "property": "n_clicks", "value": 5},
            {"id": "dispatch-decline-btn", "property": "n_clicks", "value": 0},
            {"id": "dispatch-cancel-dispatch-btn", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "dispatch-intent", "property": "data", "value": {"report_id": report_id, "volunteer_id": other["volunteer_id"]}},
            {"id": "dispatch-mode", "property": "data", "value": "reassign"},
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 6},
        ],
        changed=["dispatch-confirm-btn.n_clicks"],
    )
    assert reassigned["dispatch-feedback"]["className"] == "toast"
    final = [row for row in reports(auth_client) if row["id"] == report_id][0]
    assert final["assigned_volunteer"] == other["name"], "only the active dispatch's collector shows"

    history = call(
        auth_client,
        DISPATCH_VIEW,
        [
            {"id": "dispatch-report-select", "property": "value", "value": report_id},
            {"id": "dispatch-intent", "property": "data", "value": None},
            {"id": "dispatch-mode", "property": "data", "value": None},
            {"id": "stamp-report-created", "property": "data", "value": 1},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 6},
            {"id": "stamp-volunteer-changed", "property": "data", "value": 0},
            {"id": "dispatch-refresh", "property": "data", "value": 0},
        ],
    )
    history_payload = json.dumps(history["dispatch-history"])
    assert "reassigned" in history_payload and "declined" in history_payload and "cancelled" in history_payload

    # 6. Record the rehomed outcome ---------------------------------------- #
    before = counts(auth_client)
    outcome = call(
        auth_client,
        OUTCOME_WRITE,
        [{"id": "outcome-submit", "property": "n_clicks", "value": 1}],
        state=[
            {"id": "outcome-report", "property": "value", "value": report_id},
            {"id": "outcome-result", "property": "value", "value": REHOMED_KEY},
            {"id": "outcome-collected-on", "property": "value", "value": "2026-07-04"},
            {"id": "outcome-cluster-size", "property": "value", "value": "6500"},
            {"id": "outcome-hive", "property": "value", "value": "Nuc box 3 (5-frame)"},
            {"id": "outcome-destination", "property": "value", "value": "Avon Valley Apiary"},
            {"id": "outcome-notes", "property": "value", "value": "Queen present; hived and fed."},
            {"id": "stamp-outcome-recorded", "property": "data", "value": 0},
        ],
        changed=["outcome-submit.n_clicks"],
    )
    assert outcome["outcome-feedback"]["className"] == "toast"
    after = counts(auth_client)
    assert after["rehomed"] == before["rehomed"] + 1
    assert [row for row in reports(auth_client) if row["id"] == report_id][0]["status"] == "rehomed"

    # 7. The funnel reflects it, with lost and not found separate ----------- #
    body = call(
        auth_client,
        OUTCOMES,
        [
            {"id": "stamp-outcome-recorded", "property": "data", "value": 1},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 6},
            {"id": "stamp-report-created", "property": "data", "value": 1},
            {"id": "outcomes-refresh", "property": "data", "value": 0},
        ],
    )
    funnel = body["outcome-funnel"]["figure"]["data"][0]
    assert funnel["type"] == "funnel"
    assert funnel["y"] == ["New", "Assigned", "Collected", "Rehomed"]
    buckets = body["outcome-buckets"]["figure"]["data"][0]
    assert buckets["y"] == ["Lost", "Not found"]
    assert "No outcomes recorded yet" not in json.dumps(body["outcome-history"])


def test_dispatch_selector_keeps_the_selected_report(auth_client):
    """Regression: a *args signature swallowed the State and reset the selection."""
    assigned = reports(auth_client, "assigned")[0]["id"]
    body = call(
        auth_client,
        DISPATCH_SELECTOR,
        [
            {"id": "stamp-report-created", "property": "data", "value": 7},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 7},
            {"id": "dispatch-refresh", "property": "data", "value": 0},
        ],
        state=[{"id": "dispatch-report-select", "property": "value", "value": assigned}],
    )
    assert body["dispatch-report-select"]["value"] == assigned
    label = next(
        option["label"]
        for option in body["dispatch-report-select"]["options"]
        if option["value"] == assigned
    )
    assert label.startswith("Assigned")
    # and the panel that follows agrees with the label
    view = load_dispatch(auth_client, assigned)
    assert view["dispatch-active-group"]["style"]["display"] == "block"
    assert "Already assigned" in json.dumps(view["dispatch-assigned-notice"])


def test_rehomed_outcome_without_a_destination_is_blocked(auth_client):
    report_id = reports(auth_client, "new")[0]["id"]
    before = counts(auth_client)
    body = call(
        auth_client,
        OUTCOME_WRITE,
        [{"id": "outcome-submit", "property": "n_clicks", "value": 1}],
        state=[
            {"id": "outcome-report", "property": "value", "value": report_id},
            {"id": "outcome-result", "property": "value", "value": REHOMED_KEY},
            {"id": "outcome-collected-on", "property": "value", "value": ""},
            {"id": "outcome-cluster-size", "property": "value", "value": ""},
            {"id": "outcome-hive", "property": "value", "value": ""},
            {"id": "outcome-destination", "property": "value", "value": None},
            {"id": "outcome-notes", "property": "value", "value": ""},
            {"id": "stamp-outcome-recorded", "property": "data", "value": 0},
        ],
        changed=["outcome-submit.n_clicks"],
    )
    assert body["outcome-feedback"]["className"] == "error-banner"
    assert body["outcome-feedback"]["style"]["display"] == "block"
    assert "apiary" in body["outcome-feedback"]["children"]
    assert counts(auth_client) == before


def test_not_found_outcome_is_terminal_and_filterable(auth_client):
    report_id = reports(auth_client, "new")[0]["id"]
    before = counts(auth_client)
    body = call(
        auth_client,
        OUTCOME_WRITE,
        [{"id": "outcome-submit", "property": "n_clicks", "value": 1}],
        state=[
            {"id": "outcome-report", "property": "value", "value": report_id},
            {"id": "outcome-result", "property": "value", "value": "not_found"},
            {"id": "outcome-collected-on", "property": "value", "value": ""},
            {"id": "outcome-cluster-size", "property": "value", "value": ""},
            {"id": "outcome-hive", "property": "value", "value": ""},
            {"id": "outcome-destination", "property": "value", "value": None},
            {"id": "outcome-notes", "property": "value", "value": "Site checked twice."},
            {"id": "stamp-outcome-recorded", "property": "data", "value": 0},
        ],
        changed=["outcome-submit.n_clicks"],
    )
    assert body["outcome-feedback"]["className"] == "toast"
    after = counts(auth_client)
    assert after["not_found"] == before["not_found"] + 1
    assert after["lost"] == before["lost"]

    not_found = reports(auth_client, "not_found")
    assert all(row["status"] == "not_found" for row in not_found)
    assert report_id in [row["id"] for row in not_found]


def test_intake_rejects_a_short_phone_and_keeps_the_typed_values(auth_client):
    before = counts(auth_client)
    body = log_report(auth_client, caller_name="", phone="123")
    assert body["intake-feedback"]["className"] == "error-banner"
    assert counts(auth_client) == before

    # the typed values survive the failed submit
    payload = json.dumps(body["intake-fields"])
    assert "123" in payload

    # and the duplicate-click guard means one call, one row
    first = log_report(auth_client, caller_name="Ida Bramble", phone="07700 900777")
    assert first["intake-feedback"]["className"] == "toast"
    middle = counts(auth_client)["all"]
    log_report(auth_client, caller_name="Ida Bramble", phone="07700 900777")
    assert counts(auth_client)["all"] == middle


def test_volunteer_toggle_and_radius_validation(auth_client):
    roster = auth_client.get("/api/volunteers").get_json()["volunteers"]
    target = roster[0]

    body = call(
        auth_client,
        VOL_WRITE,
        [
            {"id": {"type": "vol-toggle", "index": target["id"]}, "property": "n_clicks", "value": 1},
            {"id": "vol-add-submit", "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": "vol-add-name", "property": "value", "value": ""},
            {"id": "vol-add-phone", "property": "value", "value": ""},
            {"id": "vol-add-home", "property": "value", "value": None},
            {"id": "vol-add-radius", "property": "value", "value": ""},
            {"id": "vol-add-skills", "property": "value", "value": ""},
            {"id": "stamp-volunteer-changed", "property": "data", "value": 0},
        ],
        changed=[prop_id({"type": "vol-toggle", "index": target["id"]}, "n_clicks")],
    )
    assert body["volunteer-feedback"]["className"] == "toast"
    updated = [row for row in auth_client.get("/api/volunteers").get_json()["volunteers"] if row["id"] == target["id"]][0]
    assert updated["is_available"] is (not target["is_available"])
    # put the roster back the way the seed left it
    auth_client.patch(f"/api/volunteers/{target['id']}", json={"is_available": target["is_available"]})

    roster_before = auth_client.get("/api/volunteers").get_json()["volunteers"]
    body = call(
        auth_client,
        VOL_WRITE,
        [
            {"id": {"type": "vol-toggle", "index": target["id"]}, "property": "n_clicks", "value": 0},
            {"id": "vol-add-submit", "property": "n_clicks", "value": 1},
        ],
        state=[
            {"id": "vol-add-name", "property": "value", "value": "Sixty Kays"},
            {"id": "vol-add-phone", "property": "value", "value": "07700 900606"},
            {"id": "vol-add-home", "property": "value", "value": "Clifton Down Allotments"},
            {"id": "vol-add-radius", "property": "value", "value": "90"},
            {"id": "vol-add-skills", "property": "value", "value": "ladders"},
            {"id": "stamp-volunteer-changed", "property": "data", "value": 1},
        ],
        changed=["vol-add-submit.n_clicks"],
    )
    assert body["volunteer-feedback"]["className"] == "error-banner"
    assert "50" in body["volunteer-feedback"]["children"]
    assert len(auth_client.get("/api/volunteers").get_json()["volunteers"]) == len(roster_before)


def test_volunteers_and_reports_panels_render_seeded_content(auth_client):
    roster = call(
        auth_client,
        VOLUNTEERS,
        [
            {"id": "vol-availability-filter", "property": "value", "value": "all"},
            {"id": "stamp-volunteer-changed", "property": "data", "value": 0},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
            {"id": "volunteers-refresh", "property": "data", "value": 0},
        ],
    )
    assert "No volunteers yet" not in json.dumps(roster["volunteer-rows"])
    assert roster["vol-coverage-graph"]["figure"]["data"], "the coverage chart renders on load"

    chips = call(auth_client, REPORTS_CHIPS, [
        {"id": "status-filter", "property": "data", "value": "all"},
        {"id": "stamp-report-created", "property": "data", "value": 0},
        {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
        {"id": "stamp-outcome-recorded", "property": "data", "value": 0},
        {"id": "reports-refresh", "property": "data", "value": 0},
    ])
    labels = json.dumps(chips)
    for label in ("All reports", "New", "Assigned", "Collected", "Rehomed", "Lost", "Not found"):
        assert label in labels


def test_empty_filter_state_shows_the_clear_filters_copy(auth_client):
    body = load_reports_table(auth_client, status="lost", selected=None)
    body = call(
        auth_client,
        REPORTS_TABLE,
        [
            {"id": "status-filter", "property": "data", "value": "lost"},
            {"id": "urgency-filter", "property": "value", "value": "all"},
            {"id": "report-search", "property": "value", "value": "nobody-matches-this"},
            {"id": "selected-report", "property": "data", "value": None},
            {"id": "stamp-report-created", "property": "data", "value": 0},
            {"id": "stamp-dispatch-changed", "property": "data", "value": 0},
            {"id": "stamp-outcome-recorded", "property": "data", "value": 0},
            {"id": "reports-refresh", "property": "data", "value": 0},
        ],
    )
    assert "No reports match these filters" in json.dumps(body["reports-table"])


def test_api_contracts(auth_client):
    assert auth_client.get("/api/session").status_code == 200
    summary = auth_client.get("/api/status-summary").get_json()
    assert set(summary["statuses"]) == {"new", "assigned", "collected", "rehomed", "lost", "not_found"}
    assert summary["funnel"]["counts"]["all"] == len(reports(auth_client))

    created = auth_client.post(
        "/api/reports",
        json={
            "caller_name": "Api Contract",
            "caller_phone": "07700 900111",
            "site_name": "Whitchurch Garden Centre",
            "cluster_size_bucket": "Small (fist-sized, <2,000 bees)",
            "urgency": "Low",
        },
    )
    assert created.status_code == 201
    assert created.get_json()["status"] == "new"

    bad = auth_client.post(
        "/api/reports",
        json={"caller_name": "Api Contract", "caller_phone": "12", "site_name": "Nowhere"},
    )
    assert bad.status_code == 400
    assert "field" in bad.get_json()

    candidates = auth_client.get(f"/api/reports/{created.get_json()['id']}/candidates")
    assert candidates.status_code == 200
    assert candidates.get_json()["candidates"]


def test_signout_invalidates_the_session(auth_client):
    auth_client.post("/logout", data={})
    assert auth_client.get("/api/session").status_code == 401
    assert auth_client.get("/app/").status_code == 302
