"""Geolocation platform: one map marker per incident."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util.location import distance as distance_in_metres

from .api import Incident
from .const import ATTRIBUTION, DOMAIN, LOGGER
from .coordinator import BpkCoordinator


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the geolocation markers."""
    if discovery_info is None:
        return
    coordinator: BpkCoordinator = hass.data[DOMAIN]["coordinator"]
    BpkGeoLocationManager(hass, coordinator, async_add_entities).async_setup()


class BpkGeoLocationManager:
    """Add and remove marker entities as incidents come and go."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: BpkCoordinator,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._coordinator = coordinator
        self._async_add_entities = async_add_entities
        self._entities: dict[str, BpkGeoLocationEvent] = {}
        self._unsub: Callable[[], None] | None = None

    @callback
    def async_setup(self) -> None:
        """Subscribe to coordinator updates and seed the current incidents."""
        self._unsub = self._coordinator.async_add_listener(self._async_sync)
        self._async_sync()

    @callback
    def _async_sync(self) -> None:
        """Reconcile entities against the current incident set."""
        data = self._coordinator.data
        incidents: dict[str, Incident] = {}
        if data is not None:
            # Not every incident carries coordinates; those simply get no
            # marker rather than being placed at 0,0.
            incidents = {
                incident.uid: incident
                for incident in data.incidents
                if incident.latitude is not None and incident.longitude is not None
            }

        for uid in set(self._entities) - set(incidents):
            entity = self._entities.pop(uid)
            self._hass.async_create_task(entity.async_remove(force_remove=True))

        new: list[BpkGeoLocationEvent] = []
        for uid, incident in incidents.items():
            if (existing := self._entities.get(uid)) is not None:
                existing.async_update_incident(incident)
                continue
            entity = BpkGeoLocationEvent(self._hass, incident)
            self._entities[uid] = entity
            new.append(entity)

        if new:
            LOGGER.debug("Adding %s geo_location markers", len(new))
            self._async_add_entities(new)


class BpkGeoLocationEvent(GeolocationEvent):
    """One incident as a map marker.

    Follows the convention of the built-in feed integrations: the geolocation
    values are written to the `_attr_*` backing fields rather than overriding
    the cached properties on the base class.
    """

    _attr_attribution = ATTRIBUTION
    _attr_should_poll = False
    _attr_icon = "mdi:alert"
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, hass: HomeAssistant, incident: Incident) -> None:
        """Initialize the marker."""
        self._incident = incident
        self._attr_unique_id = f"{DOMAIN}_{incident.uid}"
        self._apply(hass, incident)

    def _apply(self, hass: HomeAssistant, incident: Incident) -> None:
        """Copy the incident into the entity's geolocation fields."""
        self._incident = incident
        self._attr_name = incident.title
        self._attr_latitude = incident.latitude
        self._attr_longitude = incident.longitude

        metres = distance_in_metres(
            hass.config.latitude,
            hass.config.longitude,
            incident.latitude,
            incident.longitude,
        )
        self._attr_distance = None if metres is None else round(metres / 1000, 2)

    @callback
    def async_update_incident(self, incident: Incident) -> None:
        """Refresh the backing incident, in case the API revised it."""
        self._apply(self.hass, incident)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the incident detail."""
        return {
            key: value
            for key, value in (
                ("incident_id", self._incident.uid),
                ("type", self._incident.incident_type),
                ("published", self._incident.published.isoformat()),
                ("municipality", self._incident.municipality),
                ("url", self._incident.url),
                ("description", self._incident.description),
            )
            if value is not None
        }
