"""Event platform: fires when a previously unseen incident shows up."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import ATTRIBUTION, DOMAIN, EVENT_NEW_INCIDENT, LOGGER
from .coordinator import BpkCoordinator

EVENT_TYPE_NEW_INCIDENT = "new_incident"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the event entity."""
    if discovery_info is None:
        return
    coordinator: BpkCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([BpkNewIncidentEvent(coordinator)])


class BpkNewIncidentEvent(EventEntity):
    """Triggers once per newly seen incident."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:bell-alert"
    _attr_should_poll = False
    _attr_event_types = [EVENT_TYPE_NEW_INCIDENT]

    def __init__(self, coordinator: BpkCoordinator) -> None:
        """Initialize the event entity."""
        self._coordinator = coordinator
        self._attr_name = f"Brottsplatskartan {coordinator.label} new incident"
        self._attr_unique_id = f"{coordinator.app_id}_new_incident"
        self._seen: set[str] = set()
        self._primed = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        # Seed from whatever is already in the window so a restart does not
        # replay the last 24 hours as "new".
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        """Fire for each incident not seen before."""
        if (data := self._coordinator.data) is None:
            return

        current = {incident.uid for incident in data.incidents}

        if not self._primed:
            self._seen = current
            self._primed = True
            LOGGER.debug("Primed with %s existing incidents", len(current))
            return

        # Oldest first, so the entity's final state is the newest incident.
        fresh = [
            incident for incident in reversed(data.incidents)
            if incident.uid not in self._seen
        ]

        # Track exactly what is in the window, so ids that age out are
        # forgotten instead of growing this set without bound.
        self._seen = current

        for incident in fresh:
            # Images are included here but not in the sensor's incident list:
            # one event carries one incident, so the long static-map URLs are
            # affordable, and they make a notification with a map thumbnail
            # possible.
            payload = incident.as_dict(include_image=True)
            self._trigger_event(EVENT_TYPE_NEW_INCIDENT, payload)
            # Also put it on the event bus, which is easier to consume from an
            # automation that wants every incident rather than just the last.
            self.hass.bus.async_fire(EVENT_NEW_INCIDENT, payload)

        if fresh:
            LOGGER.debug("Fired %s new incident events", len(fresh))
            self.async_write_ha_state()
