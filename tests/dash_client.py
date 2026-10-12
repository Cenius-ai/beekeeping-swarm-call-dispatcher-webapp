"""Tiny client for driving the Dash callback endpoint from tests.

Mirrors exactly what dash-renderer posts to ``/_dash-update-component``, so the
suite exercises the real transport (including the session guard) rather than
calling Python functions directly.
"""

from __future__ import annotations

import json
import re

from dash._utils import stringify_id

DEMO_EMAIL = "cenius@cenius.ai"
DEMO_PASSWORD = "cenius"
CALLBACK_PATH = "/app/_dash-update-component"


def parse_callback_id(callback_id: str) -> list[dict]:
    """'..a.b...c.d..' -> [{'id': 'a', 'property': 'b'}, ...]."""
    stripped = callback_id.lstrip(".").rstrip(".")
    parsed = []
    for part in stripped.split("..."):
        part = part.strip(".")
        if not part:
            continue
        component_id, _, prop = part.rpartition(".")
        if component_id.startswith("{"):
            parsed.append({"id": json.loads(component_id), "property": prop})
        else:
            parsed.append({"id": component_id, "property": prop})
    return parsed


def prop_id(component_id, prop: str) -> str:
    """The exact prop-id string dash-renderer would send for this component."""
    return f"{stringify_id(component_id)}.{prop}"


def sign_in(client, identity: str = DEMO_EMAIL, password: str = DEMO_PASSWORD):
    page = client.get("/signin")
    assert page.status_code == 200, "sign-in page must render"
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert match, "sign-in form must carry a CSRF token"
    return client.post(
        "/signin",
        data={
            "csrf_token": match.group(1),
            "identity": identity,
            "password": password,
            "next": "/app/",
        },
        follow_redirects=False,
    )


def call(client, output: str, inputs: list[dict] | None = None, state: list[dict] | None = None,
         changed: list[str] | None = None, expect: int = 200):
    """POST one Dash callback and return the parsed response mapping."""
    inputs = inputs or []
    parsed = parse_callback_id(output)
    # dash-renderer sends a single specifier object for scalar callbacks and a
    # list for grouped ones; Dash validates the shape strictly.
    payload = {
        "output": output,
        "outputs": parsed if output.startswith("..") else parsed[0],
        "inputs": inputs,
        "state": state or [],
        "changedPropIds": changed
        if changed is not None
        else [prop_id(item["id"], item["property"]) for item in inputs],
    }
    response = client.post(
        CALLBACK_PATH,
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == expect, (
        f"callback {output} returned {response.status_code}: {response.get_data(as_text=True)[:400]}"
    )
    if response.status_code != 200:
        return response
    body = response.get_json()
    return body["response"] if body.get("multi") else body


def multi(*specs: str) -> str:
    """Build the joined output specifier Dash expects for multi-output callbacks."""
    return ".." + "...".join(specs) + ".."
