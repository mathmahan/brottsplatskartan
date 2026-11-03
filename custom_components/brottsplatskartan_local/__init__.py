"""The local Brottsplatskartan integration, configured from YAML."""

from __future__ import annotations

import uuid
from datetime import timedelta

import voluptuous as vol

from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.typing import ConfigType

from .api import DEFAULT_LOCATION_KEYS
from .const import (
    AREAS,
    CONF_APP_ID,
    CONF_AREA,
    CONF_HOURS,
    CONF_LOCATION_KEYS,
    CONF_MAX_ATTRIBUTE_INCIDENTS,
    CONF_MAX_PAGES,
    CONF_MUNICIPALITIES,
    DEFAULT_AREA,
    DEFAULT_HOURS,
    DEFAULT_MAX_ATTRIBUTE_INCIDENTS,
    DEFAULT_MAX_PAGES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MIN_SCAN_INTERVAL,
)
from .coordinator import BpkCoordinator

PLATFORMS = [Platform.SENSOR, Platform.GEO_LOCATION, Platform.EVENT]


def _at_least_min_interval(value: timedelta) -> timedelta:
    """Refuse a poll interval that would get the app id rate limited."""
    if value < MIN_SCAN_INTERVAL:
        raise vol.Invalid(
            f"scan_interval must be at least {int(MIN_SCAN_INTERVAL.total_seconds())}s "
            "to stay inside the API's rate limit"
        )
    return value


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_AREA, default=DEFAULT_AREA): vol.In(AREAS),
                vol.Optional(CONF_MUNICIPALITIES, default=[]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
                vol.Optional(CONF_HOURS, default=DEFAULT_HOURS): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=168)
                ),
                vol.Optional(CONF_MAX_PAGES, default=DEFAULT_MAX_PAGES): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=40)
                ),
                vol.Optional(
                    CONF_MAX_ATTRIBUTE_INCIDENTS,
                    default=DEFAULT_MAX_ATTRIBUTE_INCIDENTS,
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=200)),
                vol.Optional(CONF_LOCATION_KEYS): vol.All(
                    cv.ensure_list, [cv.string]
                ),
                vol.Optional(CONF_APP_ID): cv.string,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(cv.time_period, _at_least_min_interval),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from configuration.yaml."""
    conf = config.get(DOMAIN)
    if conf is None:
        return True

    location_keys = tuple(conf.get(CONF_LOCATION_KEYS) or DEFAULT_LOCATION_KEYS)

    coordinator = BpkCoordinator(
        hass,
        # The API uses this to attribute rate limits, so it should be stable
        # across restarts but unique to this installation.
        app_id=conf.get(CONF_APP_ID) or f"ha-{uuid.getnode():x}",
        area=conf[CONF_AREA],
        municipalities=conf[CONF_MUNICIPALITIES],
        hours=conf[CONF_HOURS],
        max_pages=conf[CONF_MAX_PAGES],
        location_keys=location_keys,
        scan_interval=conf[CONF_SCAN_INTERVAL],
    )

    # Not async_config_entry_first_refresh(): that helper requires a config
    # entry, and this integration is set up from YAML. A failed first fetch
    # leaves the entities unavailable rather than aborting setup.
    await coordinator.async_refresh()

    hass.data[DOMAIN] = {
        "coordinator": coordinator,
        CONF_MAX_ATTRIBUTE_INCIDENTS: conf[CONF_MAX_ATTRIBUTE_INCIDENTS],
    }

    for platform in PLATFORMS:
        hass.async_create_task(
            discovery.async_load_platform(hass, platform, DOMAIN, {}, config)
        )

    LOGGER.debug(
        "Set up %s for %s (municipalities=%s, window=%sh, interval=%s)",
        DOMAIN,
        conf[CONF_AREA],
        conf[CONF_MUNICIPALITIES] or "all",
        conf[CONF_HOURS],
        conf[CONF_SCAN_INTERVAL],
    )
    return True
