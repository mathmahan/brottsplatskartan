from enum import StrEnum
class Platform(StrEnum):
    SENSOR = "sensor"
    GEO_LOCATION = "geo_location"
    EVENT = "event"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
