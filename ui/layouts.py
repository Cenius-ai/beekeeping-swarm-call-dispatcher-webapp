"""The signed-in application shell: header, tab bar and the four tab panels.

All four panels are always mounted (inactive ones are hidden with CSS, not
removed) so every Dash callback always has a live component to write to.
"""

from __future__ import annotations

from dash import dcc, html

from db import get_session
from ui import dispatch_tab, outcomes_tab, reports_tab, volunteers_tab
from ui.signin import PRODUCT_NAME

TABS = [
    ("reports", "Reports"),
    ("dispatch", "Dispatch"),
    ("volunteers", "Volunteers"),
    ("outcomes", "Outcomes"),
]

TAB_ORDER = [value for value, _ in TABS]


def header(user) -> html.Header:
    """Coordinator identity, the live indicator and the sign-out control."""
    return html.Header(
        className="app-header hero",
        children=[
            html.Div(
                className="brand",
                children=[
                    html.Span("SC", className="brand-mark", **{"aria-hidden": "true"}),
                    html.Div(
                        className="brand-copy",
                        children=[
                            html.Div(PRODUCT_NAME, className="brand-title"),
                            html.Div("Avon Valley swarm hotline", className="brand-sub"),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="header-right",
                children=[
                    html.Span(
                        className="live",
                        children=[
                            html.Span(className="live-dot", **{"aria-hidden": "true"}),
                            html.Span("Hotline live"),
                        ],
                    ),
                    html.Div(
                        className="who",
                        children=[
                            html.Div(
                                user.display_name if user else "Coordinator",
                                id="coordinator-name",
                                className="who-name",
                            ),
                            html.Div(
                                "Coordinator on duty",
                                id="coordinator-role",
                                className="who-role",
                            ),
                        ],
                    ),
                    html.Form(
                        action="/logout",
                        method="post",
                        className="row",
                        children=[
                            dcc.Input(
                                id="logout-csrf",
                                type="hidden",
                                name="csrf_token",
                                value="",
                            ),
                            html.Button(
                                "Sign out",
                                id="signout",
                                n_clicks=0,
                                type="submit",
                                className="btn btn-sm",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def tab_bar(active: str) -> dcc.Tabs:
    return dcc.Tabs(
        id="tabs",
        value=active if active in TAB_ORDER else "reports",
        className="swarm-tabs",
        parent_className="swarm-tabs-wrap",
        colors={"border": "#2d2d34", "primary": "#9884f3", "background": "#16161d"},
        children=[
            dcc.Tab(
                label=label,
                value=value,
                className="swarm-tab",
                selected_className="swarm-tab swarm-tab--selected",
            )
            for value, label in TABS
        ],
    )


def build_layout(user, active_tab: str = "reports") -> html.Div:
    """Server-render page one with real seeded content in every panel."""
    db = get_session()
    try:
        reports_view = reports_tab.load_view(db)
        dispatch_view = dispatch_tab.load_view(db)
        volunteers_view = volunteers_tab.load_view(db)
        outcomes_view = outcomes_tab.load_view(db)
    finally:
        db.close()

    active_tab = active_tab if active_tab in TAB_ORDER else "reports"
    panels = [
        (value, panel_fn(view))
        for (value, panel_fn, view) in (
            ("reports", reports_tab.panel, reports_view),
            ("dispatch", dispatch_tab.panel, dispatch_view),
            ("volunteers", volunteers_tab.panel, volunteers_view),
            ("outcomes", outcomes_tab.panel, outcomes_view),
        )
    ]

    return html.Div(
        className="app-shell",
        children=[
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="reports-refresh", data=0),
            dcc.Store(id="dispatch-refresh", data=0),
            dcc.Store(id="volunteers-refresh", data=0),
            dcc.Store(id="outcomes-refresh", data=0),
            dcc.Store(id="stamp-report-created", data=0),
            dcc.Store(id="stamp-dispatch-changed", data=0),
            dcc.Store(id="stamp-volunteer-changed", data=0),
            dcc.Store(id="stamp-outcome-recorded", data=0),
            header(user),
            tab_bar(active_tab),
            html.Div(
                className="tabpanels",
                children=[
                    html.Div(
                        id=f"panel-{value}",
                        className="tabpanel tabpanel--active" if value == active_tab else "tabpanel",
                        **{"aria-hidden": "false" if value == active_tab else "true"},
                        children=panel,
                    )
                    for value, panel in panels
                ],
            ),
        ],
    )
