"""Minimal async client for the public Brottsplatskartan API.

Written from scratch rather than using the `brottsplatskartan` PyPI package,
which has two behaviours we specifically do not want:

* it filters on *calendar day* of the publication date, so the count resets at
  local midnight instead of being a rolling window;
* `get_incidents_from_bpk` resets its accumulator to `[]` whenever any page of
  results comes back empty, throwing away everything collected from earlier
  pages, and it stops paging at the first out-of-window row, which assumes the
  API always returns strictly reverse-chronological results.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp
from yarl import URL

from homeassistant.util import dt as dt_util

from .const import LOGGER

EVENTS_URL = "https://brottsplatskartan.se/api/events"
NEARBY_URL = "https://brottsplatskartan.se/api/eventsNearby"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The API has never published a schema and field names have drifted between
# versions, so every field is read through a list of candidate keys instead of
# one hard-coded spelling. The first key that yields a usable value wins.
DEFAULT_LOCATION_KEYS: tuple[str, ...] = (
    "administrative_area_level_2",
    "admin_area_level_2",
    "administrative_area",
    "admin_area",
    "kommun",
    "municipality",
    "title_location",
    "location_string",
    "location",
    "city",
    "place",
)
COUNTY_KEYS: tuple[str, ...] = (
    "administrative_area_level_1",
    "admin_area_level_1",
    "lan",
    "county",
)
LAT_KEYS: tuple[str, ...] = ("lat", "latitude")
LNG_KEYS: tuple[str, ...] = ("lng", "lon", "long", "longitude")
URL_KEYS: tuple[str, ...] = ("permalink", "url", "link", "guid")
ID_KEYS: tuple[str, ...] = ("id", "event_id", "externalId", "external_id")
TITLE_KEYS: tuple[str, ...] = ("title", "headline", "name")
TYPE_KEYS: tuple[str, ...] = ("title_type", "type", "category")
DESC_KEYS: tuple[str, ...] = ("description", "content", "summary", "body")
PUBDATE_KEYS: tuple[str, ...] = ("pubdate_iso8601", "pubdate", "published_at", "date")

# Suffixes stripped when comparing place names, so that a configured
# "Stockholm" matches "Stockholm", "Stockholms kommun" and "Stockholms stad".
PLACE_SUFFIXES: tuple[str, ...] = (" kommun", " stad", " municipality")


class BpkError(Exception):
    """Raised when the API could not be read."""


class BpkRateLimited(BpkError):
    """Raised when the API reports that we have been rate limited."""

    def __init__(self, reset: datetime | None) -> None:
        """Record when the rate limit is expected to lift."""
        self.reset = reset
        if reset is not None:
            super().__init__(f"Rate limited by brottsplatskartan.se until {reset}")
        else:
            super().__init__("Rate limited by brottsplatskartan.se")


def normalize_place(value: Any) -> str | None:
    """Reduce a place name to a comparable form, or None if it is not one.

    County names are deliberately rejected: `administrative_area_level_1` is
    "Stockholms län" for every row in the response, so matching on it would
    accept the whole county and defeat the municipality filter.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.endswith(" län") or text.endswith(" lan"):
        return None
    for suffix in PLACE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    text = text.strip()
    # Swedish place names appear in possessive form in some fields
    # ("Stockholms kommun" -> "stockholms"). Both sides of the comparison run
    # through this function, so stripping the trailing "s" stays consistent
    # even for names that genuinely end in one, such as Hofors.
    if text.endswith("s"):
        text = text[:-1]
    return text or None


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present, non-empty value among `keys`."""
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _str_or_none(value: Any) -> str | None:
    """Stringify a value, collapsing empties to None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    """Coerce a coordinate to float; the API returns them as strings."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_pubdate(row: dict[str, Any]) -> datetime | None:
    """Parse the publication timestamp into an aware datetime."""
    raw = _first(row, PUBDATE_KEYS)
    if isinstance(raw, str):
        if (parsed := dt_util.parse_datetime(raw)) is not None:
            return dt_util.as_utc(parsed)
    unix = row.get("pubdate_unix")
    if unix is not None:
        try:
            return dt_util.utc_from_timestamp(float(unix))
        except (TypeError, ValueError, OSError):
            return None
    return None


@dataclass(slots=True)
class Incident:
    """One normalized incident."""

    uid: str
    title: str
    incident_type: str | None
    published: datetime
    municipality: str | None
    county: str | None
    latitude: float | None
    longitude: float | None
    url: str | None
    description: str | None
    raw_places: tuple[str, ...] = field(default=(), repr=False)

    def as_dict(self) -> dict[str, Any]:
        """Render for use in a state attribute."""
        return {
            "id": self.uid,
            "title": self.title,
            "type": self.incident_type,
            "published": self.published.isoformat(),
            "municipality": self.municipality,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "url": self.url,
        }


def parse_incident(row: dict[str, Any], location_keys: tuple[str, ...]) -> Incident | None:
    """Normalize one API row, or return None if it is unusable."""
    published = _parse_pubdate(row)
    if published is None:
        LOGGER.debug("Skipping row without a parsable publication date: %s", row)
        return None

    raw_id = _first(row, ID_KEYS)
    title = _first(row, TITLE_KEYS) or "Okänd händelse"
    # Fall back to a synthetic key so de-duplication still works if the API
    # ever stops sending an id.
    uid = str(raw_id) if raw_id is not None else f"{published.isoformat()}|{title}"

    places: list[str] = []
    municipality: str | None = None
    for key in location_keys:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        places.append(value.strip())
        if municipality is None and normalize_place(value) is not None:
            municipality = value.strip()

    return Incident(
        uid=uid,
        title=str(title),
        incident_type=_str_or_none(_first(row, TYPE_KEYS)),
        published=published,
        municipality=municipality,
        county=_str_or_none(_first(row, COUNTY_KEYS)),
        latitude=_as_float(_first(row, LAT_KEYS)),
        longitude=_as_float(_first(row, LNG_KEYS)),
        url=_str_or_none(_first(row, URL_KEYS)),
        description=_str_or_none(_first(row, DESC_KEYS)),
        raw_places=tuple(places),
    )


async def async_fetch_incidents(
    session: aiohttp.ClientSession,
    *,
    app_id: str,
    area: str,
    since: datetime,
    max_pages: int,
    location_keys: tuple[str, ...] = DEFAULT_LOCATION_KEYS,
) -> list[Incident]:
    """Fetch every incident in `area` published at or after `since`.

    Pages forward until an entire page falls outside the window, so neither a
    single out-of-order row nor an empty page can truncate the result the way
    the upstream library does. `max_pages` is the hard stop.
    """
    url: URL | str = EVENTS_URL
    params: dict[str, str] | None = {"app": app_id, "area": area}
    by_uid: dict[str, Incident] = {}

    for page in range(1, max_pages + 1):
        try:
            async with session.get(url, params=params, timeout=REQUEST_TIMEOUT) as resp:
                if (reset := resp.headers.get("x-ratelimit-reset")) is not None:
                    reset_at: datetime | None = None
                    try:
                        reset_at = dt_util.utc_from_timestamp(float(reset))
                    except (TypeError, ValueError, OSError):
                        reset_at = None
                    raise BpkRateLimited(reset_at)
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except BpkRateLimited:
            raise
        except aiohttp.ClientError as err:
            raise BpkError(f"Error talking to brottsplatskartan.se: {err}") from err
        except asyncio.TimeoutError as err:
            raise BpkError("Timed out talking to brottsplatskartan.se") from err
        except ValueError as err:
            raise BpkError(f"Malformed JSON from brottsplatskartan.se: {err}") from err

        if not isinstance(payload, dict):
            raise BpkError(f"Unexpected payload type {type(payload).__name__}")

        rows = payload.get("data") or []
        if not rows:
            # An empty page means we have run off the end of the result set.
            # Keep everything collected so far.
            break

        newest_on_page: datetime | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (incident := parse_incident(row, location_keys)) is None:
                continue
            if newest_on_page is None or incident.published > newest_on_page:
                newest_on_page = incident.published
            if incident.published >= since:
                by_uid.setdefault(incident.uid, incident)

        if newest_on_page is not None and newest_on_page < since:
            # Every row on this page is older than the window, so no later page
            # can hold anything newer. Deliberately stricter than "the oldest
            # row is out of window": a single out-of-order row must not stop us
            # paging, which is the mistake the upstream library makes.
            break

        links = payload.get("links")
        next_page = links.get("next_page_url") if isinstance(links, dict) else None
        if not next_page:
            break

        # next_page_url carries its own query string, but not reliably our
        # `app` and `area` values, so merge them back in rather than passing
        # `params` again and sending each key twice.
        url = URL(str(next_page)).update_query({"app": app_id, "area": area})
        params = None
    else:
        LOGGER.debug(
            "Stopped after the %s page page-limit; raise max_pages if counts look low",
            max_pages,
        )

    return sorted(by_uid.values(), key=lambda inc: inc.published, reverse=True)


def filter_by_municipality(
    incidents: list[Incident], municipalities: set[str]
) -> list[Incident]:
    """Keep only incidents whose location matches one of `municipalities`.

    `municipalities` must already be normalized with `normalize_place`. An
    empty set means no filtering.
    """
    if not municipalities:
        return incidents
    kept: list[Incident] = []
    for incident in incidents:
        candidates = {
            norm
            for place in incident.raw_places
            if (norm := normalize_place(place)) is not None
        }
        if candidates & municipalities:
            kept.append(incident)
    return kept
