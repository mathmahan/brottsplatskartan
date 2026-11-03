"""Constants for the local Brottsplatskartan integration."""

from __future__ import annotations

import logging
from datetime import timedelta

DOMAIN = "brottsplatskartan_local"
LOGGER = logging.getLogger(__package__)

CONF_AREA = "area"
CONF_MUNICIPALITIES = "municipalities"
CONF_HOURS = "hours"
CONF_MAX_PAGES = "max_pages"
CONF_MAX_ATTRIBUTE_INCIDENTS = "max_attribute_incidents"
CONF_MAX_MARKERS = "max_markers"
CONF_LOCATION_KEYS = "location_keys"
CONF_APP_ID = "app_id"
#: Poll interval in whole minutes. Config entries are stored as JSON, so a
#: timedelta cannot go in there; the YAML path converts to this on import.
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_NAME = "Brottsplatskartan"
DEFAULT_AREA = "Stockholms län"
DEFAULT_HOURS = 24
DEFAULT_MAX_PAGES = 6
DEFAULT_MAX_ATTRIBUTE_INCIDENTS = 25
DEFAULT_MAX_MARKERS = 100
DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)
MIN_SCAN_INTERVAL = timedelta(minutes=5)
DEFAULT_UPDATE_INTERVAL = 15
MIN_UPDATE_INTERVAL = 5

ATTRIBUTION = "Information provided by brottsplatskartan.se"

EVENT_NEW_INCIDENT = f"{DOMAIN}_new_incident"

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
