"""Data coordinator for the local Brottsplatskartan integration."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BpkError,
    BpkRateLimited,
    Incident,
    async_fetch_incidents,
    filter_by_municipality,
    normalize_place,
)
from .const import DOMAIN, LOGGER


@dataclass(slots=True)
class BpkData:
    """Result of one refresh."""

    incidents: list[Incident]
    counts_by_type: dict[str, int]
    window_hours: int
    fetched_total: int
    #: Every distinct place string seen in the county before filtering. Exposed
    #: as a diagnostic so a municipality filter that matches nothing can be
    #: debugged without reading the raw API by hand.
    seen_places: list[str] = field(default_factory=list)


class BpkCoordinator(DataUpdateCoordinator[BpkData]):
    """Poll the Brottsplatskartan API on a rolling window."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        app_id: str,
        area: str,
        municipalities: list[str],
        hours: int,
        max_pages: int,
        location_keys: tuple[str, ...],
        scan_interval: timedelta,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=scan_interval,
        )
        self._session = async_get_clientsession(hass)
        self.app_id = app_id
        self.area = area
        self.hours = hours
        self.max_pages = max_pages
        self.location_keys = location_keys
        self.municipality_names = list(municipalities)
        self._municipality_filter = {
            norm
            for name in municipalities
            if (norm := normalize_place(name)) is not None
        }
        if municipalities and not self._municipality_filter:
            LOGGER.warning(
                "None of the configured municipalities %s could be used as a "
                "filter; counting the whole of %s instead",
                municipalities,
                area,
            )

    @property
    def label(self) -> str:
        """Human-readable name for the configured scope.

        Used to build entity names. This integration is set up from YAML, so it
        has no config entry, which means `device_info` is ignored and
        `has_entity_name` cannot borrow a device name — entity names have to be
        spelled out in full here.
        """
        if self.municipality_names:
            return ", ".join(self.municipality_names)
        return self.area

    async def _async_update_data(self) -> BpkData:
        """Fetch and filter the current window."""
        since = dt_util.utcnow() - timedelta(hours=self.hours)

        try:
            fetched = await async_fetch_incidents(
                self._session,
                app_id=self.app_id,
                area=self.area,
                since=since,
                max_pages=self.max_pages,
                location_keys=self.location_keys,
            )
        except BpkRateLimited as err:
            # Surface this distinctly: it means the poll interval is too short
            # for this app id, not that the service is down.
            raise UpdateFailed(str(err)) from err
        except BpkError as err:
            raise UpdateFailed(str(err)) from err

        # Frequency-ordered, not alphabetical: the location hierarchy is split
        # into components, so this list holds street names too. Municipalities
        # recur across incidents and therefore sort to the top, which is what
        # you actually want to copy into `municipalities`.
        place_counter = Counter(
            place for incident in fetched for place in incident.raw_places
        )
        seen_places = [place for place, _ in place_counter.most_common(50)]
        incidents = filter_by_municipality(fetched, self._municipality_filter)

        counts = Counter(
            incident.incident_type or "Okänd"
            for incident in incidents
        )

        LOGGER.debug(
            "Fetched %s incidents in %s for the last %sh, %s after filtering to %s",
            len(fetched),
            self.area,
            self.hours,
            len(incidents),
            self.municipality_names or "the whole county",
        )

        return BpkData(
            incidents=incidents,
            counts_by_type=dict(counts.most_common()),
            window_hours=self.hours,
            fetched_total=len(fetched),
            seen_places=seen_places,
        )
