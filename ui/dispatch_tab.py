"""Dispatch tab: the report selector, the distance-ranked candidate list and the
dispatch lifecycle actions."""

from __future__ import annotations

import logging

from dash import dcc, html
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.errors import ServiceError

from db import utcnow_iso
from services import dispatch as dispatch_service
from services import ranking as ranking_service
from services import reports as report_service
from services import volunteers as volunteer_service
from ui.components import (
    card,
    loading,
    empty_state,
    error_panel,
    feedback_panel,
    format_utc,
    stat,
    status_pill,
    utc_span,
)
logger = logging.getLogger(__name__)

DISPATCH_ERROR_COPY = "We could not refresh the dispatch board just now. Try again in a moment."
NO_PENDING_COPY = "Every report has an active dispatch - beautiful."

#: Candidate rows are rendered into a fixed set of slots: the confirm buttons
#: keep stable ids, so the callback never depends on a wildcard that could be
#: mid-replacement.
MAX_CANDIDATE_SLOTS = 6
NO_REPORTS_COPY = "Nothing is waiting for a collector. Log a swarm call on the Reports tab."


def load_view(db: Session, report_id: int | None = None, mode: str | None = None,
              intent: dict | None = None) -> dict:
    view = {
        "options": [],
        "value": None,
        "ranking": None,
        "pending_count": 0,
        "assigned_count": 0,
        "available_volunteers": 0,
        "active_dispatches": 0,
        "mean_distance": 0.0,
        "history": [],
        "mode": mode,
        "intent": intent,
        "slots": {},
        "now_iso": utcnow_iso(),
        "error": None,
    }
    try:
        pending = report_service.dispatchable_reports(db)
        assigned = report_service.assigned_reports(db)
        view["pending_count"] = len(pending)
        view["assigned_count"] = len(assigned)
        view["available_volunteers"] = len(
            [v for v in volunteer_service.list_volunteers(db, "available")]
        )
        view["active_dispatches"] = view["assigned_count"]

        options = [
            {
                "label": f"Needs dispatch · {row['site_name']} · {row['cluster_size_bucket'].split(' (')[0]}",
                "value": row["id"],
            }
            for row in pending
        ] + [
            {
                "label": f"Assigned · {row['site_name']} · {row['assigned_volunteer']}",
                "value": row["id"],
            }
            for row in assigned
        ]
        view["options"] = options

        chosen = report_id if any(option["value"] == report_id for option in options) else None
        if chosen is None:
            chosen = pending[0]["id"] if pending else (options[0]["value"] if options else None)
        view["value"] = chosen

        if chosen is not None:
            view["ranking"] = ranking_service.rank_candidates(db, chosen)
            view["history"] = dispatch_service.dispatch_history(db, chosen)
            distances = [
                row["distance_km"] for row in view["history"] if row["distance_km"]
            ]
            view["mean_distance"] = round(sum(distances) / len(distances), 1) if distances else 0.0
    except (ServiceError, SQLAlchemyError):
        logger.exception("loading the dispatch board failed")
        view["error"] = DISPATCH_ERROR_COPY
    return view


def kpi_strip(view: dict) -> html.Div:
    ranking = view["ranking"] or {}
    candidates = ranking.get("candidates") or []
    nearest = f"{candidates[0]['distance_km']:.1f} km" if candidates else "—"
    return html.Div(
        className="kpi-strip",
        children=[
            stat("Awaiting dispatch", view["pending_count"], "reports with no collector", "warn", "◉"),
            stat("Collectors available", view["available_volunteers"], "eligible right now", "ok", "☰"),
            stat("Active dispatches", view["active_dispatches"], "confirmed and in progress", "accent", "→"),
            stat("Nearest candidate", nearest, "for the selected report", "info", "◆"),
            stat("Mean trip", f"{view['mean_distance']:.1f} km" if view["mean_distance"] else "—",
                 "across this report's history", "", "◈"),
            stat("Awaiting assignment", view["assigned_count"], "already assigned", "muted", "◌"),
        ],
    )


def report_summary(view: dict) -> list:
    """The selected report's identifying fields, shared by the selector card."""
    ranking = view["ranking"] or {}
    report = ranking.get("report")
    if report is None:
        return [empty_state("No report selected", NO_REPORTS_COPY)]
    return [
        html.Dl(
            className="detail-list",
            children=[
                html.Div(className="detail-row", children=[html.Dt("Caller"), html.Dd(report["caller_name"])]),
                html.Div(className="detail-row", children=[html.Dt("Phone"), html.Dd(html.Span(report["caller_phone"], className="mono"))]),
                html.Div(className="detail-row", children=[html.Dt("Site"), html.Dd(report["site_name"])]),
                html.Div(className="detail-row", children=[html.Dt("Cluster"), html.Dd(report["cluster_size_bucket"])]),
                html.Div(className="detail-row", children=[html.Dt("Urgency"), html.Dd(report["urgency"])]),
                html.Div(className="detail-row", children=[html.Dt("Status"), html.Dd(status_pill(report["status"]))]),
                html.Div(className="detail-row", children=[html.Dt("Logged"), html.Dd(utc_span(report["created_at"]))]),
                html.Div(className="detail-row", children=[html.Dt("Logged by"), html.Dd(report["logged_by"])]),
            ],
        ),
        html.Div(report["notes"] or "No call notes recorded.", className="muted tiny mt-3"),
    ]


def selector_card(view: dict) -> html.Div:
    body = [
        html.Div(
            className="field",
            children=[
                html.Label("Report to dispatch", htmlFor="dispatch-report-select"),
                dcc.Dropdown(
                    id="dispatch-report-select",
                    options=view["options"],
                    value=view["value"],
                    clearable=False,
                    searchable=True,
                    placeholder="Pick a swarm report",
                ),
            ],
        ),
        html.Div(id="dispatch-summary", className="mt-4", children=report_summary(view)),
    ]
    return card(
        "Swarm calls",
        body,
        subtitle=f"{view['pending_count']} waiting · {view['assigned_count']} already assigned",
        icon="◎",
    )


def _empty_slot(slot: int) -> html.Button:
    """Keeps every confirm slot present so the callbacks always have a target."""
    return html.Button(
        "Confirm dispatch",
        id=f"candidate-confirm-{slot}",
        n_clicks=0,
        type="button",
        disabled=True,
        className="btn btn-sm",
        style={"display": "none"},
    )


def candidates_body(view: dict) -> list:
    ranking = view["ranking"] or {}
    if view["error"]:
        return [empty_state("Dispatch board unavailable", DISPATCH_ERROR_COPY)] + [
            _empty_slot(slot) for slot in range(1, MAX_CANDIDATE_SLOTS + 1)
        ]

    if ranking.get("status") == "assigned":
        dispatch = ranking.get("dispatch") or {}
        return [
            html.Div(
                className="notice--info notice",
                children=[
                    html.Strong(f"Already assigned to {dispatch.get('volunteer_name', 'a collector')}"),
                    html.Div(
                        [
                            "since ",
                            format_utc(dispatch.get("created_at")),
                            f" · {dispatch.get('distance_km', 0):.1f} km away · dispatch #{dispatch.get('id')}",
                        ]
                    ),
                    html.Div(
                        "Use Reassign in the actions panel to change the collector.",
                        className="tiny",
                    ),
                ],
            ),
        ] + [_empty_slot(slot) for slot in range(1, MAX_CANDIDATE_SLOTS + 1)]

    candidates = ranking.get("candidates") or []
    if not candidates:
        return [
            empty_state(
                "No eligible collectors",
                ranking.get("message") or ranking_service.NO_COVERAGE_MESSAGE,
            ),
        ] + [_empty_slot(slot) for slot in range(1, MAX_CANDIDATE_SLOTS + 1)]

    rows = []
    slots: dict[str, int] = {}
    for index, candidate in enumerate(candidates[:MAX_CANDIDATE_SLOTS], start=1):
        rows.append(
            html.Div(
                className="candidate",
                children=[
                    html.Div(str(index), className="rank-badge"),
                    html.Div(
                        className="stack-sm",
                        children=[
                            html.Div(candidate["name"], className="candidate-name"),
                            html.Div(
                                f"{candidate['skills']} · coverage {candidate['coverage_radius_km']:.0f} km",
                                className="candidate-meta",
                            ),
                            html.Div(candidate["phone"], className="candidate-meta mono"),
                        ],
                    ),
                    html.Div(
                        className="row",
                        children=[
                            html.Span(f"{candidate['distance_km']:.1f} km", className="distance-chip"),
                            html.Button(
                                "Confirm dispatch",
                                id=f"candidate-confirm-{index}",
                                n_clicks=0,
                                type="button",
                                className="btn btn-sm btn-primary",
                            ),
                        ],
                    ),
                ],
            )
        )
        slots[str(index)] = candidate["volunteer_id"]

    for slot in range(len(rows) + 1, MAX_CANDIDATE_SLOTS + 1):
        rows.append(_empty_slot(slot))
    view["slots"] = slots
    return rows


def candidates_card(view: dict) -> html.Div:
    """The ranked list; candidate_body() also records the slot -> collector map."""
    return card(
        "Ranked collectors",
        loading(html.Div(id="dispatch-candidates", children=candidates_body(view))),
        subtitle="Available collectors whose coverage radius reaches this site, nearest first",
        icon="◆",
        head_extra=html.Button(
            "Volunteer roster",
            id={"type": "goto-tab", "index": "volunteers"},
            n_clicks=0,
            type="button",
            className="btn btn-sm btn-ghost",
        ),
    )


def assigned_notice(view: dict) -> list:
    """The 'already assigned' notice body, rendered inside its group wrapper."""
    ranking = view["ranking"] or {}
    dispatch = ranking.get("dispatch") or {}
    report = ranking.get("report") or {}
    return [
        html.Strong(f"Already assigned to {dispatch.get('volunteer_name', 'a collector')}"),
        html.Div(
            [
                "since ",
                format_utc(dispatch.get("created_at")),
                f" · {dispatch.get('distance_km', 0):.1f} km from {report.get('site_name', 'the site')}",
                f" · dispatch #{dispatch.get('id')}",
            ]
        ),
    ]


def actions_card(view: dict) -> html.Div:
    ranking = view["ranking"] or {}
    dispatch = ranking.get("dispatch") or {}
    intent = view.get("intent") or {}
    mode = view.get("mode")

    assigned = bool(dispatch) and ranking.get("status") == "assigned"
    show_confirm = bool(intent) and (mode == "reassign" or not assigned)
    show_assigned = assigned and not show_confirm
    show_idle = not show_confirm and not show_assigned and not view["error"]

    assigned_children = [
        html.Div(id="dispatch-assigned-notice", children=assigned_notice(view)),
        html.Div(
            className="row mt-3",
            children=[
                html.Button(
                    "Reassign",
                    id="dispatch-reassign-btn",
                    n_clicks=0,
                    type="button",
                    className="btn btn-sm",
                ),
                html.Button(
                    "Decline",
                    id="dispatch-decline-btn",
                    n_clicks=0,
                    type="button",
                    className="btn btn-sm",
                    title="The collector cannot attend",
                ),
                html.Button(
                    "Cancel dispatch",
                    id="dispatch-cancel-dispatch-btn",
                    n_clicks=0,
                    type="button",
                    className="btn btn-sm btn-danger",
                ),
            ],
        ),
        html.Div(
            "Declining or cancelling returns the report to the pending list so it can be re-dispatched.",
            className="muted tiny mt-3",
        ),
    ]

    confirm_children = [
        html.Div(id="dispatch-confirm-summary", className="stack-sm"),
        html.Div(
            className="row mt-3",
            children=[
                html.Button(
                    "Confirm dispatch",
                    id="dispatch-confirm-btn",
                    n_clicks=0,
                    type="button",
                    className="btn btn-primary",
                    **{"data-enter-submit": "dispatch-confirm-btn"},
                ),
                html.Button(
                    "Back",
                    id="dispatch-intent-cancel-btn",
                    n_clicks=0,
                    type="button",
                    className="btn btn-ghost",
                ),
            ],
        ),
    ]

    idle_children = [
        empty_state(
            "Nothing to confirm yet",
            "Pick a report on the left, then choose a collector from the ranked list.",
        )
    ]

    return card(
        "Dispatch actions",
        [
            html.Div(
                id="dispatch-active-group",
                style={"display": "block"} if show_assigned else {"display": "none"},
                children=assigned_children,
            ),
            html.Div(
                id="dispatch-confirm-group",
                style={"display": "block"} if show_confirm else {"display": "none"},
                children=confirm_children,
            ),
            html.Div(
                id="dispatch-idle-group",
                style={"display": "block"} if show_idle else {"display": "none"},
                children=idle_children,
            ),
            feedback_panel("dispatch-feedback", tone="toast"),
        ],
        subtitle="Confirm, decline, cancel or reassign — one active dispatch per report",
        icon="⚑",
    )


def confirm_summary(view: dict) -> list:
    intent = view.get("intent") or {}
    ranking = view.get("ranking") or {}
    report = ranking.get("report") or {}
    candidates = {c["volunteer_id"]: c for c in (ranking.get("candidates") or [])}
    candidate = candidates.get(intent.get("volunteer_id"))
    mode = view.get("mode")
    if not candidate or not report:
        return [empty_state("Pick a collector", "Choose a collector from the ranked list first.")]
    action = "Reassign" if mode == "reassign" else "Confirm dispatch"
    return [
        html.Div(f"{action} to {candidate['name']}?", className="card-title"),
        html.Dl(
            className="detail-list",
            children=[
                html.Div(className="detail-row", children=[html.Dt("Report"), html.Dd(f"#{report['id']} · {report['site_name']}")]),
                html.Div(className="detail-row", children=[html.Dt("Caller"), html.Dd(report["caller_name"])]),
                html.Div(className="detail-row", children=[html.Dt("Cluster"), html.Dd(report["cluster_size_bucket"])]),
                html.Div(className="detail-row", children=[html.Dt("Collector"), html.Dd(candidate["name"])]),
                html.Div(className="detail-row", children=[html.Dt("Distance"), html.Dd(f"{candidate['distance_km']:.1f} km")]),
                html.Div(className="detail-row", children=[html.Dt("Coverage"), html.Dd(f"{candidate['coverage_radius_km']:.0f} km")]),
                html.Div(className="detail-row", children=[html.Dt("Confirmed at"), html.Dd(format_utc(view.get("now_iso")))]),
            ],
        ),
    ]


def history_table(rows: list[dict]) -> html.Div:
    if not rows:
        return empty_state(
            "No dispatch history",
            "This report has not been dispatched yet.",
        )
    return html.Div(
        className="table-wrap",
        children=html.Table(
            className="data-table",
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Dispatch"),
                            html.Th("Collector"),
                            html.Th("State"),
                            html.Th("Distance"),
                            html.Th("Raised"),
                            html.Th("Closed"),
                            html.Th("Reason"),
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(f"#{row['id']}", className="mono"),
                                html.Td(row["volunteer_name"], className="cell-strong"),
                                html.Td(html.Span(row["state"], className="pill pill-assigned")),
                                html.Td(f"{row['distance_km']:.1f} km"),
                                html.Td(utc_span(row["created_at"]), className="cell-dim tiny"),
                                html.Td(utc_span(row["closed_at"]), className="cell-dim tiny"),
                                html.Td(row["close_reason"] or "—", className="cell-dim"),
                            ]
                        )
                        for row in rows
                    ]
                ),
            ],
        ),
    )


def panel(view: dict) -> html.Div:
    return html.Div(
        className="stack",
        children=[
            html.Div(id="dispatch-kpis", children=kpi_strip(view)),
            error_panel("dispatch-error", "dispatch-error-text", "dispatch-retry"),
            html.Div(
                className="grid",
                children=[
                    html.Div(className="col-4", children=[selector_card(view)]),
                    html.Div(className="col-8", children=[candidates_card(view)]),
                    html.Div(className="col-4", children=[actions_card(view)]),
                    html.Div(
                        className="col-8",
                        children=[
                            card(
                                "Dispatch history",
                                loading(
                                    html.Div(id="dispatch-history", children=history_table(view["history"]))
                                ),
                                subtitle="Every attempt on this report, including closed and reassigned rows",
                                icon="▤",
                            )
                        ],
                    ),
                ],
            ),
            dcc.Store(id="dispatch-intent", data=view.get("intent")),
            dcc.Store(id="dispatch-mode", data=view.get("mode")),
            dcc.Store(id="candidate-slots", data=view.get("slots") or {}),
        ],
    )
