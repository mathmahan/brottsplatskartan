"""Binary sensor platform: is there an incident close to home?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_NEARBY_RADIUS
from .coordinator import BpkConfigEntry, BpkCoordinator
from .sensor import BpkEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BpkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the proximity binary sensor."""
    data = entry.runtime_data
    async_add_entities(
        [BpkIncidentNearbyBinarySensor(data.coordinator, entry, data.nearby_radius)]
    )


class BpkIncidentNearbyBinarySensor(BpkEntity, BinarySensorEntity):
    """On when the closest incident is within the configured radius.

    The radius is an option, so a proximity automation needs no template and
    no YAML — trigger on this entity turning on.
    """

    _attr_name = "Incident nearby"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(
        self, coordinator: BpkCoordinator, entry: BpkConfigEntry, radius_km: float
    ) -> None:
        """Initialize the proximity sensor."""
        super().__init__(coordinator, entry)
        self._radius_km = radius_km
        self._attr_unique_id = f"{entry.entry_id}_incident_nearby"

    @property
    def is_on(self) -> bool | None:
        """Return True when something happened inside the radius."""
        if (data := self.coordinator.data) is None:
            return None
        if data.nearest_km is None:
            # Nothing with coordinates in the window. That is a definite "no
            # incident nearby", not an unknown.
            return False
        return data.nearest_km <= self._radius_km

    @property
    def icon(self) -> str:
        """Use a louder icon while it is on."""
        return "mdi:map-marker-alert" if self.is_on else "mdi:map-marker-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the radius and, when on, the incident that tripped it."""
        attributes: dict[str, Any] = {CONF_NEARBY_RADIUS: self._radius_km}
        if (data := self.coordinator.data) is None:
            return attributes
        attributes["distance_km"] = data.nearest_km
        if self.is_on and data.nearest is not None:
            attributes.update(data.nearest.as_dict(include_image=True))
        return attributes
