"""Constants for the local Brottsplatskartan integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "brottsplatskartan_local"
LOGGER = logging.getLogger(__package__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.GEO_LOCATION,
    Platform.EVENT,
]

# --- config entry data (set at setup, changed via the reconfigure flow) ---
CONF_AREA = "area"
CONF_APP_ID = "app_id"

# --- config entry options (all editable in the options flow) ---
CONF_MUNICIPALITIES = "municipalities"
CONF_HOURS = "hours"
#: Poll interval in whole minutes. Config entries are stored as JSON, so a
#: timedelta cannot go in there.
CONF_UPDATE_INTERVAL = "update_interval"
CONF_NEARBY_RADIUS = "nearby_radius"
CONF_MAX_ATTRIBUTE_INCIDENTS = "max_attribute_incidents"
CONF_MAX_MARKERS = "max_markers"
CONF_MAX_PAGES = "max_pages"
CONF_LOCATION_KEYS = "location_keys"
#: Collapsible section in the options form. Its contents are flattened into
#: the stored options, so the storage shape is unaffected.
SECTION_ADVANCED = "advanced"

DEFAULT_NAME = "Brottsplatskartan"
DEFAULT_AREA = "Stockholms län"
DEFAULT_HOURS = 24
DEFAULT_UPDATE_INTERVAL = 15
MIN_UPDATE_INTERVAL = 5
DEFAULT_NEARBY_RADIUS = 1.0
DEFAULT_MAX_ATTRIBUTE_INCIDENTS = 25
DEFAULT_MAX_MARKERS = 100
DEFAULT_MAX_PAGES = 6

ATTRIBUTION = "Information provided by brottsplatskartan.se"

EVENT_NEW_INCIDENT = f"{DOMAIN}_new_incident"

SERVICE_REFRESH = "refresh"
SERVICE_GET_INCIDENTS = "get_incidents"

ISSUE_OVERLAPPING_ENTRIES = "overlapping_entries"
ISSUE_DUPLICATE_ENTRIES = "duplicate_entries"

# The counties ("län") the API accepts for the `area` query parameter.
AREAS = [
    "Blekinge län",
    "Dalarnas län",
    "Gotlands län",
    "Gävleborgs län",
    "Hallands län",
    "Jämtlands län",
    "Jönköpings län",
    "Kalmar län",
    "Kronobergs län",
    "Norrbottens län",
    "Skåne län",
    "Stockholms län",
    "Södermanlands län",
    "Uppsala län",
    "Värmlands län",
    "Västerbottens län",
    "Västernorrlands län",
    "Västmanlands län",
    "Västra Götalands län",
    "Örebro län",
    "Östergötlands län",
]
