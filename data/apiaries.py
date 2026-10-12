"""Local apiary destinations a collected swarm can be rehomed to.

These are the only rehoming targets the Outcome form offers. They live in the
repository, not behind a network call.
"""

from __future__ import annotations

APIARIES = [
    {
        "name": "Avon Valley Apiary",
        "operator": "Bristol Beekeepers' Association",
        "kind": "association apiary",
        "capacity": 18,
    },
    {
        "name": "Blaise Community Apiary",
        "operator": "Henbury & District Branch",
        "kind": "community apiary",
        "capacity": 10,
    },
    {
        "name": "Ashton Court Woodland Hives",
        "operator": "Long Ashton Trust",
        "kind": "estate apiary",
        "capacity": 12,
    },
    {
        "name": "Keynsham Training Apiary",
        "operator": "Bristol BKA training team",
        "kind": "training apiary",
        "capacity": 8,
    },
    {
        "name": "Frampton Cotterell Farm Apiary",
        "operator": "M. Adeyemi & Sons",
        "kind": "farm apiary",
        "capacity": 24,
    },
    {
        "name": "Nailsea Out-Apiary",
        "operator": "North Somerset Beekeepers",
        "kind": "out-apiary",
        "capacity": 14,
    },
    {
        "name": "Seabank Orchard Apiary",
        "operator": "Portishead Gardeners' Guild",
        "kind": "orchard apiary",
        "capacity": 6,
    },
    {
        "name": "Dundry Slopes Apiary",
        "operator": "Bristol BKA south cluster",
        "kind": "association apiary",
        "capacity": 16,
    },
    {
        "name": "Warmley Forest Apiary",
        "operator": "Warmley Forest School",
        "kind": "school apiary",
        "capacity": 6,
    },
    {
        "name": "Retained on site (caller keeps swarm)",
        "operator": "Caller-managed",
        "kind": "in situ",
        "capacity": 0,
    },
]

APIARY_BY_NAME = {a["name"]: a for a in APIARIES}


def apiary_names() -> list[str]:
    """Rehoming destinations in picker order."""
    return [a["name"] for a in APIARIES]


def lookup(name: str) -> dict | None:
    """Return the apiary record for *name*, or ``None`` when unknown."""
    if not name:
        return None
    return APIARY_BY_NAME.get(name.strip())
