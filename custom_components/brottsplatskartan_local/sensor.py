"""Sensor platform for the local Brottsplatskartan integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Incident
from .const import (
    ATTRIBUTION,
    DOMAIN,
    SERVICE_GET_INCIDENTS,
    SERVICE_REFRESH,
)
from .coordinator import BpkConfigEntry, BpkCoordinator

# Entity names are set with _attr_name rather than a translation key on
# purpose. A translation key would make Home Assistant derive the entity id
# from the *translated* name, so a Swedish installation would get different
# entity ids from an English one and any dashboard would break on a language
# change. The config UI is still translated; only these names are fixed.

ATTR_LIMIT = "limit"
ATTR_TYPE = "incident_type"
ATTR_WITHIN_KM = "within_km"

GET_INCIDENTS_SCHEMA = {
    vol.Optional(ATTR_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
    vol.Optional(ATTR_TYPE): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_WITHIN_KM): vol.All(
        vol.Coerce(float), vol.Range(min=0.01, max=1000)
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BpkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors and the integration's actions."""
    data = entry.runtime_data
    coordinator = data.coordinator

    platform = entity_platform.async_get_current_platform()
    # Registered here rather than in async_setup, since this integration has
    # no YAML setup. async_register_entity_service is a no-op if the service
    # already exists, so a second entry does not re-register them.
    platform.async_register_entity_service(
        SERVICE_REFRESH, None, "async_refresh_now"
    )
    platform.async_register_entity_service(
        SERVICE_GET_INCIDENTS,
        GET_INCIDENTS_SCHEMA,
        "async_get_incidents",
        supports_response=SupportsResponse.ONLY,
    )

    async_add_entities(
        [
            BpkIncidentCountSensor(coordinator, entry, data.max_attribute_incidents),
            BpkLatestIncidentSensor(coordinator, entry),
            BpkNearestIncidentSensor(coordinator, entry),
        ]
    )


def device_info(entry: BpkConfigEntry) -> DeviceInfo:
    """Group the entry's entities under one service device."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Brottsplatskartan",
        name=entry.title,
        configuration_url="https://brottsplatskartan.se/",
    )


class BpkEntity(CoordinatorEntity[BpkCoordinator]):
    """Shared wiring for this integration's coordinator entities."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: BpkCoordinator, entry: BpkConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_device_info = device_info(entry)


class BpkIncidentCountSensor(BpkEntity, SensorEntity):
    """Number of incidents in the rolling window."""

    _attr_name = "Incidents"
    _attr_icon = "mdi:police-badge"
    _attr_native_unit_of_measurement = "incidents"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: BpkCoordinator,
        entry: BpkConfigEntry,
        max_attribute_incidents: int,
    ) -> None:
        """Initialize the count sensor."""
        super().__init__(coordinator, entry)
        self._max_attribute_incidents = max_attribute_incidents
        self._attr_unique_id = f"{entry.entry_id}_incident_count"

    @property
    def native_value(self) -> int | None:
        """Return the incident count."""
        if (data := self.coordinator.data) is None:
            return None
        return len(data.incidents)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the per-type breakdown, the incident list and diagnostics."""
        if (data := self.coordinator.data) is None:
            return {}
        attributes: dict[str, Any] = {
            "window_hours": data.window_hours,
            "area": self.coordinator.area,
            "municipalities": self.coordinator.municipality_names,
            "by_type": data.counts_by_type,
            "fetched_in_county": data.fetched_total,
        }
        if self._max_attribute_incidents:
            attributes["incidents"] = [
                incident.as_dict()
                for incident in data.incidents[: self._max_attribute_incidents]
            ]
            attributes["truncated"] = (
                len(data.incidents) > self._max_attribute_incidents
            )
        # Diagnostic: if the municipality filter matches nothing, these are the
        # place names the API actually returned, which is what to match on.
        if not data.incidents and data.fetched_total:
            attributes["places_seen_in_county"] = data.seen_places[:50]
        return attributes

    async def async_refresh_now(self) -> None:
        """Action: fetch from the API immediately."""
        await self.coordinator.async_request_refresh()

    async def async_get_incidents(
        self,
        limit: int | None = None,
        incident_type: list[str] | None = None,
        within_km: float | None = None,
    ) -> ServiceResponse:
        """Action: return the current incidents as response data.

        Useful from a script or template without having to read a state
        attribute, and it is not capped by `max_attribute_incidents`.
        """
        data = self.coordinator.data
        incidents: list[Incident] = list(data.incidents) if data else []

        if incident_type:
            wanted = {name.casefold() for name in incident_type}
            incidents = [
                i for i in incidents
                if i.incident_type and i.incident_type.casefold() in wanted
            ]
        if within_km is not None:
            incidents = [
                i for i in incidents
                if i.distance_km is not None and i.distance_km <= within_km
            ]
        if limit is not None:
            incidents = incidents[:limit]

        return {
            "count": len(incidents),
            "area": self.coordinator.area,
            "municipalities": self.coordinator.municipality_names,
            "window_hours": data.window_hours if data else None,
            "incidents": [i.as_dict(include_image=True) for i in incidents],
        }


class BpkLatestIncidentSensor(BpkEntity, SensorEntity):
    """The most recent incident, as a human-readable headline."""

    _attr_name = "Latest incident"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: BpkCoordinator, entry: BpkConfigEntry) -> None:
        """Initialize the latest-incident sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_latest_incident"

    @property
    def native_value(self) -> str | None:
        """Return the newest incident's title, truncated to the state limit."""
        if (data := self.coordinator.data) is None or not data.incidents:
            return None
        # Home Assistant rejects states longer than 255 characters.
        return data.incidents[0].title[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the newest incident in full."""
        if (data := self.coordinator.data) is None or not data.incidents:
            return {}
        # Only one incident here, so the static-map images are affordable.
        return data.incidents[0].as_dict(include_image=True)


class BpkNearestIncidentSensor(BpkEntity, SensorEntity):
    """Distance from home to the closest incident.

    Replaces the template sensor this integration used to ask people to write
    by hand, so proximity automations need no YAML.
    """

    _attr_name = "Nearest incident"
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: BpkCoordinator, entry: BpkConfigEntry) -> None:
        """Initialize the nearest-incident sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nearest_incident"

    @property
    def native_value(self) -> float | None:
        """Return the distance in km, or None if nothing has coordinates."""
        if (data := self.coordinator.data) is None:
            return None
        return data.nearest_km

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the closest incident in full."""
        if (data := self.coordinator.data) is None or data.nearest is None:
            return {}
        return data.nearest.as_dict(include_image=True)
