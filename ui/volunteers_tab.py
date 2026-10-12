"""Volunteers tab: the collector roster, availability toggling, the roster form
and a coverage chart."""

from __future__ import annotations

import logging

from dash import dcc, html
from services.errors import ServiceError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from data import sites as site_catalogue
from services import volunteers as volunteer_service
from services.geo import haversine_km
from ui.components import (
    card,
    loading,
    chart,
    empty_state,
    error_panel,
    feedback_panel,
    field,
    radio_group,
    skeleton,
    stat,
    text_input,
    utc_span,
)
from ui.theme import ACCENT, MUTED_FOREGROUND, OK, axis_style, base_layout

logger = logging.getLogger(__name__)

EMPTY_ROSTER_COPY = "No volunteers yet - add your first collector before dispatching."
ROSTER_ERROR_COPY = "We could not read the collector roster just now. Try again in a moment."


def load_view(db: Session, availability: str = "all") -> dict:
    view = {"availability": availability or "all", "rows": [], "error": None}
    try:
        view["rows"] = volunteer_service.list_volunteers(db, view["availability"])
    except (ServiceError, SQLAlchemyError):
        logger.exception("loading the volunteer roster failed")
        view["error"] = ROSTER_ERROR_COPY
    return view


def summary(rows: list[dict]) -> dict:
    available = [row for row in rows if row["is_available"]]
    radii = [row["coverage_radius_km"] for row in rows]
    return {
        "total": len(rows),
        "available": len(available),
        "unavailable": len(rows) - len(available),
        "average_radius": round(sum(radii) / len(radii), 1) if radii else 0.0,
        "largest_radius": max(radii) if radii else 0.0,
    }


def kpi_strip(view: dict) -> html.Div:
    stats = summary(view["rows"])
    return html.Div(
        className="kpi-strip",
        children=[
            stat("Collectors on the roster", stats["total"], "across the service area", "accent", "☰"),
            stat("Available now", stats["available"], "eligible for dispatch", "ok", "◉"),
            stat("Unavailable", stats["unavailable"], "on a break or off-rota", "muted", "◌"),
            stat("Mean coverage", f"{stats['average_radius']:.1f} km", "per collector", "info", "◈"),
            stat("Widest coverage", f"{stats['largest_radius']:.0f} km", "largest radius offered", "warn", "◆"),
            stat("Service area", f"{int(site_catalogue.SERVICE_RADIUS_KM)} km", "around Bristol", "", "◎"),
        ],
    )


def roster_table(rows: list[dict], error: str | None = None) -> html.Div:
    if error:
        return skeleton(5)
    if not rows:
        return html.Div(
            className="table-wrap",
            children=html.Table(
                className="data-table",
                children=[
                    html.Thead(
                        html.Tr(
                            [
                                html.Th("Collector"),
                                html.Th("Phone"),
                                html.Th("Home area"),
                                html.Th("Coverage"),
                                html.Th("Skills"),
                                html.Th("Available"),
                                html.Th("Updated"),
                            ]
                        )
                    ),
                    html.Tbody(
                        html.Tr(
                            id={"type": "volunteer-row", "index": 0},
                            children=[
                                html.Td(
                                    colSpan=7,
                                    children=[
                                        empty_state("Roster is empty", EMPTY_ROSTER_COPY),
                                        html.Div(
                                            className="row row--end",
                                            style={"display": "none"},
                                            children=html.Button(
                                                "toggle",
                                                id={"type": "vol-toggle", "index": 0},
                                                n_clicks=0,
                                                type="button",
                                                className="btn btn-sm",
                                            ),
                                        ),
                                    ],
                                )
                            ],
                        )
                    ),
                ],
            ),
        )

    body = []
    for row in rows:
        available = row["is_available"]
        body.append(
            html.Tr(
                children=[
                    html.Td(row["name"], className="cell-strong"),
                    html.Td(row["phone"], className="mono"),
                    html.Td(f"{row['lat']:.3f}, {row['lon']:.3f}", className="cell-dim mono"),
                    html.Td(f"{row['coverage_radius_km']:.0f} km"),
                    html.Td(row["skills"] or "General swarm collection", className="cell-dim"),
                    html.Td(
                        html.Button(
                            id={"type": "vol-toggle", "index": row["id"]},
                            n_clicks=0,
                            type="button",
                            className=f"toggle{' toggle--on' if available else ''}",
                            title=(
                                f"Mark {row['name']} unavailable"
                                if available
                                else f"Mark {row['name']} available"
                            ),
                            children=[
                                html.Span(
                                    className="toggle-track",
                                    **{"aria-hidden": "true"},
                                    children=html.Span(className="toggle-knob"),
                                ),
                                html.Span("Available" if available else "Unavailable"),
                            ],
                        )
                    ),
                    html.Td(utc_span(row["updated_at"]), className="cell-dim tiny"),
                ]
            )
        )
    return html.Div(
        className="table-wrap overflow-scroll-y",
        children=html.Table(
            className="data-table",
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Collector"),
                            html.Th("Phone"),
                            html.Th("Home area"),
                            html.Th("Coverage"),
                            html.Th("Skills"),
                            html.Th("Available"),
                            html.Th("Updated"),
                        ]
                    )
                ),
                html.Tbody(body),
            ],
        ),
    )


def coverage_figure(rows: list[dict]):
    if not rows:
        from ui.theme import empty_figure

        return empty_figure("No collectors yet - add your first collector to see coverage.", 300)

    ordered = sorted(rows, key=lambda row: row["coverage_radius_km"])
    figure = {
        "data": [
            {
                "type": "bar",
                "orientation": "h",
                "y": [row["name"] for row in ordered],
                "x": [row["coverage_radius_km"] for row in ordered],
                "marker": {
                    "color": [ACCENT if row["is_available"] else MUTED_FOREGROUND for row in ordered],
                    "line": {"width": 0},
                },
                "text": [f"{row['coverage_radius_km']:.0f} km" for row in ordered],
                "textposition": "outside",
                "textfont": {"size": 11, "color": MUTED_FOREGROUND},
                "hovertemplate": "%{y}: %{x:.0f} km coverage<extra></extra>",
                "showlegend": False,
            }
        ],
        "layout": base_layout(
            height=300,
            margin={"l": 150, "r": 48, "t": 8, "b": 30},
            showlegend=False,
            bargap=0.35,
        ),
    }
    figure["layout"]["xaxis"] = axis_style(title={"text": "coverage radius (km)", "font": {"size": 11}})
    figure["layout"]["yaxis"] = axis_style(showgrid=False, automargin=True)
    return figure


def average_distance_label(rows: list[dict]) -> str:
    if not rows:
        return "no collectors"
    distances = [
        haversine_km(row["lat"], row["lon"], site_catalogue.SERVICE_CENTRE["lat"], site_catalogue.SERVICE_CENTRE["lon"])
        for row in rows
    ]
    return f"mean {sum(distances) / len(distances):.1f} km from the depot"


def add_volunteer_fields(values: dict | None = None, errors: dict | None = None) -> list:
    values = values or {}
    errors = errors or {}
    return [
        field(
            "Collector name",
            text_input(
                "vol-add-name",
                value=values.get("name", ""),
                placeholder="e.g. Priya Raman",
                invalid="name" in errors,
                n_submit=0,
            ),
            error=errors.get("name"),
            control_id="vol-add-name",
        ),
        field(
            "Phone",
            text_input(
                "vol-add-phone",
                value=values.get("phone", ""),
                placeholder="07700 900123",
                input_type="tel",
                invalid="phone" in errors,
                n_submit=0,
            ),
            error=errors.get("phone"),
            control_id="vol-add-phone",
        ),
        field(
            "Home location",
            dcc.Dropdown(
                id="vol-add-home",
                options=[{"label": f"{site['name']} · {site['area']}", "value": site["name"]} for site in site_catalogue.SITES],
                value=values.get("home") or site_catalogue.SITES[0]["name"],
                clearable=False,
                searchable=True,
            ),
            hint="Coordinates come from the site list, so the roster stays consistent.",
            error=errors.get("home"),
            control_id="vol-add-home",
            wide=True,
        ),
        field(
            "Coverage radius (km)",
            text_input(
                "vol-add-radius",
                value=str(values.get("coverage_radius_km", "") or ""),
                placeholder="1 to 50",
                input_type="number",
                invalid="coverage_radius_km" in errors,
                min=1,
                max=50,
                step=1,
            ),
            hint="Between 1 and 50 km — the dispatcher only offers this collector inside it.",
            error=errors.get("coverage_radius_km"),
            control_id="vol-add-radius",
        ),
        field(
            "Skills",
            text_input(
                "vol-add-skills",
                value=values.get("skills", ""),
                placeholder="cut-outs, ladders, bee-vac",
                invalid="skills" in errors,
                n_submit=0,
            ),
            hint="Comma-separated; shown on the ranked candidate list.",
            error=errors.get("skills"),
            control_id="vol-add-skills",
        ),
    ]


def add_volunteer_card(values: dict | None = None, errors: dict | None = None) -> html.Div:
    body = [
        html.Div(id="vol-add-fields", className="form-grid", children=add_volunteer_fields(values, errors)),
        feedback_panel("volunteer-feedback", tone="toast"),
        html.Div(
            className="row mt-3",
            **{"data-enter-form": "volunteer"},
            children=html.Button(
                "Add collector",
                id="vol-add-submit",
                n_clicks=0,
                type="button",
                className="btn btn-primary",
                **{"data-enter-submit": "vol-add-submit"},
            ),
        ),
    ]
    return card(
        "Add a collector",
        body,
        subtitle="New collectors are available immediately",
        icon="✚",
    )


def panel(view: dict) -> html.Div:
    stats = summary(view["rows"])
    return html.Div(
        className="stack",
        children=[
            html.Div(id="volunteers-kpis", children=kpi_strip(view)),
            error_panel("volunteer-error", "volunteer-error-text", "volunteer-retry"),
            html.Div(
                className="grid",
                children=[
                    html.Div(
                        className="col-8",
                        children=[
                            card(
                                "Collector roster",
                                [
                                    html.Div(
                                        className="row",
                                        children=[
                                            html.Div(
                                                className="field",
                                                style={"minWidth": "190px"},
                                                children=[
                                                    html.Label("Availability", htmlFor="vol-availability-filter"),
                                                    dcc.Dropdown(
                                                        id="vol-availability-filter",
                                                        options=[
                                                            {"label": "Everyone", "value": "all"},
                                                            {"label": "Available only", "value": "available"},
                                                            {"label": "Unavailable only", "value": "unavailable"},
                                                        ],
                                                        value=view["availability"],
                                                        clearable=False,
                                                        searchable=False,
                                                    ),
                                                ],
                                            ),
                                            html.Div(
                                                className="stat",
                                                style={"flex": "1 1 220px"},
                                                children=[
                                                    html.Div("Dispatch-ready", className="stat-label"),
                                                    html.Div(str(stats["available"]), className="stat-value"),
                                                    html.Div(average_distance_label(view["rows"]), className="stat-foot"),
                                                ],
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="mt-3",
                                        children=loading(
                                            html.Div(
                                                id="volunteer-rows",
                                                children=roster_table(view["rows"], view["error"]),
                                            )
                                        ),
                                    ),
                                ],
                                subtitle="Toggle availability — the ranking reads it immediately",
                                icon="☰",
                            )
                        ],
                    ),
                    html.Div(className="col-4", children=[add_volunteer_card()]),
                    html.Div(
                        className="col-12",
                        children=[
                            card(
                                "Coverage radius by collector",
                                loading(
                                    chart(
                                        coverage_figure(view["rows"]), "vol-coverage-graph", "chart-280"
                                    )
                                ),
                                subtitle="Accent bars are available now; grey bars are off-rota",
                                icon="◈",
                            )
                        ],
                    ),
                ],
            ),
        ],
    )
