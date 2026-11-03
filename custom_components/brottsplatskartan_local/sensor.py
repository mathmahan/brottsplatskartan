"""Sensor platform for the local Brottsplatskartan integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_MAX_ATTRIBUTE_INCIDENTS, DOMAIN
from .coordinator import BpkCoordinator


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the sensor from the YAML-configured integration."""
    if discovery_info is None:
        return
    data = hass.data[DOMAIN]
    async_add_entities(
        [
            BpkIncidentCountSensor(
                data["coordinator"], data[CONF_MAX_ATTRIBUTE_INCIDENTS]
            ),
            BpkLatestIncidentSensor(data["coordinator"]),
        ]
    )


class BpkIncidentCountSensor(CoordinatorEntity[BpkCoordinator], SensorEntity):
    """Number of incidents in the rolling window."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:police-badge"
    _attr_native_unit_of_measurement = "incidents"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BpkCoordinator, max_attribute_incidents: int) -> None:
        """Initialize the count sensor."""
        super().__init__(coordinator)
        self._max_attribute_incidents = max_attribute_incidents
        self._attr_name = f"Brottsplatskartan {coordinator.label} incidents"
        self._attr_unique_id = f"{coordinator.app_id}_incident_count"

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


class BpkLatestIncidentSensor(CoordinatorEntity[BpkCoordinator], SensorEntity):
    """The most recent incident, as a human-readable headline."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: BpkCoordinator) -> None:
        """Initialize the latest-incident sensor."""
        super().__init__(coordinator)
        self._attr_name = f"Brottsplatskartan {coordinator.label} latest incident"
        self._attr_unique_id = f"{coordinator.app_id}_latest_incident"

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
