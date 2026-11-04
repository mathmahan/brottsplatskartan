"""The local Brottsplatskartan integration.

Configured entirely from the UI. There is no YAML configuration: everything,
including the county, is editable under Settings > Devices & services.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, issue_registry as ir

from .api import DEFAULT_LOCATION_KEYS, entry_unique_id, normalized_places
from .const import (
    CONF_APP_ID,
    CONF_AREA,
    CONF_HOURS,
    CONF_LOCATION_KEYS,
    CONF_MAX_ATTRIBUTE_INCIDENTS,
    CONF_MAX_MARKERS,
    CONF_MAX_PAGES,
    CONF_MUNICIPALITIES,
    CONF_NEARBY_RADIUS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HOURS,
    DEFAULT_MAX_ATTRIBUTE_INCIDENTS,
    DEFAULT_MAX_MARKERS,
    DEFAULT_MAX_PAGES,
    DEFAULT_NEARBY_RADIUS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ISSUE_DUPLICATE_ENTRIES,
    ISSUE_OVERLAPPING_ENTRIES,
    LOGGER,
    PLATFORMS,
)
from .coordinator import BpkConfigEntry, BpkCoordinator, BpkRuntimeData

TROUBLESHOOTING_URL = (
    "https://github.com/mathmahan/brottsplatskartan"
    "#every-incident-appears-twice-on-the-map"
)

# This integration has no YAML configuration. The helper makes Home Assistant
# raise a repair issue pointing at the Add integration page if a leftover
# `brottsplatskartan_local:` block is still in configuration.yaml, rather than
# failing quietly or noisily.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _check_for_overlapping_entries(
    hass: HomeAssistant, entry: BpkConfigEntry, area: str, municipalities: list[str]
) -> None:
    """Raise a repair issue when another entry covers some of the same incidents.

    Two entries over overlapping areas are a legitimate configuration — a
    municipality and its whole county, say — but each produces its own map
    marker per incident, so the shared incidents appear twice. That looks like
    a bug in the integration, and the map alone gives no way to tell, so say so
    in Settings > Repairs where it will actually be seen.
    """
    issue_id = f"{ISSUE_OVERLAPPING_ENTRIES}_{entry.entry_id}"
    places = normalized_places(municipalities)
    overlapping: list[str] = []

    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id == entry.entry_id or other.data.get(CONF_AREA) != area:
            continue
        other_places = normalized_places(
            list(other.options.get(CONF_MUNICIPALITIES) or [])
        )
        # An empty set means the whole county, which overlaps everything in it.
        if not places or not other_places or (places & other_places):
            overlapping.append(other.title)

    if not overlapping:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    LOGGER.warning(
        "'%s' covers some of the same incidents as %s; incidents in both will "
        "appear more than once on the map",
        entry.title,
        " and ".join(f"'{title}'" for title in overlapping),
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_OVERLAPPING_ENTRIES,
        translation_placeholders={
            "entry": entry.title,
            "others": ", ".join(overlapping),
            "area": area,
        },
        learn_more_url=TROUBLESHOOTING_URL,
    )


def _backfill_unique_id(
    hass: HomeAssistant, entry: BpkConfigEntry, area: str, municipalities: list[str]
) -> None:
    """Give an entry created before unique ids existed one now.

    Without it such an entry sits outside the duplicate check, and a second
    entry over the same places can still be created beside it.
    """
    issue_id = f"{ISSUE_DUPLICATE_ENTRIES}_{entry.entry_id}"
    if entry.unique_id is not None:
        return

    unique_id = entry_unique_id(area, municipalities)
    clash = next(
        (
            other
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id and other.unique_id == unique_id
        ),
        None,
    )
    if clash is not None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DUPLICATE_ENTRIES,
            translation_placeholders={"entry": entry.title, "other": clash.title},
            learn_more_url=TROUBLESHOOTING_URL,
        )
        return

    ir.async_delete_issue(hass, DOMAIN, issue_id)
    hass.config_entries.async_update_entry(entry, unique_id=unique_id)


async def async_setup_entry(hass: HomeAssistant, entry: BpkConfigEntry) -> bool:
    """Set up a config entry."""
    options = entry.options
    area: str = entry.data[CONF_AREA]
    municipalities = list(options.get(CONF_MUNICIPALITIES) or [])
    location_keys = tuple(options.get(CONF_LOCATION_KEYS) or DEFAULT_LOCATION_KEYS)

    _backfill_unique_id(hass, entry, area, municipalities)
    _check_for_overlapping_entries(hass, entry, area, municipalities)

    coordinator = BpkCoordinator(
        hass,
        # Stable across restarts, unique to this installation: the API uses it
        # to attribute rate limits.
        app_id=entry.data.get(CONF_APP_ID) or f"ha-{uuid.getnode():x}",
        area=area,
        municipalities=municipalities,
        hours=int(options.get(CONF_HOURS, DEFAULT_HOURS)),
        max_pages=int(options.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES)),
        location_keys=location_keys,
        scan_interval=timedelta(
            minutes=int(options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        ),
        entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = BpkRuntimeData(
        coordinator=coordinator,
        max_attribute_incidents=int(
            options.get(CONF_MAX_ATTRIBUTE_INCIDENTS, DEFAULT_MAX_ATTRIBUTE_INCIDENTS)
        ),
        max_markers=int(options.get(CONF_MAX_MARKERS, DEFAULT_MAX_MARKERS)),
        nearby_radius=float(options.get(CONF_NEARBY_RADIUS, DEFAULT_NEARBY_RADIUS)),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BpkConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: BpkConfigEntry) -> None:
    """Clean up this entry's repair issues when it is deleted."""
    for prefix in (ISSUE_OVERLAPPING_ENTRIES, ISSUE_DUPLICATE_ENTRIES):
        ir.async_delete_issue(hass, DOMAIN, f"{prefix}_{entry.entry_id}")
    # A remaining entry may have been flagged only because of this one, so let
    # the others re-evaluate on their next setup.
    for other in hass.config_entries.async_entries(DOMAIN):
        ir.async_delete_issue(
            hass, DOMAIN, f"{ISSUE_OVERLAPPING_ENTRIES}_{other.entry_id}"
        )
        await hass.config_entries.async_reload(other.entry_id)


async def async_reload_entry(hass: HomeAssistant, entry: BpkConfigEntry) -> None:
    """Reload when the options change, so a new interval takes effect at once."""
    await hass.config_entries.async_reload(entry.entry_id)
