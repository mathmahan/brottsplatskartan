"""Geolocation platform: one map marker per incident."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.location import distance as distance_in_metres

from .api import Incident
from .const import ATTRIBUTION, CONF_MAX_MARKERS, DOMAIN, LOGGER
from .coordinator import BpkCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the geolocation markers for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = BpkGeoLocationManager(
        hass, data["coordinator"], async_add_entities, data[CONF_MAX_MARKERS]
    )
    manager.async_setup()
    entry.async_on_unload(manager.async_shutdown)


class BpkGeoLocationManager:
    """Add and remove marker entities as incidents come and go."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: BpkCoordinator,
        async_add_entities: AddConfigEntryEntitiesCallback,
        max_markers: int,
    ) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._coordinator = coordinator
        self._async_add_entities = async_add_entities
        self._max_markers = max_markers
        self._entities: dict[str, BpkGeoLocationEvent] = {}
        self._unsub: Callable[[], None] | None = None

    @callback
    def async_setup(self) -> None:
        """Subscribe to coordinator updates and seed the current incidents."""
        self._unsub = self._coordinator.async_add_listener(self._async_sync)
        self._async_sync()

    @callback
    def async_shutdown(self) -> None:
        """Stop listening when the entry unloads."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _async_sync(self) -> None:
        """Reconcile entities against the current incident set."""
        data = self._coordinator.data
        incidents: dict[str, Incident] = {}
        if data is not None:
            # Not every incident carries coordinates; those simply get no
            # marker rather than being placed at 0,0.
            # Capped: a wide window over a whole county can return hundreds of
            # incidents, and one entity each would flood the state machine.
            # data.incidents is newest-first, so the cap keeps the newest.
            located = [
                incident
                for incident in data.incidents
                if incident.latitude is not None and incident.longitude is not None
            ]
            if self._max_markers and len(located) > self._max_markers:
                LOGGER.debug(
                    "Capping %s located incidents to %s markers",
                    len(located),
                    self._max_markers,
                )
                located = located[: self._max_markers]
            incidents = {incident.uid: incident for incident in located}

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

    # Deliberately no unique_id. These entities are transient — one per
    # incident, replaced as the window moves — and a unique_id would leave a
    # permanent entity-registry entry behind for every incident ever seen,
    # which is thousands of orphans over a few months. The built-in feed
    # integrations (usgs_earthquakes_feed, gdacs) omit it for the same reason.

    def __init__(self, hass: HomeAssistant, incident: Incident) -> None:
        """Initialize the marker."""
        self._incident = incident
        self._apply(hass, incident)

    def _apply(self, hass: HomeAssistant, incident: Incident) -> None:
        """Copy the incident into the entity's geolocation fields."""
        self._incident = incident
        # Short label: the marker name is what shows on the map, and the full
        # headline is far too long for it. The headline lives in the
        # attributes, which is what the more-info dialog shows on click.
        place = incident.place or incident.municipality
        self._attr_name = (
            f"{incident.incident_type}: {place}"
            if incident.incident_type and place
            else incident.title
        )
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
        """Return the incident detail shown in the more-info dialog."""
        incident = self._incident
        return {
            key: value
            for key, value in (
                ("incident_id", incident.uid),
                ("headline", incident.title),
                ("type", incident.incident_type),
                ("description", incident.description),
                ("published", incident.published.isoformat()),
                ("date_human", incident.date_human),
                ("place", incident.place),
                ("municipality", incident.municipality),
                ("location", incident.location),
                ("url", incident.url),
                ("source_url", incident.source_url),
                ("image", incident.image_wide),
            )
            if value is not None
        }
