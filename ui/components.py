"""Presentational building blocks shared by every tab.

Everything here is a pure function of its arguments, so the same builder renders
the first server-side paint inside ``app.layout`` and the refreshed content sent
back from a callback.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dash import dcc, html

from db import STATUS_COLORS, STATUS_LABELS

CLUSTER_SIZE_BUCKETS = (
    "Small (fist-sized, <2,000 bees)",
    "Medium (football-sized, 2,000-8,000 bees)",
    "Large (basketball-sized, 8,000-20,000 bees)",
    "Very large (more than 20,000 bees)",
)

#: Display order for pickers: the common case first so the default selection is
#: also the first option.
URGENCY_CHOICES = ("Normal", "High", "Emergency", "Low")

URGENCIES = URGENCY_CHOICES

SKILL_HINT = "e.g. cut-outs, ladders, bee-vac"


def format_utc(iso: str | None) -> str:
    """Readable UTC fallback; the browser rewrites it to local time."""
    if not iso:
        return "—"
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def utc_span(iso: str | None, className: str = "") -> html.Span:
    """Timestamp that local-time.js rewrites in the viewer's timezone."""
    return html.Span(
        format_utc(iso),
        className=className or "nowrap",
        title=iso or "",
        **{"data-utc": iso or ""},
    )


def status_pill(status: str) -> html.Span:
    return html.Span(
        STATUS_LABELS.get(status, status),
        className=f"pill pill-{status}",
    )


def urgency_pill(urgency: str) -> html.Span:
    return html.Span(
        urgency,
        className=f"pill pill-urgency-{(urgency or 'normal').lower()}",
    )


def card(
    title: str | None,
    body,
    subtitle: str | None = None,
    icon: str | None = None,
    head_extra=None,
    className: str = "",
    flush: bool = False,
) -> html.Div:
    """Elevation tier 2 surface with the signature margin-hung icon."""
    head = None
    if title:
        head = html.Div(
            className="card-head",
            children=[
                html.Div(
                    className="stack-sm",
                    children=[
                        html.Div(
                            className="card-title",
                            style={"position": "relative"},
                            children=[
                                html.Span(icon, className="seam-icon", **{"aria-hidden": "true"})
                                if icon
                                else None,
                                html.Span(title),
                            ],
                        ),
                        html.Div(subtitle, className="card-sub") if subtitle else None,
                    ],
                ),
                html.Div(head_extra, className="row") if head_extra is not None else None,
            ],
        )
    body_class = "card-body card-body--flush" if flush else "card-body"
    return html.Div(
        className=f"card {className}".strip(),
        children=[head, html.Div(body, className=body_class)],
    )


def stat(label: str, value, foot: str | None = None, tone: str = "", icon: str | None = None):
    return html.Div(
        className=f"stat {('stat--' + tone) if tone else ''}".strip(),
        children=[
            html.Span(icon, className="seam-icon", **{"aria-hidden": "true"}) if icon else None,
            html.Div(label, className="stat-label"),
            html.Div(str(value), className="stat-value"),
            html.Div(foot, className="stat-foot") if foot else None,
        ],
    )


def empty_state(title: str, message: str = "") -> html.Div:
    return html.Div(
        className="empty",
        children=[html.Strong(title), html.Div(message) if message else None],
    )


def error_panel(panel_id: str, text_id: str, retry_id: str | None = None) -> html.Div:
    """Hidden-by-default banner; a callback flips its ``style``."""
    children = [html.Span(id=text_id, children="")]
    if retry_id:
        children.append(
            html.Button(
                "Retry",
                id=retry_id,
                n_clicks=0,
                type="button",
                className="btn btn-sm btn-danger",
            )
        )
    return html.Div(
        id=panel_id,
        className="error-banner",
        style={"display": "none"},
        role="alert",
        children=children,
    )


def feedback_panel(panel_id: str, message="", tone: str = "toast") -> html.Div:
    return html.Div(
        id=panel_id,
        className=tone,
        role="status",
        **{"aria-live": "polite"},
        style={"display": "block"} if message else {"display": "none"},
        children=message,
    )


def field(
    label: str,
    control,
    hint: str | None = None,
    error: str | None = None,
    wide: bool = False,
    control_id: str | None = None,
) -> html.Div:
    """One labelled form field with its message slot inside the same region."""
    return html.Div(
        className=f"field{' field--wide' if wide else ''}",
        **{"aria-invalid": "true"} if error else {},
        children=[
            html.Label(label, htmlFor=control_id) if control_id else html.Label(label),
            control,
            html.Div(hint, className="field-hint") if hint and not error else None,
            html.Div(error, className="field-error", role="alert") if error else None,
        ],
    )


def text_input(control_id: str, value: str = "", placeholder: str = "", input_type: str = "text",
               invalid: bool = False, **extra):
    return dcc.Input(
        id=control_id,
        type=input_type,
        value=value or "",
        placeholder=placeholder,
        className=f"input{' is-invalid' if invalid else ''}",
        debounce=False,
        **extra,
    )


def text_area(control_id: str, value: str = "", placeholder: str = "", invalid: bool = False):
    return dcc.Textarea(
        id=control_id,
        value=value or "",
        placeholder=placeholder,
        className=f"textarea{' is-invalid' if invalid else ''}",
    )


def normalise_options(options) -> list[dict]:
    """Accept strings, ``(label, value)`` pairs or ``{label, value}`` dicts."""
    normalised = []
    for option in options:
        if isinstance(option, dict):
            normalised.append({"label": option["label"], "value": option["value"]})
        elif isinstance(option, (tuple, list)):
            normalised.append({"label": option[0], "value": option[1]})
        else:
            normalised.append({"label": option, "value": option})
    return normalised


def native_select(field_id: str, options, value: str | None = None, aria_label: str = "",
                  className: str = "") -> html.Div:
    """A real ``<select>`` with real option values.

    ``static/app-behaviour.js`` mirrors the chosen option into the hidden Dash
    input that carries the field's id, so callbacks read a single State value
    while the browser gets a control it can drive natively.
    """
    normalised = normalise_options(options)
    current = value if value is not None else ""
    return html.Div(
        className=f"native-select {className}".strip(),
        **{"data-select-wrap": field_id},
        children=[
            html.Select(
                id=f"{field_id}-select",
                name=field_id,
                className="select",
                **{"aria-label": aria_label} if aria_label else {},
                **{"data-select-sync": field_id},
                children=[
                    html.Option(option["label"], value=option["value"])
                    for option in normalised
                ],
            ),
            dcc.Input(
                id=field_id,
                type="text",
                value=current,
                className="select-value",
            ),
        ],
    )


def radio_group(control_id: str, options, value=None, label_class: str = "radio-pill",
                input_class: str = "radio-input", className: str = "") -> dcc.RadioItems:
    """Native ``<input type=radio>`` options — always driveable, never a div toggle.

    Options may be plain strings (label == value) or ``(label, value)`` pairs.
    """
    normalised = normalise_options(options)
    return dcc.RadioItems(
        id=control_id,
        options=normalised,
        value=value,
        labelClassName=label_class,
        inputClassName=input_class,
        className=f"radio-group {className}".strip(),
    )


def status_legend() -> html.Div:
    """One legend for chips, table pills and map markers."""
    return html.Div(
        className="legend-row",
        children=[
            html.Span(
                className="legend-item",
                children=[
                    html.Span(
                        className="swatch",
                        style={"background": STATUS_COLORS[status]},
                        **{"aria-hidden": "true"},
                    ),
                    STATUS_LABELS[status],
                ],
            )
            for status in STATUS_LABELS
        ],
    )


def chart(figure, graph_id: str, height_class: str = "chart-340", config: dict | None = None,
          **kwargs) -> html.Div:
    """Every figure is drawn from this origin — no tiles, no CDN, no tokens."""
    graph_config = {"displayModeBar": False, "displaylogo": False, "responsive": True}
    graph_config.update(config or {})
    return html.Div(
        className=height_class,
        children=dcc.Graph(
            id=graph_id,
            figure=figure,
            config=graph_config,
            style={"height": "100%"},
            **kwargs,
        ),
    )


def loading(child, delay_ms: int = 120):
    """Wrap a region so Dash shows a spinner while its callback is in flight."""
    return dcc.Loading(
        children=child,
        type="circle",
        color="#9884f3",
        delay_show=delay_ms,
        className="dash-loading-custom",
    )


def skeleton(rows: int = 4) -> html.Div:
    return html.Div([html.Div(className="skeleton-row") for _ in range(rows)])


def submit_row(button_id: str, label: str, cancel_id: str | None = None, form_id: str = "") -> html.Div:
    """Submit control; Enter inside the form clicks it (see local-time.js)."""
    children = [
        html.Button(
            label,
            id=button_id,
            n_clicks=0,
            type="button",
            className="btn btn-primary",
            **{"data-enter-submit": button_id},
        )
    ]
    if cancel_id:
        children.append(
            html.Button("Clear", id=cancel_id, n_clicks=0, type="button", className="btn btn-ghost")
        )
    return html.Div(className="row mt-3", children=children, **{"data-enter-form": form_id} if form_id else {})
