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

# Field names confirmed against a live response (Stockholms län, Nov 2026).
# The API publishes no schema, so each field is still read through a list of
# candidate keys, with the observed name first and older/plausible spellings
# after it as a fallback.
#
# One observed row, abridged:
#   headline                    'Försök till inbrott i container på Alströmergatan, Kungsholmen'
#   title_type                  'Stöld'
#   title_location              'Stockholm'                   <- the kommun
#   administrative_area_level_1 'Stockholms län'               <- the county
#   administrative_area_level_2 None                           <- always null, do not rely on it
#   location_string             'Kungsholmen, Alströmergatan, Fridhemsgatan, Stockholm, Stockholms län'
#   location_string_2           'Kungsholmen, Alströmergatan, Fridhemsgatan, Stockholm'
#   description                 'Polisen får in ett samtal om ett försök till inbrott ...'
#   permalink                   'https://brottsplatskartan.se/stockholm/stold-stockholm-kungsholmen-512915'
#   external_source_link        'https://polisen.se/aktuellt/handelser/...'
#   lat / lng                   59.3357055 / 18.0314941
#   image / image_far           static map images of the location
#   date_human                  '49 minuter sedan'

#: Fields holding a single place name. `title_location` is the municipality and
#: was present on every observed row; `administrative_area_level_2` looks like
#: the obvious choice but is null in practice, so it sits in the fallbacks.
MUNICIPALITY_KEYS: tuple[str, ...] = (
    "title_location",
    "administrative_area_level_2",
    "admin_area_level_2",
    "kommun",
    "municipality",
    "city",
)
#: Fields holding a comma-separated place hierarchy, most specific first. Each
#: component is treated as a separate candidate, which is what makes filtering
#: on a district ("Kungsholmen", "Södermalm") work as well as on a kommun.
HIERARCHY_KEYS: tuple[str, ...] = (
    "location_string_2",
    "location_string",
    "location",
)
DEFAULT_LOCATION_KEYS: tuple[str, ...] = MUNICIPALITY_KEYS + HIERARCHY_KEYS
COUNTY_KEYS: tuple[str, ...] = (
    "administrative_area_level_1",
    "admin_area_level_1",
    "lan",
    "county",
)
LAT_KEYS: tuple[str, ...] = ("lat", "latitude")
LNG_KEYS: tuple[str, ...] = ("lng", "lon", "long", "longitude")
URL_KEYS: tuple[str, ...] = ("permalink", "url", "link", "guid")
SOURCE_URL_KEYS: tuple[str, ...] = ("external_source_link", "source_link")
ID_KEYS: tuple[str, ...] = ("id", "event_id", "externalId", "external_id")
TITLE_KEYS: tuple[str, ...] = ("headline", "title", "name")
TYPE_KEYS: tuple[str, ...] = ("title_type", "type", "category")
DESC_KEYS: tuple[str, ...] = ("description", "content_teaser", "summary")
TEASER_KEYS: tuple[str, ...] = ("content_teaser", "description")
IMAGE_KEYS: tuple[str, ...] = ("image",)
IMAGE_WIDE_KEYS: tuple[str, ...] = ("image_far", "image")
HUMAN_DATE_KEYS: tuple[str, ...] = ("date_human",)
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
    #: The municipality, from `title_location`.
    municipality: str | None
    #: The most specific place name available, e.g. "Kungsholmen". Taken from
    #: the first component of the location hierarchy, which is finer-grained
    #: than the municipality and is what you actually want on a card.
    place: str | None
    #: The full human-readable hierarchy, e.g.
    #: "Kungsholmen, Alströmergatan, Fridhemsgatan, Stockholm".
    location: str | None
    county: str | None
    latitude: float | None
    longitude: float | None
    url: str | None
    #: The police's own page for the event, when the API links one.
    source_url: str | None
    description: str | None
    #: Relative time as the API phrases it, e.g. "49 minuter sedan".
    date_human: str | None
    image: str | None = field(default=None, repr=False)
    image_wide: str | None = field(default=None, repr=False)
    #: Normalized place names this incident matches, used by the filter.
    places: frozenset[str] = field(default=frozenset(), repr=False)
    #: The same names as the API wrote them, for the diagnostic attribute.
    raw_places: tuple[str, ...] = field(default=(), repr=False)

    def as_dict(self, *, include_image: bool = False) -> dict[str, Any]:
        """Render for use in a state attribute or a template.

        Images are left out unless asked for: the static-map URLs are several
        hundred characters each, and a list of them would push the sensor's
        attributes past what the recorder will store.
        """
        data: dict[str, Any] = {
            "id": self.uid,
            "title": self.title,
            "type": self.incident_type,
            "published": self.published.isoformat(),
            "date_human": self.date_human,
            "municipality": self.municipality,
            "place": self.place,
            "location": self.location,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "url": self.url,
            "source_url": self.source_url,
            "description": self.description,
        }
        if include_image:
            data["image"] = self.image
            data["image_wide"] = self.image_wide
        return data


def place_candidates(
    row: dict[str, Any], location_keys: tuple[str, ...]
) -> list[str]:
    """Every place name a row mentions, most specific first, de-duplicated.

    `location_string` is a comma-separated hierarchy, so it is split into
    components. Without that split the whole string would be compared as one
    name and never match anything — and because it ends in "Stockholms län" it
    would be rejected outright as a county.
    """
    found: list[str] = []
    seen: set[str] = set()
    for key in location_keys:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        for part in value.split(","):
            part = part.strip()
            if part and part.lower() not in seen:
                seen.add(part.lower())
                found.append(part)
    return found


def parse_incident(
    row: dict[str, Any], location_keys: tuple[str, ...]
) -> Incident | None:
    """Normalize one API row, or return None if it is unusable."""
    published = _parse_pubdate(row)
    if published is None:
        LOGGER.debug("Skipping row without a parsable publication date: %s", row)
        return None

    raw_id = _first(row, ID_KEYS)
    title = _str_or_none(_first(row, TITLE_KEYS)) or "Okänd händelse"
    # Fall back to a synthetic key so de-duplication still works if the API
    # ever stops sending an id.
    uid = str(raw_id) if raw_id is not None else f"{published.isoformat()}|{title}"

    raw_places = place_candidates(row, location_keys)
    places = frozenset(
        norm for place in raw_places if (norm := normalize_place(place)) is not None
    )

    municipality = _str_or_none(_first(row, MUNICIPALITY_KEYS))
    if municipality is not None and normalize_place(municipality) is None:
        # Guard against the municipality field holding a county name.
        municipality = None

    location = _str_or_none(_first(row, HIERARCHY_KEYS))
    # The most specific name comes from the hierarchy's first component, not
    # from `raw_places[0]` — that list starts with the municipality keys, so it
    # would hand back "Stockholm" where "Kungsholmen" is wanted.
    hierarchy = place_candidates(row, HIERARCHY_KEYS)
    place = hierarchy[0] if hierarchy else municipality

    return Incident(
        uid=uid,
        title=title,
        incident_type=_str_or_none(_first(row, TYPE_KEYS)),
        published=published,
        municipality=municipality,
        place=place,
        location=location,
        county=_str_or_none(_first(row, COUNTY_KEYS)),
        latitude=_as_float(_first(row, LAT_KEYS)),
        longitude=_as_float(_first(row, LNG_KEYS)),
        url=_str_or_none(_first(row, URL_KEYS)),
        source_url=_str_or_none(_first(row, SOURCE_URL_KEYS)),
        description=_str_or_none(_first(row, DESC_KEYS)),
        date_human=_str_or_none(_first(row, HUMAN_DATE_KEYS)),
        image=_str_or_none(_first(row, IMAGE_KEYS)),
        image_wide=_str_or_none(_first(row, IMAGE_WIDE_KEYS)),
        places=places,
        raw_places=tuple(raw_places),
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
    """Keep only incidents matching one of `municipalities`.

    Matching is against every component of the location hierarchy, so a
    district ("Kungsholmen") works as well as a municipality ("Stockholm").
    Comparison is exact after normalization, not a substring test, so
    "Stockholmsvägen" in Nacka does not count as Stockholm.

    `municipalities` must already be normalized with `normalize_place`. An
    empty set means no filtering.
    """
    if not municipalities:
        return incidents
    return [
        incident for incident in incidents if incident.places & municipalities
    ]
