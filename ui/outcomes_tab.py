"""Outcomes tab: the pipeline funnel, the outcome recording form and the outcome
history tables."""

from __future__ import annotations

import logging
from datetime import date

from dash import dcc, html
from services.errors import ServiceError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from data import apiaries as apiary_catalogue
from db import OUTCOME_RESULTS
from services import dispatch as dispatch_service
from services import outcomes as outcome_service
from services import reports as report_service
from ui.components import (
    card,
    chart,
    loading,
    native_select,
    empty_state,
    error_panel,
    feedback_panel,
    field,
    stat,
    text_area,
    text_input,
    utc_span,
)
from ui.theme import (
    ACCENT,
    DESTRUCTIVE,
    INFO,
    MUTED_FOREGROUND,
    OK,
    WARN,
    axis_style,
    base_layout,
    empty_figure,
)

logger = logging.getLogger(__name__)

OUTCOMES_ERROR_COPY = "We could not load the outcome pipeline just now. Try again in a moment."
NO_OUTCOMES_COPY = "No outcomes recorded yet - record a collection to start the pipeline."
NO_REPORT_OUTCOMES_COPY = "No outcomes recorded yet."

STAGE_COLORS = {
    "new": WARN,
    "assigned": ACCENT,
    "collected": INFO,
    "rehomed": OK,
}

RESULT_LABELS = {
    "collected": "Collected — in a travel box",
    "rehomed": "Rehomed — hived at an apiary",
    "lost": "Lost — colony gone before arrival",
    "not_found": "Not found — no swarm at the site",
}


def load_view(db: Session, report_id: int | None = None) -> dict:
    view = {
        "funnel": {
            "counts": {},
            "stages": [],
            "terminal": [],
            "outcome_counts": {},
            "outcomes_total": 0,
            "reports_total": 0,
        },
        "outcome_rows": [],
        "report_options": [],
        "report_id": None,
        "report": None,
        "collector": None,
        "report_outcomes": [],
        "today": date.today().isoformat(),
        "error": None,
    }
    try:
        view["funnel"] = outcome_service.funnel(db)
        view["outcome_rows"] = outcome_service.list_outcomes(db)

        reports = report_service.list_reports(db)
        view["report_options"] = [
            {
                "label": f"#{row['id']} · {row['site_name']} · {row['status_label']} · {row['caller_name']}",
                "value": row["id"],
            }
            for row in reports
        ]
        chosen = report_id if any(option["value"] == report_id for option in view["report_options"]) else None
        if chosen is None and view["report_options"]:
            chosen = view["report_options"][0]["value"]
        view["report_id"] = chosen

        if chosen is not None:
            report = report_service.get_report(db, chosen)
            view["report"] = report_service.serialize_report(report)
            view["report_outcomes"] = outcome_service.report_outcomes(db, chosen)
            active = None
            for candidate in reversed(report.dispatches):
                if candidate.state == "confirmed":
                    active = candidate
                    break
            view["collector"] = active.volunteer.name if active and active.volunteer else None
    except (ServiceError, SQLAlchemyError):
        logger.exception("loading the outcomes tab failed")
        view["error"] = OUTCOMES_ERROR_COPY
    return view


def kpi_strip(view: dict) -> html.Div:
    funnel = view["funnel"]
    counts = funnel.get("counts", {})
    outcomes = funnel.get("outcomes_total", 0)
    rehomed = counts.get("rehomed", 0)
    closed = rehomed + counts.get("lost", 0) + counts.get("not_found", 0)
    rate = f"{(100 * rehomed / closed):.0f}%" if closed else "—"
    return html.Div(
        className="kpi-strip",
        children=[
            stat("Outcomes recorded", outcomes, "collections, losses and misses", "accent", "▣"),
            stat("Rehomed", rehomed, f"of {funnel.get('reports_total', 0)} reports", "ok", "✚"),
            stat("Lost", counts.get("lost", 0), "colony gone before arrival", "danger", "✕"),
            stat("Not found", counts.get("not_found", 0), "terminal, separate from lost", "muted", "◌"),
            stat("Rehome rate", rate, "of reports with a terminal outcome", "info", "◈"),
            stat("Still open", counts.get("new", 0) + counts.get("assigned", 0), "in the live pipeline", "warn", "◉"),
        ],
    )


def funnel_figure(funnel: dict):
    stages = funnel.get("stages") or []
    if not stages or not any(stage["count"] for stage in stages):
        return empty_figure(NO_OUTCOMES_COPY, 340)
    figure = {
        "data": [
            {
                "type": "funnel",
                "y": [stage["label"] for stage in stages],
                "x": [stage["count"] for stage in stages],
                "textinfo": "value+percent initial",
                "textfont": {"family": "Chakra Petch, sans-serif", "size": 12, "color": "#111111"},
                "marker": {
                    "color": [STAGE_COLORS[stage["status"]] for stage in stages],
                    "line": {"color": "#0c0c11", "width": 1},
                },
                "connector": {"line": {"color": "#2d2d34", "width": 1}},
                "hovertemplate": "%{y}: %{x} reports<extra></extra>",
                "showlegend": False,
            }
        ],
        "layout": base_layout(
            height=340,
            margin={"l": 110, "r": 24, "t": 8, "b": 24},
            showlegend=False,
            funnelmode="stack",
        ),
    }
    return figure


def terminal_figure(funnel: dict):
    terminal = funnel.get("terminal") or []
    if not terminal:
        return empty_figure("No terminal outcomes yet.", 340)
    colors = {"lost": DESTRUCTIVE, "not_found": MUTED_FOREGROUND}
    figure = {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "y": [row["label"] for row in terminal],
                "x": [row["count"] for row in terminal],
                "marker": {"color": [colors.get(row["status"], ACCENT) for row in terminal]},
                "text": [str(row["count"]) for row in terminal],
                "textposition": "outside",
                "textfont": {"size": 12, "color": "#efeff5"},
                "hovertemplate": "%{y}: %{x} reports<extra></extra>",
                "showlegend": False,
            }
        ],
        "layout": base_layout(
            height=340,
            margin={"l": 90, "r": 32, "t": 8, "b": 30},
            showlegend=False,
            bargap=0.5,
        ),
    }
    figure["layout"]["xaxis"] = axis_style(title={"text": "reports", "font": {"size": 11}})
    figure["layout"]["yaxis"] = axis_style(showgrid=False, automargin=True)
    return figure


def outcome_fields(
    values: dict | None,
    errors: dict | None,
    report_options: list[dict],
    report_id: int | None,
    collector: str | None,
) -> list:
    values = values or {}
    errors = errors or {}
    return [
        field(
            "Report",
            dcc.Dropdown(
                id="outcome-report",
                options=report_options,
                value=report_id,
                clearable=False,
                searchable=True,
                placeholder="Pick the swarm report",
            ),
            error=errors.get("report_id"),
            control_id="outcome-report",
            wide=True,
        ),
        field(
            "Collector on the call",
            html.Div(
                collector or "No active dispatch — record the outcome against the report anyway.",
                id="outcome-collector",
                className="input",
                style={"display": "flex", "alignItems": "center"},
            ),
            hint="Taken from the report's active dispatch; the coordinator can never change it here.",
            wide=True,
        ),
        field(
            "Result",
            native_select(
                "outcome-result",
                [(RESULT_LABELS[result], result) for result in OUTCOME_RESULTS],
                values.get("result") or OUTCOME_RESULTS[0],
                aria_label="Outcome result",
            ),
            error=errors.get("result"),
            control_id="outcome-result-select",
            wide=True,
        ),
        field(
            "Collection date",
            text_input(
                "outcome-collected-on",
                value=values.get("collected_on") or "",
                input_type="date",
                invalid="collected_on" in errors,
            ),
            hint="Defaults to today; stored as UTC.",
            error=errors.get("collected_on"),
            control_id="outcome-collected-on",
        ),
        field(
            "Actual cluster size (bees)",
            text_input(
                "outcome-cluster-size",
                value=str(values.get("actual_cluster_size", "") or ""),
                placeholder="e.g. 6500",
                input_type="number",
                invalid="actual_cluster_size" in errors,
                min=0,
                step=100,
            ),
            error=errors.get("actual_cluster_size"),
            control_id="outcome-cluster-size",
        ),
        field(
            "Hive / box used",
            text_input(
                "outcome-hive",
                value=values.get("hive_box", ""),
                placeholder="e.g. Nuc box 3 (5-frame)",
                invalid="hive_box" in errors,
                n_submit=0,
            ),
            error=errors.get("hive_box"),
            control_id="outcome-hive",
            wide=True,
        ),
        field(
            "Rehoming destination",
            native_select(
                "outcome-destination",
                [("Not rehomed yet", "")]
                + [
                    (f"{apiary['name']} · {apiary['kind']}", apiary["name"])
                    for apiary in apiary_catalogue.APIARIES
                ],
                values.get("rehomed_to") or "",
                aria_label="Rehoming destination",
            ),
            hint="Required when the result is 'Rehomed'.",
            error=errors.get("rehomed_to"),
            control_id="outcome-destination-select",
            wide=True,
        ),
        field(
            "Outcome notes",
            text_area(
                "outcome-notes",
                value=values.get("notes", ""),
                placeholder="Queen present? Any damage to the structure?",
                invalid="notes" in errors,
            ),
            error=errors.get("notes"),
            wide=True,
        ),
    ]


def outcome_form_card(view: dict, values: dict | None = None, errors: dict | None = None) -> html.Div:
    body = [
        html.Div(
            id="outcome-fields",
            className="form-grid form-grid--single",
            children=outcome_fields(values, errors, view["report_options"], view["report_id"], view["collector"]),
        ),
        feedback_panel("outcome-feedback", tone="toast"),
        html.Div(
            className="row mt-3",
            **{"data-enter-form": "outcome"},
            children=html.Button(
                "Record outcome",
                id="outcome-submit",
                n_clicks=0,
                type="button",
                className="btn btn-primary",
                **{"data-enter-submit": "outcome-submit"},
            ),
        ),
    ]
    return card(
        "Record an outcome",
        body,
        subtitle="Moves the report, the chip, the marker colour and the funnel together",
        icon="✚",
    )


def report_history_table(rows: list[dict]) -> html.Div:
    if not rows:
        return empty_state("No outcome history for this report", NO_REPORT_OUTCOMES_COPY)
    return html.Div(
        className="table-wrap",
        children=html.Table(
            className="data-table",
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Recorded"),
                            html.Th("Result"),
                            html.Th("Collector"),
                            html.Th("Cluster"),
                            html.Th("Hive / box"),
                            html.Th("Destination"),
                            html.Th("Notes"),
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(utc_span(row["recorded_at"]), className="cell-dim tiny"),
                                html.Td(html.Span(row["result_label"], className="pill pill-assigned")),
                                html.Td(row["collector"]),
                                html.Td(str(row["actual_cluster_size"]) if row["actual_cluster_size"] is not None else "—"),
                                html.Td(row["hive_box"] or "—", className="cell-dim"),
                                html.Td(row["rehomed_to"] or "—", className="cell-dim"),
                                html.Td(row["notes"] or "—", className="cell-dim"),
                            ]
                        )
                        for row in rows
                    ]
                ),
            ],
        ),
    )


def season_history_table(rows: list[dict]) -> html.Div:
    if not rows:
        return empty_state("No outcomes recorded yet", NO_OUTCOMES_COPY)
    return html.Div(
        className="table-wrap overflow-scroll-y",
        children=html.Table(
            className="data-table",
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Recorded"),
                            html.Th("Report"),
                            html.Th("Caller"),
                            html.Th("Result"),
                            html.Th("Collector"),
                            html.Th("Destination"),
                            html.Th("Recorded by"),
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(utc_span(row["recorded_at"]), className="cell-dim tiny"),
                                html.Td(f"#{row['report_id']} · {row['report_site']}"),
                                html.Td(row["report_caller"], className="cell-dim"),
                                html.Td(html.Span(row["result_label"], className="pill pill-rehomed")),
                                html.Td(row["collector"]),
                                html.Td(row["rehomed_to"] or "—", className="cell-dim"),
                                html.Td(row["recorded_by"], className="cell-dim"),
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
            html.Div(id="outcomes-kpis", children=kpi_strip(view)),
            error_panel("outcomes-error", "outcomes-error-text", "outcomes-retry"),
            html.Div(
                className="grid",
                children=[
                    html.Div(
                        className="col-7",
                        children=[
                            card(
                                "Pipeline funnel",
                                loading(
                                    chart(funnel_figure(view["funnel"]), "outcome-funnel", "chart-340")
                                ),
                                subtitle="new → assigned → collected → rehomed",
                                icon="◈",
                            )
                        ],
                    ),
                    html.Div(
                        className="col-5",
                        children=[
                            card(
                                "Terminal buckets",
                                loading(
                                    chart(terminal_figure(view["funnel"]), "outcome-buckets", "chart-340")
                                ),
                                subtitle="Lost and not found stay separate from the funnel",
                                icon="◌",
                            )
                        ],
                    ),
                    html.Div(className="col-5", children=[outcome_form_card(view)]),
                    html.Div(
                        className="col-7",
                        children=[
                            card(
                                "Outcome history for the selected report",
                                loading(
                                    html.Div(
                                        id="report-outcome-history",
                                        children=report_history_table(view["report_outcomes"]),
                                    )
                                ),
                                subtitle="Every outcome recorded against the report chosen on the left",
                                icon="▤",
                            )
                        ],
                    ),
                    html.Div(
                        className="col-12",
                        children=[
                            card(
                                "Season outcome log",
                                loading(
                                    html.Div(
                                        id="outcome-history",
                                        children=season_history_table(view["outcome_rows"]),
                                    )
                                ),
                                subtitle=f"{view['funnel'].get('outcomes_total', 0)} outcomes recorded this season",
                                icon="☰",
                            )
                        ],
                    ),
                ],
            ),
        ],
    )
