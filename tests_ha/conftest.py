"""Fixtures for the real Home Assistant integration tests.

These run against an actual Home Assistant instance via
pytest-homeassistant-custom-component, so they exercise the genuine config
flow, entity platform, service registry and issue registry rather than stubs.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

EVENTS_URL = "https://brottsplatskartan.se/api/events"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ in every test."""
    return


def incident_row(
    n: int,
    *,
    minutes_ago: int,
    lat: float,
    lng: float,
    kommun: str = "Stockholm",
    district: str | None = None,
    kind: str = "Stöld",
) -> dict:
    """One API row, in the shape the live API actually returns."""
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    hierarchy = [p for p in (district, kommun) if p]
    return {
        "id": n,
        "headline": f"{kind} i {district or kommun}",
        "title_type": kind,
        "title_location": kommun,
        "administrative_area_level_1": "Stockholms län",
        "administrative_area_level_2": None,
        "location_string": ", ".join([*hierarchy, "Stockholms län"]),
        "location_string_2": ", ".join(hierarchy),
        "description": f"Polisen rapporterar {kind.lower()} i {district or kommun}.",
        "content": f"<p>{kind}</p>",
        "content_teaser": f"{kind} i {district or kommun}",
        "permalink": f"https://brottsplatskartan.se/stockholm/handelse-{n}",
        "external_source_link": f"https://polisen.se/handelser/{n}/",
        "image": f"https://kartbilder.brottsplatskartan.se/{n}.jpg",
        "image_far": f"https://kartbilder.brottsplatskartan.se/{n}-far.jpg",
        "date_human": f"{minutes_ago} minuter sedan",
        "lat": lat,
        "lng": lng,
        "pubdate_iso8601": when.astimezone().isoformat(),
        "pubdate_unix": str(int(when.timestamp())),
    }


#: Home for the tests, in central Stockholm. One degree of latitude is about
#: 111.32 km, so the offsets below give predictable, assertable distances
#: rather than relying on whatever the rows happen to work out to.
HOME_LAT, HOME_LNG = 59.3293, 18.0686


def _north_of_home(km: float) -> tuple[float, float]:
    return HOME_LAT + km / 111.32, HOME_LNG


#: Ages and positions are all distinct, so "newest" and "nearest" are
#: unambiguous. Two rows with the same age differ only by the microseconds
#: between their timestamps being computed, which made an earlier version of
#: these tests pick a different row on each run.
DEFAULT_ROWS = [
    # In scope: Stockholm kommun, inside 24 h. Newest and nearest.
    ("kungsholmen", dict(minutes_ago=10, district="Kungsholmen", kind="Stöld",
                         **dict(zip(("lat", "lng"), _north_of_home(4.0))))),
    ("norrmalm", dict(minutes_ago=90, district="Norrmalm", kind="Rån",
                      **dict(zip(("lat", "lng"), _north_of_home(6.0))))),
    # Filtered out by the municipality filter.
    ("nacka", dict(minutes_ago=20, kommun="Nacka", kind="Skadegörelse",
                   lat=59.31, lng=18.16)),
    ("sodertalje", dict(minutes_ago=50, kommun="Södertälje", district="Filen",
                        kind="Stöld", lat=59.19, lng=17.62)),
    # Filtered out by the 24 hour window.
    ("old", dict(minutes_ago=60 * 40, district="Södermalm", kind="Stöld",
                 **dict(zip(("lat", "lng"), _north_of_home(2.0))))),
]


@pytest.fixture
def api(aioclient_mock):
    """Serve a default single-page API response; tests can re-arm it."""

    def serve(rows, *, clear=True):
        if clear:
            aioclient_mock.clear_requests()
        aioclient_mock.get(EVENTS_URL, json={"data": rows})
        return aioclient_mock

    serve([incident_row(n, **kw) for n, (_, kw) in enumerate(DEFAULT_ROWS, start=1)])
    serve.mock = aioclient_mock
    return serve
