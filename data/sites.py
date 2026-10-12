"""Named caller sites used by the swarm-call intake form.

Coordinates are real (approximate) locations in and around the Avon Valley
service area, so the straight-line distances the dispatcher shows are
believable. Nothing here is fetched at runtime.
"""

from __future__ import annotations

# Centre of the service area: Bristol, UK.
SERVICE_CENTRE = {"lat": 51.4545, "lon": -2.5879}
SERVICE_RADIUS_KM = 45.0

SITES = [
    {"name": "Clifton Down Allotments", "area": "Clifton", "lat": 51.4755, "lon": -2.6195},
    {"name": "Redland Green Pavilion", "area": "Redland", "lat": 51.4720, "lon": -2.6018},
    {"name": "Horfield Common Orchard", "area": "Horfield", "lat": 51.4869, "lon": -2.5836},
    {"name": "St Werburghs City Farm", "area": "St Werburghs", "lat": 51.4759, "lon": -2.5760},
    {"name": "Eastville Park Lodge", "area": "Eastville", "lat": 51.4746, "lon": -2.5550},
    {"name": "Victoria Park Primary", "area": "Bedminster", "lat": 51.4394, "lon": -2.5938},
    {"name": "Ashton Court Estate Gatehouse", "area": "Long Ashton", "lat": 51.4422, "lon": -2.6425},
    {"name": "Blaise Castle Museum Lawn", "area": "Henbury", "lat": 51.4996, "lon": -2.6372},
    {"name": "Kingsweston House Garden", "area": "Avonmouth", "lat": 51.4966, "lon": -2.6660},
    {"name": "Oldbury Court Walled Garden", "area": "Fishponds", "lat": 51.4844, "lon": -2.5351},
    {"name": "Snuff Mills Riverside Cafe", "area": "Stapleton", "lat": 51.4827, "lon": -2.5610},
    {"name": "Troopers Hill Clay Pit", "area": "St Anne's", "lat": 51.4520, "lon": -2.5298},
    {"name": "Netham Park Boat House", "area": "Netham", "lat": 51.4501, "lon": -2.5569},
    {"name": "Greville Smyth Park", "area": "Ashton", "lat": 51.4448, "lon": -2.6266},
    {"name": "Durdham Down Water Tower", "area": "Sneyd Park", "lat": 51.4789, "lon": -2.6299},
    {"name": "Fishponds Hive Yard", "area": "Fishponds", "lat": 51.4785, "lon": -2.5310},
    {"name": "Whitchurch Garden Centre", "area": "Whitchurch", "lat": 51.4098, "lon": -2.5719},
    {"name": "Keynsham Memorial Park", "area": "Keynsham", "lat": 51.4137, "lon": -2.4983},
    {"name": "Portishead Marina Gardens", "area": "Portishead", "lat": 51.4844, "lon": -2.7682},
    {"name": "Clevedon Pier Approach", "area": "Clevedon", "lat": 51.4420, "lon": -2.8580},
    {"name": "Warmley Forest School", "area": "Warmley", "lat": 51.4587, "lon": -2.4805},
    {"name": "Hanham Court Meadow", "area": "Hanham", "lat": 51.4498, "lon": -2.5112},
]

SITE_BY_NAME = {site["name"]: site for site in SITES}


def site_names() -> list[str]:
    """Site names in the order they appear in the intake picker."""
    return [site["name"] for site in SITES]


def lookup(name: str) -> dict | None:
    """Return the site record for *name*, or ``None`` when unknown."""
    if not name:
        return None
    return SITE_BY_NAME.get(name.strip())
