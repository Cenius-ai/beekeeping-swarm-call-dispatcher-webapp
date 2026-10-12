"""Every Dash callback for the dispatcher.

One writer per output property, app-wide. Callbacks that mutate state open a
transaction through :func:`db.session_scope` and bump a single-purpose stamp
store, which is what the tab-level read callbacks listen to.
"""

from __future__ import annotations

import logging

from dash import Input, Output, State, callback, ctx, no_update
from dash.exceptions import PreventUpdate
from sqlalchemy.exc import SQLAlchemyError

from db import session_scope, utcnow_iso
from services import dispatch as dispatch_service
from services import outcomes as outcome_service
from services import reports as report_service
from services import volunteers as volunteer_service
from services.errors import ServiceError
from ui import dispatch_tab, outcomes_tab, reports_tab, volunteers_tab

logger = logging.getLogger(__name__)

TAB_ORDER = ("reports", "dispatch", "volunteers", "outcomes")


def _visible(message) -> dict:
    return {"display": "block"} if message else {"display": "none"}


def _next_stamp(value) -> int:
    try:
        return int(value or 0) + 1
    except (TypeError, ValueError):
        return 1


# --------------------------------------------------------------------------- #
# Shell: tab routing and the URL round trip
# --------------------------------------------------------------------------- #
@callback(
    *[Output(f"panel-{tab}", "className") for tab in TAB_ORDER],
    *[Output(f"panel-{tab}", "aria-hidden") for tab in TAB_ORDER],
    Input("tabs", "value"),
)
def show_active_panel(active):
    active = active if active in TAB_ORDER else "reports"
    classes = [
        "tabpanel tabpanel--active" if tab == active else "tabpanel" for tab in TAB_ORDER
    ]
    hidden = ["false" if tab == active else "true" for tab in TAB_ORDER]
    return (*classes, *hidden)


@callback(
    Output("tabs", "value"),
    Input("url", "search"),
)
def read_tab_from_url(search):
    """Deep links such as /app/?tab=volunteers open on that tab.

    The reverse direction (tab click updates the address bar) is handled by
    static/app-behaviour.js with history.replaceState, so Dash sees a simple
    one-way dependency instead of a cycle.
    """
    if not search:
        return "reports"
    for part in str(search).lstrip("?").split("&"):
        key, _, value = part.partition("=")
        if key == "tab" and value in TAB_ORDER:
            return value
    return "reports"


@callback(
    Output("tabs", "value", allow_duplicate=True),
    Input({"type": "goto-tab", "index": "ALL"}, "n_clicks"),
    prevent_initial_call=True,
)
def jump_to_tab(_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("index") in TAB_ORDER:
        if ctx.triggered and ctx.triggered[0]["value"]:
            return triggered["index"]
    raise PreventUpdate


@callback(
    Output("coordinator-name", "children"),
    Output("coordinator-role", "children"),
    Output("logout-csrf", "value"),
    Input("url", "pathname"),
)
def hydrate_session(_pathname):
    """Identity and CSRF token come from the server session, never the browser."""
    from auth import csrf_token, current_user

    user = current_user()
    if user is None:
        return "Coordinator", "Sign-in required", no_update
    return user.display_name, f"Coordinator · {user.username}", csrf_token()


# --------------------------------------------------------------------------- #
# Reports tab
# --------------------------------------------------------------------------- #
@callback(
    Output("reports-status-chips", "children"),
    Input("status-filter", "data"),
    Input("stamp-report-created", "data"),
    Input("stamp-dispatch-changed", "data"),
    Input("stamp-outcome-recorded", "data"),
    Input("reports-refresh", "data"),
)
def render_status_chips(active, *_stamps):
    active = active or "all"
    with session_scope() as db:
        counts = report_service.status_counts(db)
    return reports_tab.chip_row(counts, active)


@callback(
    Output("status-filter", "data"),
    Input({"type": "status-chip", "index": "ALL"}, "n_clicks"),
    prevent_initial_call=True,
)
def set_status_filter(_clicks):
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        raise PreventUpdate
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    return triggered["index"]


@callback(
    Output("reports-table", "children"),
    Output("reports-count", "children"),
    Output("reports-map", "figure"),
    Output("report-detail", "children"),
    Output("reports-error", "style"),
    Output("reports-error-text", "children"),
    Input("status-filter", "data"),
    Input("urgency-filter", "value"),
    Input("report-search", "value"),
    Input("selected-report", "data"),
    Input("stamp-report-created", "data"),
    Input("stamp-dispatch-changed", "data"),
    Input("stamp-outcome-recorded", "data"),
    Input("reports-refresh", "data"),
)
def render_reports_table(status, urgency, search, selected_id, *_stamps):
    status = status or "all"
    with session_scope() as db:
        view = reports_tab.load_view(db, status, urgency or "all", search or "", selected_id)
    selected = (view["selected"] or {}).get("id")
    error_style = {"display": "flex"} if view["error"] else {"display": "none"}
    return (
        reports_tab.table(view["rows"], selected),
        reports_tab.count_caption(len(view["rows"]), view["counts"].get("all", 0)),
        reports_tab.swarm_map(view["rows"], selected),
        reports_tab.detail_panel(view["selected"]),
        error_style,
        view["error"] or "",
    )


@callback(
    Output("selected-report", "data"),
    Input({"type": "report-row", "index": "ALL"}, "n_clicks"),
    Input({"type": "report-link", "index": "ALL"}, "n_clicks"),
    Input("reports-map", "clickData"),
    prevent_initial_call=True,
)
def select_report(_row_clicks, _link_clicks, click_data):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        index = triggered.get("index")
        if not index or int(index) <= 0:
            raise PreventUpdate
        return int(index)
    if triggered == "reports-map" and click_data:
        try:
            return int(click_data["points"][0]["customdata"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            raise PreventUpdate from None
    raise PreventUpdate


@callback(
    Output("intake-fields", "children"),
    Output("intake-feedback", "children"),
    Output("intake-feedback", "className"),
    Output("intake-feedback", "style"),
    Output("stamp-report-created", "data"),
    Input("intake-submit", "n_clicks"),
    Input("intake-caller-name", "n_submit"),
    Input("intake-caller-phone", "n_submit"),
    State("intake-caller-name", "value"),
    State("intake-caller-phone", "value"),
    State("intake-urgency", "value"),
    State("intake-cluster", "value"),
    State("intake-site", "value"),
    State("intake-notes", "value"),
    State("stamp-report-created", "data"),
    running=[(Output("intake-submit", "disabled"), True, False)],
    prevent_initial_call=True,
)
def log_swarm_report(
    _clicks, _name_submit, _phone_submit,
    caller_name, caller_phone, urgency, cluster_size, site_name, notes, stamp,
):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    values = {
        "caller_name": caller_name or "",
        "caller_phone": caller_phone or "",
        "urgency": urgency or "Normal",
        "cluster_size_bucket": cluster_size or "",
        "site_name": site_name or "",
        "notes": notes or "",
    }
    # The coordinator id comes from the server-side session, never the browser.
    from auth import current_user_id

    user_id = current_user_id()
    if not user_id:
        raise PreventUpdate

    try:
        with session_scope() as db:
            created = report_service.create_report(db, values, user_id)
    except ServiceError as exc:
        fields = reports_tab.intake_fields(values, {exc.field or "caller_name": exc.message})
        return fields, exc.message, "error-banner", _visible(exc.message), no_update
    except SQLAlchemyError:
        logger.exception("logging a swarm report failed")
        fields = reports_tab.intake_fields(values, {})
        message = "We could not save that report. Try again."
        return fields, message, "error-banner", _visible(message), no_update

    fields = reports_tab.intake_fields({}, {})
    message = f"Report #{created['id']} logged for {created['site_name']} - it is at the top of the table."
    return fields, message, "toast", _visible(message), _next_stamp(stamp)


# --------------------------------------------------------------------------- #
# Dispatch tab
# --------------------------------------------------------------------------- #
@callback(
    Output("dispatch-report-select", "options"),
    Output("dispatch-report-select", "value"),
    Input("stamp-report-created", "data"),
    Input("stamp-dispatch-changed", "data"),
    Input("dispatch-refresh", "data"),
    State("dispatch-report-select", "value"),
)
def refresh_report_selector(_created, _dispatch_changed, _refresh, current=None):
    # `current` must stay a named parameter: Dash passes every input and state
    # positionally, so a *args signature would swallow the selected report and
    # silently fall back to the newest one.
    with session_scope() as db:
        view = dispatch_tab.load_view(db, current)
    return view["options"], view["value"]


@callback(
    Output("dispatch-intent", "data"),
    Output("dispatch-mode", "data"),
    *[Input(f"candidate-confirm-{slot}", "n_clicks") for slot in range(1, dispatch_tab.MAX_CANDIDATE_SLOTS + 1)],
    Input("dispatch-intent-cancel-btn", "n_clicks"),
    Input("dispatch-reassign-btn", "n_clicks"),
    Input("stamp-dispatch-changed", "data"),
    Input("dispatch-report-select", "value"),
    State("dispatch-mode", "data"),
    State("candidate-slots", "data"),
    prevent_initial_call=True,
)
def update_dispatch_intent(*args):
    *clicks, mode, slots = args
    slot_clicks = clicks[: dispatch_tab.MAX_CANDIDATE_SLOTS]
    triggered = ctx.triggered_id

    if isinstance(triggered, str) and triggered.startswith("candidate-confirm-"):
        slot = triggered.rsplit("-", 1)[1]
        if not slot_clicks[int(slot) - 1]:
            raise PreventUpdate
        volunteer_id = (slots or {}).get(slot)
        if not volunteer_id:
            raise PreventUpdate
        return {"report_id": clicks[-1], "volunteer_id": volunteer_id}, mode
    if triggered == "dispatch-intent-cancel-btn":
        return None, mode
    if triggered == "dispatch-reassign-btn":
        return None, "reassign"
    return None, None


@callback(
    Output("candidate-slots", "data"),
    Output("dispatch-kpis", "children"),
    Output("dispatch-summary", "children"),
    Output("dispatch-candidates", "children"),
    Output("dispatch-history", "children"),
    Output("dispatch-active-group", "style"),
    Output("dispatch-assigned-notice", "children"),
    Output("dispatch-confirm-group", "style"),
    Output("dispatch-confirm-summary", "children"),
    Output("dispatch-idle-group", "style"),
    Output("dispatch-error", "style"),
    Output("dispatch-error-text", "children"),
    Input("dispatch-report-select", "value"),
    Input("dispatch-intent", "data"),
    Input("dispatch-mode", "data"),
    Input("stamp-report-created", "data"),
    Input("stamp-dispatch-changed", "data"),
    Input("stamp-volunteer-changed", "data"),
    Input("dispatch-refresh", "data"),
)
def render_dispatch(report_id, intent, mode, *_stamps):
    with session_scope() as db:
        view = dispatch_tab.load_view(db, report_id, mode, intent)

    ranking = view["ranking"] or {}
    assigned = ranking.get("status") == "assigned" and bool(ranking.get("dispatch"))
    show_confirm = bool(intent) and (mode == "reassign" or not assigned)
    show_assigned = assigned and not show_confirm
    show_idle = not show_confirm and not show_assigned

    # candidates_body also records the slot -> collector map used by the
    # confirm buttons, so build it before assembling the response.
    candidate_rows = dispatch_tab.candidates_body(view)

    return (
        view.get("slots") or {},
        dispatch_tab.kpi_strip(view),
        dispatch_tab.report_summary(view),
        candidate_rows,
        dispatch_tab.history_table(view["history"]),
        {"display": "block"} if show_assigned else {"display": "none"},
        dispatch_tab.assigned_notice(view),
        {"display": "block"} if show_confirm else {"display": "none"},
        dispatch_tab.confirm_summary(view),
        {"display": "block"} if show_idle else {"display": "none"},
        {"display": "flex"} if view["error"] else {"display": "none"},
        view["error"] or "",
    )


@callback(
    Output("stamp-dispatch-changed", "data"),
    Output("dispatch-feedback", "children"),
    Output("dispatch-feedback", "className"),
    Output("dispatch-feedback", "style"),
    Input("dispatch-confirm-btn", "n_clicks"),
    Input("dispatch-decline-btn", "n_clicks"),
    Input("dispatch-cancel-dispatch-btn", "n_clicks"),
    State("dispatch-intent", "data"),
    State("dispatch-mode", "data"),
    State("dispatch-report-select", "value"),
    State("stamp-dispatch-changed", "data"),
    running=[(Output("dispatch-confirm-btn", "disabled"), True, False)],
    prevent_initial_call=True,
)
def perform_dispatch(_confirm, _decline, _cancel, intent, mode, report_id, stamp):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate

    from auth import current_user_id

    user_id = current_user_id()
    if not user_id or not report_id:
        raise PreventUpdate

    action = ctx.triggered_id
    try:
        with session_scope() as db:
            if action == "dispatch-confirm-btn":
                if not intent or not intent.get("volunteer_id"):
                    raise ServiceError("Pick a collector from the ranked list first.")
                if mode == "reassign":
                    result = dispatch_service.reassign_dispatch(
                        db, int(report_id), int(intent["volunteer_id"]), user_id
                    )
                    message = (
                        f"Reassigned report #{result['report']['id']} to "
                        f"{result['dispatch']['volunteer_name']}."
                    )
                else:
                    result = dispatch_service.confirm_dispatch(
                        db, int(report_id), int(intent["volunteer_id"]), user_id
                    )
                    message = (
                        f"Dispatched {result['dispatch']['volunteer_name']} to report "
                        f"#{result['report']['id']} ({result['dispatch']['distance_km']:.1f} km)."
                    )
            else:
                active = dispatch_service.active_dispatch_for(db, int(report_id))
                if active is None:
                    raise ServiceError("That report has no active dispatch to close.")
                if action == "dispatch-decline-btn":
                    dispatch_service.decline_dispatch(db, active.id, user_id)
                    message = (
                        f"{active.volunteer.name} declined — report #{active.report_id} is back "
                        "in the pending list."
                    )
                else:
                    dispatch_service.cancel_dispatch(db, active.id, user_id)
                    message = (
                        f"Dispatch for report #{active.report_id} cancelled — the call is pending again."
                    )
    except ServiceError as exc:
        return no_update, exc.message, "error-banner", _visible(exc.message)
    except SQLAlchemyError:
        logger.exception("dispatch action failed")
        message = "We could not complete that action. Try again."
        return no_update, message, "error-banner", _visible(message)

    return _next_stamp(stamp), message, "toast", _visible(message)


# --------------------------------------------------------------------------- #
# Volunteers tab
# --------------------------------------------------------------------------- #
@callback(
    Output("volunteers-kpis", "children"),
    Output("volunteer-rows", "children"),
    Output("volunteer-error", "style"),
    Output("volunteer-error-text", "children"),
    Output("vol-coverage-graph", "figure"),
    Input("vol-availability-filter", "value"),
    Input("stamp-volunteer-changed", "data"),
    Input("stamp-dispatch-changed", "data"),
    Input("volunteers-refresh", "data"),
)
def render_volunteers(availability, *_stamps):
    with session_scope() as db:
        view = volunteers_tab.load_view(db, availability or "all")
    return (
        volunteers_tab.kpi_strip(view),
        volunteers_tab.roster_table(view["rows"], view["error"]),
        {"display": "flex"} if view["error"] else {"display": "none"},
        view["error"] or "",
        volunteers_tab.coverage_figure(view["rows"]),
    )


@callback(
    Output("stamp-volunteer-changed", "data"),
    Output("volunteer-feedback", "children"),
    Output("volunteer-feedback", "className"),
    Output("volunteer-feedback", "style"),
    Output("vol-add-fields", "children"),
    Input({"type": "vol-toggle", "index": "ALL"}, "n_clicks"),
    Input("vol-add-submit", "n_clicks"),
    State("vol-add-name", "value"),
    State("vol-add-phone", "value"),
    State("vol-add-home", "value"),
    State("vol-add-radius", "value"),
    State("vol-add-skills", "value"),
    State("stamp-volunteer-changed", "data"),
    running=[(Output("vol-add-submit", "disabled"), True, False)],
    prevent_initial_call=True,
)
def write_volunteer(_toggles, _add_clicks, name, phone, home, radius, skills, stamp):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate

    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        volunteer_id = triggered.get("index")
        if not volunteer_id or int(volunteer_id) <= 0:
            raise PreventUpdate
        try:
            with session_scope() as db:
                current = volunteer_service.get_volunteer(db, int(volunteer_id))
                updated = volunteer_service.update_volunteer(
                    db, int(volunteer_id), {"is_available": not current.is_available}
                )
        except ServiceError as exc:
            return no_update, exc.message, "error-banner", _visible(exc.message), no_update
        except SQLAlchemyError:
            logger.exception("availability toggle failed")
            message = "Could not update availability. Try again."
            return no_update, message, "error-banner", _visible(message), no_update
        state = "available" if updated["is_available"] else "unavailable"
        message = f"{updated['name']} is now {state} for dispatch."
        return _next_stamp(stamp), message, "toast", _visible(message), no_update

    site = home or None
    values = {
        "name": name or "",
        "phone": phone or "",
        "home": site or "",
        "coverage_radius_km": radius,
        "skills": skills or "",
    }
    from data import sites as site_catalogue

    site_record = site_catalogue.lookup(site or "")
    payload = {
        "name": values["name"],
        "phone": values["phone"],
        "lat": site_record["lat"] if site_record else None,
        "lon": site_record["lon"] if site_record else None,
        "coverage_radius_km": values["coverage_radius_km"],
        "skills": values["skills"],
    }
    if site_record is None:
        message = "Pick the collector's home location from the list."
        return (
            no_update,
            message,
            "error-banner",
            _visible(message),
            volunteers_tab.add_volunteer_fields(values, {"home": "Pick a home location."}),
        )
    try:
        with session_scope() as db:
            created = volunteer_service.create_volunteer(db, payload)
    except ServiceError as exc:
        fields = volunteers_tab.add_volunteer_fields(values, {exc.field or "name": exc.message})
        return no_update, exc.message, "error-banner", _visible(exc.message), fields
    except SQLAlchemyError:
        logger.exception("adding a collector failed")
        fields = volunteers_tab.add_volunteer_fields(values, {})
        message = "We could not add that collector. Try again."
        return no_update, message, "error-banner", _visible(message), fields

    message = f"{created['name']} added to the roster with {created['coverage_radius_km']:.0f} km coverage."
    return (
        _next_stamp(stamp),
        message,
        "toast",
        _visible(message),
        volunteers_tab.add_volunteer_fields({}, {}),
    )


# --------------------------------------------------------------------------- #
# Outcomes tab
# --------------------------------------------------------------------------- #
@callback(
    Output("outcomes-kpis", "children"),
    Output("outcome-funnel", "figure"),
    Output("outcome-buckets", "figure"),
    Output("outcome-history", "children"),
    Output("outcomes-error", "style"),
    Output("outcomes-error-text", "children"),
    Input("stamp-outcome-recorded", "data"),
    Input("stamp-dispatch-changed", "data"),
    Input("stamp-report-created", "data"),
    Input("outcomes-refresh", "data"),
)
def render_outcomes(*_stamps):
    with session_scope() as db:
        view = outcomes_tab.load_view(db)
    return (
        outcomes_tab.kpi_strip(view),
        outcomes_tab.funnel_figure(view["funnel"]),
        outcomes_tab.terminal_figure(view["funnel"]),
        outcomes_tab.season_history_table(view["outcome_rows"]),
        {"display": "flex"} if view["error"] else {"display": "none"},
        view["error"] or "",
    )


@callback(
    Output("outcome-report", "options"),
    Output("outcome-report", "value"),
    Input("stamp-report-created", "data"),
    Input("stamp-outcome-recorded", "data"),
    Input("outcomes-refresh", "data"),
    State("outcome-report", "value"),
)
def refresh_outcome_reports(_created, _recorded, _refresh, current=None):
    with session_scope() as db:
        view = outcomes_tab.load_view(db, current)
    return view["report_options"], view["report_id"]


@callback(
    Output("report-outcome-history", "children"),
    Output("outcome-collector", "children"),
    Input("outcome-report", "value"),
)
def render_report_outcomes(report_id):
    with session_scope() as db:
        view = outcomes_tab.load_view(db, report_id)
    collector = view["collector"] or (
        "No active dispatch — record the outcome against the report anyway."
    )
    return outcomes_tab.report_history_table(view["report_outcomes"]), collector


@callback(
    Output("stamp-outcome-recorded", "data"),
    Output("outcome-feedback", "children"),
    Output("outcome-feedback", "className"),
    Output("outcome-feedback", "style"),
    Output("outcome-fields", "children"),
    Input("outcome-submit", "n_clicks"),
    State("outcome-report", "value"),
    State("outcome-result", "value"),
    State("outcome-collected-on", "value"),
    State("outcome-cluster-size", "value"),
    State("outcome-hive", "value"),
    State("outcome-destination", "value"),
    State("outcome-notes", "value"),
    State("stamp-outcome-recorded", "data"),
    running=[(Output("outcome-submit", "disabled"), True, False)],
    prevent_initial_call=True,
)
def record_outcome(_clicks, report_id, result, collected_on, cluster_size, hive, destination, notes, stamp):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate

    from auth import current_user_id

    user_id = current_user_id()
    if not user_id:
        raise PreventUpdate

    values = {
        "report_id": report_id,
        "result": result,
        "collected_on": collected_on or "",
        "actual_cluster_size": cluster_size,
        "hive_box": hive or "",
        "rehomed_to": destination or "",
        "notes": notes or "",
    }

    with session_scope() as db:
        view = outcomes_tab.load_view(db, report_id)

    def rebuild(errors, values_for_form):
        return outcomes_tab.outcome_fields(
            values_for_form, errors, view["report_options"], view["report_id"], view["collector"]
        )

    if not report_id:
        message = "Pick the swarm report this outcome belongs to."
        return no_update, message, "error-banner", _visible(message), rebuild(
            {"report_id": "Pick a report."}, values
        )

    recorded_at = utcnow_iso()
    if collected_on:
        recorded_at = f"{collected_on}T00:00:00+00:00"

    try:
        with session_scope() as db:
            result_payload = outcome_service.record_outcome(
                db,
                int(report_id),
                {
                    "result": result,
                    "rehomed_to": destination or "",
                    "actual_cluster_size": cluster_size,
                    "hive_box": hive or "",
                    "notes": notes or "",
                    "recorded_at": recorded_at,
                },
                user_id,
            )
    except ServiceError as exc:
        return (
            no_update,
            exc.message,
            "error-banner",
            _visible(exc.message),
            rebuild({exc.field or "result": exc.message}, values),
        )
    except SQLAlchemyError:
        logger.exception("recording an outcome failed")
        message = "We could not record that outcome. Try again."
        return no_update, message, "error-banner", _visible(message), rebuild({}, values)

    status = result_payload["report_status"].replace("_", " ")
    message = f"Report #{report_id} is now '{status}'. The funnel and the map have been updated."
    fields = rebuild({}, {"collected_on": collected_on or "", "report_id": report_id})
    return _next_stamp(stamp), message, "toast", _visible(message), fields


# --------------------------------------------------------------------------- #
# Retry controls
# --------------------------------------------------------------------------- #
@callback(
    Output("reports-refresh", "data"),
    Output("dispatch-refresh", "data"),
    Output("volunteers-refresh", "data"),
    Output("outcomes-refresh", "data"),
    Input("reports-retry", "n_clicks"),
    Input("dispatch-retry", "n_clicks"),
    Input("volunteer-retry", "n_clicks"),
    Input("outcomes-retry", "n_clicks"),
    State("reports-refresh", "data"),
    State("dispatch-refresh", "data"),
    State("volunteers-refresh", "data"),
    State("outcomes-refresh", "data"),
    prevent_initial_call=True,
)
def retry_panel(_r, _d, _v, _o, reports, dispatch, volunteers, outcomes):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    triggered = ctx.triggered_id
    if triggered == "reports-retry":
        return _next_stamp(reports), dispatch, volunteers, outcomes
    if triggered == "dispatch-retry":
        return reports, _next_stamp(dispatch), volunteers, outcomes
    if triggered == "volunteer-retry":
        return reports, dispatch, _next_stamp(volunteers), outcomes
    return reports, dispatch, volunteers, _next_stamp(outcomes)
