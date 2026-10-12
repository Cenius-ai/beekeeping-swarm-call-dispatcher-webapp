"""Reports tab: intake, canonical status chips, triage table, swarm map and the
shared detail panel."""

from __future__ import annotations

import logging

from dash import dcc, html
from services.errors import ServiceError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from data import sites as site_catalogue
from db import REPORT_STATUSES, STATUS_COLORS, STATUS_LABELS
from services import reports as report_service
from ui.components import (
    CLUSTER_SIZE_BUCKETS,
    URGENCIES,
    URGENCY_CHOICES,
    card,
    chart,
    empty_state,
    error_panel,
    feedback_panel,
    field,
    loading,
    native_select,
    stat,
    status_legend,
    status_pill,
    text_area,
    text_input,
    urgency_pill,
    utc_span,
)
from ui.theme import STATUS_COLORS as CHART_STATUS_COLORS
from ui.theme import base_layout

logger = logging.getLogger(__name__)

EMPTY_TABLE_COPY = "No reports match these filters - clear a filter or log a new report."
EMPTY_MAP_COPY = "No swarm reports match these filters yet."
REPORTS_ERROR_COPY = "We could not load the swarm reports just now. Try again in a moment."

STATUS_FILTERS = ("all",) + REPORT_STATUSES

MAP_HEIGHT = 420


# --------------------------------------------------------------------------- #
# Data snapshot
# --------------------------------------------------------------------------- #
def load_view(
    db: Session,
    status: str = "all",
    urgency: str = "all",
    search: str = "",
    selected_id: int | None = None,
) -> dict:
    """Everything the Reports tab needs, including its failure branch."""
    view = {
        "status": status or "all",
        "urgency": urgency or "all",
        "search": search or "",
        "rows": [],
        "counts": {s: 0 for s in REPORT_STATUSES} | {"all": 0},
        "selected": None,
        "error": None,
    }
    try:
        view["rows"] = report_service.list_reports(db, view["status"], view["urgency"], view["search"])
        view["counts"] = report_service.status_counts(db)
        if selected_id:
            view["selected"] = next(
                (row for row in view["rows"] if row["id"] == selected_id), None
            )
            if view["selected"] is None:
                view["selected"] = report_service.serialize_report(
                    report_service.get_report(db, selected_id)
                )
    except (ServiceError, SQLAlchemyError):
        logger.exception("loading swarm reports failed")
        view["error"] = REPORTS_ERROR_COPY
    return view


# --------------------------------------------------------------------------- #
# Fragments
# --------------------------------------------------------------------------- #
def kpi_strip(counts: dict, rows: list[dict]) -> html.Div:
    open_calls = counts.get("new", 0)
    assigned = counts.get("assigned", 0)
    collected = counts.get("collected", 0)
    rehomed = counts.get("rehomed", 0)
    lost = counts.get("lost", 0)
    missing = counts.get("not_found", 0)
    total = counts.get("all", 0)
    return html.Div(
        className="kpi-strip",
        children=[
            stat("Open swarm calls", open_calls, "awaiting a collector", "warn", "◉"),
            stat("Dispatched", assigned, "collector en route", "accent", "→"),
            stat("In transit", collected, "collected, not yet hived", "info", "▣"),
            stat("Rehomed", rehomed, "settled at an apiary", "ok", "✚"),
            stat("Lost", lost, "colony gone before arrival", "danger", "✕"),
            stat("Not found", missing, f"of {total} reports this season", "muted", "◌"),
        ],
    )


def chip_row(counts: dict, active: str) -> html.Div:
    chips = []
    for status in STATUS_FILTERS:
        label = "All reports" if status == "all" else STATUS_LABELS[status]
        className = "chip chip--active" if status == active else "chip"
        chips.append(
            html.Button(
                id={"type": "status-chip", "index": status},
                n_clicks=0,
                type="button",
                className=className,
                children=[
                    html.Span(
                        className="chip-dot",
                        style={"background": STATUS_COLORS.get(status, "#9884f3")},
                        **{"aria-hidden": "true"},
                    ),
                    html.Span(label),
                    html.Span(str(counts.get(status, 0)), className="chip-count"),
                ],
            )
        )
    return html.Div(id="reports-status-chips", className="chip-row", children=chips)


def filter_bar(status: str, urgency: str, search: str) -> html.Div:
    return html.Div(
        className="row mt-3",
        children=[
            html.Div(
                className="field",
                style={"minWidth": "180px"},
                children=[
                    html.Label("Urgency", htmlFor="urgency-filter"),
                    dcc.Dropdown(
                        id="urgency-filter",
                        options=[{"label": "Any urgency", "value": "all"}]
                        + [{"label": u, "value": u} for u in URGENCIES],
                        value=urgency,
                        clearable=False,
                        searchable=False,
                    ),
                ],
            ),
            html.Div(
                className="field",
                style={"flex": "1 1 220px"},
                children=[
                    html.Label("Search caller, phone or site", htmlFor="report-search"),
                    text_input(
                        "report-search",
                        value=search,
                        placeholder="e.g. Ashworth or Blaise",
                        input_type="search",
                    ),
                ],
            ),
        ],
    )


def table(rows: list[dict], selected_id: int | None) -> html.Div:
    return html.Div(
        className="table-wrap overflow-scroll-y",
        children=[
            html.Table(
                className="data-table",
                children=[
                    html.Thead(
                        html.Tr(
                            [
                                html.Th("Created"),
                                html.Th("Caller"),
                                html.Th("Cluster size"),
                                html.Th("Status"),
                                html.Th("Urgency"),
                                html.Th("Logged by"),
                                html.Th("Assigned volunteer"),
                            ]
                        )
                    ),
                    html.Tbody(table_rows(rows, selected_id)),
                ],
            )
        ],
    )


def table_rows(rows: list[dict], selected_id: int | None):
    if not rows:
        return [
            html.Tr(
                id={"type": "report-row", "index": 0},
                n_clicks=0,
                children=[
                    html.Td(
                        colSpan=7,
                        children=[
                            empty_state("Nothing matches these filters", EMPTY_TABLE_COPY),
                        ],
                    )
                ],
            )
        ]

    body = []
    for row in rows:
        is_selected = row["id"] == selected_id
        body.append(
            html.Tr(
                id={"type": "report-row", "index": row["id"]},
                n_clicks=0,
                className="row--selected" if is_selected else "",
                children=[
                    html.Td(
                        children=[
                            html.Button(
                                [
                                    html.Div(row["caller_name"], className="cell-strong"),
                                    html.Div(utc_span(row["created_at"]), className="cell-dim tiny"),
                                ],
                                id={"type": "report-link", "index": row["id"]},
                                n_clicks=0,
                                type="button",
                                className="row-button",
                            )
                        ]
                    ),
                    html.Td(
                        children=[
                            html.Div(row["caller_phone"], className="mono"),
                            html.Div(row["site_name"], className="cell-dim tiny"),
                        ]
                    ),
                    html.Td(row["cluster_size_bucket"].split(" (")[0]),
                    html.Td(status_pill(row["status"])),
                    html.Td(urgency_pill(row["urgency"])),
                    html.Td(row["logged_by"], className="cell-dim"),
                    html.Td(
                        row["assigned_volunteer"] or "—",
                        className="cell-dim" if not row["assigned_volunteer"] else "cell-strong",
                    ),
                ],
            )
        )
    return body


def swarm_map(rows: list[dict], selected_id: int | None):
    """Scattergeo with no basemap tiles and no token — bundled world geometry."""
    figure = {
        "data": [],
        "layout": base_layout(
            height=MAP_HEIGHT,
            margin={"l": 8, "r": 8, "t": 8, "b": 8},
            geo={
                "projection": {"type": "mercator"},
                "lataxis": {"range": [51.28, 51.64]},
                "lonaxis": {"range": [-2.98, -2.38]},
                "bgcolor": "rgba(0,0,0,0)",
                "showland": True,
                "landcolor": "#16161d",
                "showocean": True,
                "oceancolor": "#0c0c11",
                "showcountries": True,
                "countrycolor": "#2d2d34",
                "showcoastlines": True,
                "coastlinecolor": "#2d2d34",
                "showlakes": False,
                "showrivers": False,
                "showframe": False,
                "resolution": 50,
            },
        ),
    }

    for status in REPORT_STATUSES:
        group = [row for row in rows if row["status"] == status]
        if not group:
            continue
        figure["data"].append(
            {
                "type": "scattergeo",
                "mode": "markers",
                "name": STATUS_LABELS[status],
                "lat": [row["lat"] for row in group],
                "lon": [row["lon"] for row in group],
                "customdata": [
                    [row["id"], row["site_name"], row["caller_name"], row["cluster_size_bucket"]]
                    for row in group
                ],
                "text": [
                    f"{row['site_name']}<br>{row['caller_name']} · {row['caller_phone']}"
                    for row in group
                ],
                "hovertemplate": "%{text}<br>Status: "
                + STATUS_LABELS[status]
                + "<br>Cluster: %{customdata[3]}<extra></extra>",
                "marker": {
                    "size": 13,
                    "color": CHART_STATUS_COLORS[status],
                    "line": {"width": 1, "color": "#0c0c11"},
                },
            }
        )

    selected = next((row for row in rows if row["id"] == selected_id), None)
    if selected is not None:
        figure["data"].append(
            {
                "type": "scattergeo",
                "mode": "markers",
                "name": "Selected",
                "showlegend": False,
                "lat": [selected["lat"]],
                "lon": [selected["lon"]],
                "text": [selected["site_name"]],
                "hovertemplate": "Selected: %{text}<extra></extra>",
                "marker": {
                    "size": 26,
                    "color": "rgba(0,0,0,0)",
                    "line": {"width": 2.5, "color": "#efeff5"},
                },
            }
        )

    return figure


def detail_panel(report: dict | None) -> html.Div:
    if report is None:
        return empty_state(
            "No report selected",
            "Pick a row in the triage table or a marker on the map to open its full record.",
        )
    rows = [
        ("Caller", report["caller_name"]),
        ("Phone", html.Span(report["caller_phone"], className="mono")),
        ("Site", report["site_name"]),
        ("Cluster size", report["cluster_size_bucket"]),
        ("Urgency", urgency_pill(report["urgency"])),
        ("Status", status_pill(report["status"])),
        ("Logged by", report["logged_by"]),
        ("Logged at", utc_span(report["created_at"])),
        (
            "Assigned volunteer",
            report["assigned_volunteer"] or "No active dispatch",
        ),
    ]
    if report["active_dispatch_since"]:
        rows.append(("Dispatched", utc_span(report["active_dispatch_since"])))
    rows.append(("Notes", report["notes"] or "No call notes recorded."))
    return html.Dl(
        className="detail-list",
        children=[
            html.Div(
                className="detail-row",
                children=[html.Dt(label), html.Dd(value)],
            )
            for label, value in rows
        ],
    )


# --------------------------------------------------------------------------- #
# Intake form
# --------------------------------------------------------------------------- #
def intake_fields(values: dict | None = None, errors: dict | None = None) -> list:
    values = values or {}
    errors = errors or {}
    return [
        field(
            "Caller name",
            text_input(
                "intake-caller-name",
                value=values.get("caller_name", ""),
                placeholder="Who reported the swarm?",
                invalid="caller_name" in errors,
                n_submit=0,
            ),
            error=errors.get("caller_name"),
            control_id="intake-caller-name",
        ),
        field(
            "Caller phone",
            text_input(
                "intake-caller-phone",
                value=values.get("caller_phone", ""),
                placeholder="07700 900123",
                input_type="tel",
                invalid="caller_phone" in errors,
                n_submit=0,
            ),
            hint="7 to 15 digits — we never send SMS from this build.",
            error=errors.get("caller_phone"),
            control_id="intake-caller-phone",
        ),
        field(
            "Urgency",
            native_select(
                "intake-urgency",
                [(urgency, urgency) for urgency in URGENCY_CHOICES],
                values.get("urgency") or URGENCY_CHOICES[0],
                aria_label="Call urgency",
            ),
            error=errors.get("urgency"),
            control_id="intake-urgency-select",
        ),
        field(
            "Cluster size",
            native_select(
                "intake-cluster",
                CLUSTER_SIZE_BUCKETS,
                values.get("cluster_size_bucket") or CLUSTER_SIZE_BUCKETS[0],
                aria_label="Cluster size bucket",
            ),
            error=errors.get("cluster_size_bucket"),
            control_id="intake-cluster-select",
            wide=True,
        ),
        field(
            "Site / location",
            native_select(
                "intake-site",
                site_catalogue.site_names(),
                values.get("site_name") or site_catalogue.site_names()[0],
                aria_label="Reported swarm site",
            ),
            hint="Named local sites — pick the closest match to the caller's description.",
            error=errors.get("site_name"),
            control_id="intake-site-select",
            wide=True,
        ),
        field(
            "Call notes",
            text_area(
                "intake-notes",
                value=values.get("notes", ""),
                placeholder="Where exactly is the cluster, and is anyone at risk?",
                invalid="notes" in errors,
            ),
            error=errors.get("notes"),
            wide=True,
        ),
    ]


def intake_card(values: dict | None = None, errors: dict | None = None) -> html.Div:
    body = [
        html.P(
            "Log the call while you have the caller on the line. The report lands at the "
            "top of the triage table as a new swarm call.",
            className="muted tiny",
        ),
        html.Div(id="intake-fields", className="form-grid", children=intake_fields(values, errors)),
        feedback_panel("intake-feedback", tone="toast"),
        html.Div(
            className="row mt-3",
            **{"data-enter-form": "intake"},
            children=[
                html.Button(
                    "Log swarm call",
                    id="intake-submit",
                    n_clicks=0,
                    type="button",
                    className="btn btn-primary",
                    **{"data-enter-submit": "intake-submit"},
                ),
            ],
        ),
    ]
    return card(
        "Log a swarm call",
        body,
        subtitle="Intake · every call is attributed to you as the logger",
        icon="✚",
    )


# --------------------------------------------------------------------------- #
# Panel assembly
# --------------------------------------------------------------------------- #
def panel(view: dict) -> html.Div:
    return html.Div(
        className="stack",
        children=[
            kpi_strip(view["counts"], view["rows"]),
            error_panel("reports-error", "reports-error-text", "reports-retry"),
            html.Div(
                className="grid",
                children=[
                    html.Div(
                        className="col-8",
                        children=[
                            card(
                                "Swarm report triage",
                                [
                                    chip_row(view["counts"], view["status"]),
                                    filter_bar(view["status"], view["urgency"], view["search"]),
                                    html.Div(
                                        className="between mt-3",
                                        children=[
                                            html.Span(
                                                id="reports-count",
                                                className="muted tiny",
                                                children=count_caption(
                                                    len(view["rows"]), view["counts"].get("all", 0)
                                                ),
                                            ),
                                            status_legend(),
                                        ],
                                    ),
                                    loading(
                                        html.Div(
                                            id="reports-table",
                                            children=table(
                                                view["rows"], (view["selected"] or {}).get("id")
                                            ),
                                        )
                                    ),
                                ],
                                subtitle="Filter by status, then open a row for the full record",
                                icon="▤",
                            )
                        ],
                    ),
                    html.Div(
                        className="col-4",
                        children=[
                            card(
                                "Report detail",
                                loading(
                                    html.Div(id="report-detail", children=detail_panel(view["selected"]))
                                ),
                                subtitle="Everything logged against the selected call",
                                icon="◎",
                            )
                        ],
                    ),
                    html.Div(
                        className="col-8",
                        children=[
                            card(
                                "Swarm map",
                                loading(
                                    chart(
                                        swarm_map(
                                            view["rows"], (view["selected"] or {}).get("id")
                                        ),
                                        "reports-map",
                                        "chart-420",
                                        # Plotly fetches its world geometry from a CDN by
                                        # default; point it at the copy we ship instead.
                                        config={"topojsonURL": "/static/geo/"},
                                    )
                                ),
                                subtitle="Marker colour follows the canonical status list",
                                icon="◆",
                            )
                        ],
                    ),
                    html.Div(
                        className="col-4",
                        children=[intake_card()],
                    ),
                ],
            ),
            dcc.Store(id="status-filter", data=view["status"]),
            dcc.Store(id="selected-report", data=(view["selected"] or {}).get("id")),
        ],
    )


def count_caption(shown: int, total: int) -> str:
    if shown == total:
        return f"Showing all {total} reports"
    return f"Showing {shown} of {total} reports"
