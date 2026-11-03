"""Stub of homeassistant.helpers.update_coordinator."""
from typing import Generic, TypeVar

_DataT = TypeVar("_DataT")


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator(Generic[_DataT]):
    """Generic, so `DataUpdateCoordinator[BpkData]` subscripts like the real one."""

    def __init__(self, hass, logger, *, config_entry=None, name=None,
                 update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.config_entry = config_entry
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self._listeners = {}

    def async_add_listener(self, update_callback, context=None):
        self._listeners[update_callback] = context
        return lambda: self._listeners.pop(update_callback, None)


class CoordinatorEntity(Generic[_DataT]):
    def __init__(self, coordinator, context=None):
        self.coordinator = coordinator
