"""Static wiring checks: no duplicate callback outputs, every callback target
exists in the rendered layout, and every asset the page asks for is delivered.
"""

from __future__ import annotations

import collections
import json
import re
import sys

import pytest
from dash import dcc

@pytest.fixture()
def app_client_and_html(auth_client):
    return auth_client, auth_client.get("/app/").get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Layout walking helpers
# --------------------------------------------------------------------------- #


def to_dict(node):
    """Dash keeps nested components as objects inside to_plotly_json()."""
    if hasattr(node, "to_plotly_json"):
        return node.to_plotly_json()
    return node


class LayoutEncoder(json.JSONEncoder):
    def default(self, obj):  # noqa: D102
        if hasattr(obj, "to_plotly_json"):
            return obj.to_plotly_json()
        return super().default(obj)


def dump_layout(app_module) -> str:
    return json.dumps(app_module.app.layout, cls=LayoutEncoder)


def walk(node, visit):
    """Depth-first walk over every Dash component dict in the tree."""
    node = to_dict(node)
    if isinstance(node, dict):
        visit(node)
        for value in (node.get("props") or {}).values():
            walk(value, visit)
    elif isinstance(node, (list, tuple)):
        for item in node:
            walk(item, visit)


def collect_components(app_module, type_name):
    found = []
    walk(
        app_module.app.layout,
        lambda node: found.append(node) if node.get("type") == type_name else None,
    )
    return found


def find_component(app_module, type_name):
    found = collect_components(app_module, type_name)
    return found[0] if found else None


def layout_index(app_module):
    ids, patterns = set(), set()

    def visit(node):
        component_id = (node.get("props") or {}).get("id")
        if isinstance(component_id, str):
            ids.add(component_id)
        elif isinstance(component_id, dict) and "type" in component_id:
            patterns.add(tuple(sorted(component_id.keys())))

    walk(app_module.app.layout, visit)
    return ids, patterns


def normalise_id(raw):
    """callback_map stores wildcard ids as JSON strings."""
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


# --------------------------------------------------------------------------- #
# Callback wiring
# --------------------------------------------------------------------------- #
def test_no_duplicate_callback_outputs(app_module):
    """One writer per (id, property) app-wide, or Dash wires nothing at all."""
    counters = collections.Counter()
    for key in app_module.app.callback_map:
        parts = key.lstrip(".").rstrip(".").split("...") if "..." in key else [key]
        for part in parts:
            part = part.strip(".")
            if "@" in part or not part:
                continue
            counters[part] += 1
    duplicates = [name for name, count in counters.items() if count > 1]
    assert duplicates == [], f"duplicate callback outputs: {duplicates}"


def test_every_callback_target_exists_in_the_layout(app_module):
    ids, patterns = layout_index(app_module)
    missing = []
    for key, entry in app_module.app.callback_map.items():
        for spec in (entry.get("inputs") or []) + (entry.get("state") or []):
            component_id = normalise_id(spec["id"])
            if isinstance(component_id, str):
                if component_id not in ids:
                    missing.append((key, component_id, spec["property"]))
            elif tuple(sorted(component_id.keys())) not in patterns:
                missing.append((key, component_id, spec["property"]))
    for key in app_module.app.callback_map:
        parts = key.lstrip(".").rstrip(".").split("...") if "..." in key else [key]
        for part in parts:
            component_id = part.strip(".").rpartition(".")[0]
            if component_id and not component_id.startswith("{") and component_id not in ids:
                missing.append((key, component_id, None))
    assert missing == [], f"callbacks point at components that do not exist: {missing}"


def test_layout_has_four_clearly_separate_tabs(app_module):
    tabs = find_component(app_module, "Tabs")
    assert tabs is not None, "the shell must render dcc.Tabs"
    children = [to_dict(child) for child in tabs["props"]["children"]]
    assert [child["props"]["label"] for child in children] == [
        "Reports",
        "Dispatch",
        "Volunteers",
        "Outcomes",
    ]
    values = [child["props"]["value"] for child in children]
    assert values == ["reports", "dispatch", "volunteers", "outcomes"]

    ids, _ = layout_index(app_module)
    for value in values:
        assert f"panel-{value}" in ids


def test_choice_fields_are_real_native_selects(app_module):
    """Required choices must be driveable: a real <select> with real values."""
    selects = collect_components(app_module, "Select")
    options = collect_components(app_module, "Option")
    carriers = [
        item
        for item in collect_components(app_module, "Input")
        if "select-value" in ((item["props"] or {}).get("className") or "")
    ]
    hidden_ids = {item["props"].get("id") for item in carriers}
    names = {item["props"].get("name") for item in selects}

    assert {"intake-urgency", "intake-cluster", "intake-site"} <= names
    assert {"outcome-result", "outcome-destination"} <= names
    assert hidden_ids >= {"intake-urgency", "intake-cluster", "intake-site", "outcome-result"}
    assert any(
        item["props"].get("value") == "Clifton Down Allotments" for item in options
    ), "the site picker must offer real option values"
    assert len(options) >= 25


def test_no_custom_toggle_groups_are_required(app_module):
    """A create form must never depend on a bare button/div toggle group."""
    assert collect_components(app_module, "RadioItems") == []
    assert collect_components(app_module, "Checklist") == []


# --------------------------------------------------------------------------- #
# First paint, assets and delivered files
# --------------------------------------------------------------------------- #
def test_tabs_render_seeded_content_on_first_paint(app_module):
    payload = dump_layout(app_module)
    for heading in (
        "Swarm report triage",
        "Ranked collectors",
        "Collector roster",
        "Pipeline funnel",
    ):
        assert heading in payload, f"{heading} must be present in the first paint"
    assert "No reports match these filters" not in payload


def test_index_html_references_only_local_assets(auth_client):
    html_text = auth_client.get("/app/").get_data(as_text=True)
    remote = re.findall(r'(?:src|href)="(https?://[^"]+|//[^"]+)"', html_text)
    assert remote == [], f"the page must not depend on remote assets: {remote}"
    assert "fonts.googleapis" not in html_text

    referenced = set(re.findall(r'(?:src|href)="(/static/[^"]+)"', html_text))
    assert "/static/theme.css" in referenced
    for asset in sorted(referenced):
        assert auth_client.get(asset).status_code == 200, f"{asset} must be delivered"


def test_fonts_and_behaviour_script_are_served(auth_client):
    for asset in (
        "/static/app-behaviour.js",
        "/static/favicon.svg",
        "/static/fonts/rajdhani-700.woff2",
        "/static/fonts/chakra-petch-400.woff2",
    ):
        assert auth_client.get(asset).status_code == 200, asset


def test_security_headers_are_set(client):
    headers = client.get("/signin").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_stylesheet_is_balanced_and_uses_the_committed_tokens(app_module):
    css = (app_module.BASE_DIR / "static" / "theme.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}"), "an unclosed rule nests the whole sheet"
    for token in (
        "--background: #0c0c11",
        "--accent: #9884f3",
        "--card: #16161d",
        "Rajdhani",
        "Chakra Petch",
        "prefers-reduced-motion",
    ):
        assert token in css, f"{token} must survive into the delivered CSS"
    assert "oklch(0.68 0.16 290)" in css, "the committed accent ramp stays in the CSS layer"


def test_no_inline_event_handlers_in_server_rendered_html(client):
    html_text = client.get("/signin").get_data(as_text=True)
    assert not re.search(r"\son[a-z]+\s*=", html_text), "no inline event handlers"


def test_seeded_demo_account_and_roster_exist(app_module):
    from sqlalchemy import func, select

    from db import User, Volunteer, session_scope

    with session_scope() as db:
        user = db.execute(select(User).where(User.username == "cenius")).scalar_one()
        assert user.email == "cenius@cenius.ai"
        assert user.password_hash != "cenius"
        assert db.execute(select(func.count(Volunteer.id))).scalar_one() >= 8


def test_flask_cli_can_find_exactly_one_application(app_module):
    """`flask run` must resolve this module: several Flask instances is fatal."""
    from flask import Flask
    from flask.cli import find_best_app

    module = sys.modules["app"]
    found = find_best_app(module)
    assert isinstance(found, Flask)
    assert found is app_module.server
    assert module.application is app_module.server
    assert isinstance(module.flask_server, Flask)


def test_flaskenv_sets_the_cli_defaults(app_module):
    env_file = app_module.BASE_DIR / ".flaskenv"
    assert env_file.is_file(), "flask run needs .flaskenv for host/port defaults"
    text = env_file.read_text(encoding="utf-8")
    assert "FLASK_APP=app" in text
    assert "FLASK_RUN_HOST=0.0.0.0" in text


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_dash_location_carries_no_static_href(app_module):
    locations = collect_components(app_module, "Location")
    assert locations, "the shell needs dcc.Location for the tab round trip"
    for location in locations:
        assert not (location["props"] or {}).get("href"), "a literal href reloads the page"


def test_feedback_panels_start_hidden(app_module):
    ids, _ = layout_index(app_module)
    for panel in ("intake-feedback", "dispatch-feedback", "volunteer-feedback", "outcome-feedback"):
        assert panel in ids
    payload = dump_layout(app_module)
    assert '"display": "none"' in payload


def test_dash_bundles_are_served_from_this_origin(app_client_and_html):
    """Plotly ships inside dash-core-components; nothing is fetched at runtime."""
    auth_client, html_text = app_client_and_html
    assert "cdn" not in html_text.lower()
    suites = set(re.findall(r'src="(/app/_dash-component-suites/[^"]+)"', html_text))
    assert suites, "the Dash bundle must be referenced"
    for asset in sorted(suites):
        assert auth_client.get(asset).status_code == 200, f"{asset} must be delivered"
    assert any("dash_core_components" in asset for asset in suites)
