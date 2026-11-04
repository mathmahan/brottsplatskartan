"""Minimal stand-in for homeassistant.const.

Only what api.py and const.py import. Everything that needs more of Home
Assistant than this is tested against the real thing in tests_ha/.
"""

from enum import StrEnum


class Platform(StrEnum):
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    GEO_LOCATION = "geo_location"
    EVENT = "event"
