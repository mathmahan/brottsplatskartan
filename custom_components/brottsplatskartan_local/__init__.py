"""The local Brottsplatskartan integration.

Set up from the UI. A legacy `configuration.yaml` block is imported into a
config entry on first run and can then be deleted.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import DEFAULT_LOCATION_KEYS
from .const import (
    AREAS,
    CONF_APP_ID,
    CONF_AREA,
    CONF_HOURS,
    CONF_LOCATION_KEYS,
    CONF_MAX_ATTRIBUTE_INCIDENTS,
    CONF_MAX_MARKERS,
    CONF_MAX_PAGES,
    CONF_MUNICIPALITIES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_AREA,
    DEFAULT_HOURS,
    DEFAULT_MAX_ATTRIBUTE_INCIDENTS,
    DEFAULT_MAX_MARKERS,
    DEFAULT_MAX_PAGES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER,
    MIN_SCAN_INTERVAL,
    MIN_UPDATE_INTERVAL,
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


# Retained only so an existing YAML block can be imported. New installations
# configure the integration from the UI.
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
                vol.Optional(
                    CONF_MAX_MARKERS, default=DEFAULT_MAX_MARKERS
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                vol.Optional(CONF_LOCATION_KEYS): vol.All(cv.ensure_list, [cv.string]),
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
    """Import a legacy YAML block, if there is one."""
    if (conf := config.get(DOMAIN)) is None:
        return True

    import_data = dict(conf)
    # The YAML schema takes a timedelta; options are JSON, so store minutes.
    interval: timedelta = import_data.pop(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    import_data[CONF_UPDATE_INTERVAL] = max(
        MIN_UPDATE_INTERVAL, int(interval.total_seconds() // 60)
    )

    LOGGER.warning(
        "Configuring %s in configuration.yaml is deprecated. Your settings are "
        "being imported into a config entry — once Settings > Devices & services "
        "shows the integration, delete the '%s:' block from configuration.yaml",
        DOMAIN,
        DOMAIN,
    )
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    options = entry.options
    location_keys = tuple(options.get(CONF_LOCATION_KEYS) or DEFAULT_LOCATION_KEYS)

    coordinator = BpkCoordinator(
        hass,
        # Stable across restarts, unique to this installation: the API uses it
        # to attribute rate limits.
        app_id=entry.data.get(CONF_APP_ID) or f"ha-{uuid.getnode():x}",
        area=entry.data[CONF_AREA],
        municipalities=list(options.get(CONF_MUNICIPALITIES) or []),
        hours=int(options.get(CONF_HOURS, DEFAULT_HOURS)),
        max_pages=int(options.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES)),
        location_keys=location_keys,
        scan_interval=timedelta(
            minutes=int(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        ),
        entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        CONF_MAX_ATTRIBUTE_INCIDENTS: int(
            options.get(CONF_MAX_ATTRIBUTE_INCIDENTS, DEFAULT_MAX_ATTRIBUTE_INCIDENTS)
        ),
        CONF_MAX_MARKERS: int(options.get(CONF_MAX_MARKERS, DEFAULT_MAX_MARKERS)),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the options change, so a new interval takes effect at once."""
    await hass.config_entries.async_reload(entry.entry_id)
