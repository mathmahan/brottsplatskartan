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
from homeassistant.util.location import distance as distance_in_metres

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
class BpkRuntimeData:
    """Everything the platforms need, hung off the config entry."""

    coordinator: BpkCoordinator
    max_attribute_incidents: int
    max_markers: int
    nearby_radius: float


#: A config entry for this integration, with its runtime data typed.
type BpkConfigEntry = ConfigEntry[BpkRuntimeData]


@dataclass(slots=True)
class BpkData:
    """Result of one refresh."""

    incidents: list[Incident]
    counts_by_type: dict[str, int]
    window_hours: int
    fetched_total: int
    #: The closest incident that has coordinates, and its distance in km.
    nearest: Incident | None = None
    nearest_km: float | None = None
    #: Every distinct place string seen in the county before filtering,
    #: most frequent first. Exposed as a diagnostic so a municipality filter
    #: that matches nothing can be debugged without reading the raw API.
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
        """Human-readable name for the configured scope."""
        if self.municipality_names:
            return ", ".join(self.municipality_names)
        return self.area

    def _apply_distances(self, incidents: list[Incident]) -> tuple[Incident | None, float | None]:
        """Fill in each incident's distance from home and return the nearest.

        Done once here rather than in each entity, so the markers, the
        nearest-incident sensor and the proximity binary sensor all agree.
        """
        home_lat = self.hass.config.latitude
        home_lon = self.hass.config.longitude
        nearest: Incident | None = None

        for incident in incidents:
            if incident.latitude is None or incident.longitude is None:
                incident.distance_km = None
                continue
            metres = distance_in_metres(
                home_lat, home_lon, incident.latitude, incident.longitude
            )
            if metres is None:
                incident.distance_km = None
                continue
            incident.distance_km = round(metres / 1000, 2)
            if nearest is None or incident.distance_km < nearest.distance_km:
                nearest = incident

        return nearest, nearest.distance_km if nearest else None

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
        # you actually want to copy into the municipality filter.
        place_counter = Counter(
            place for incident in fetched for place in incident.raw_places
        )
        seen_places = [place for place, _ in place_counter.most_common(50)]

        incidents = filter_by_municipality(fetched, self._municipality_filter)
        nearest, nearest_km = self._apply_distances(incidents)
        counts = Counter(
            incident.incident_type or "Okänd" for incident in incidents
        )

        LOGGER.debug(
            "Fetched %s incidents in %s for the last %sh, %s after filtering to %s"
            "%s",
            len(fetched),
            self.area,
            self.hours,
            len(incidents),
            self.municipality_names or "the whole county",
            f", nearest {nearest_km} km" if nearest_km is not None else "",
        )

        return BpkData(
            incidents=incidents,
            counts_by_type=dict(counts.most_common()),
            window_hours=self.hours,
            fetched_total=len(fetched),
            nearest=nearest,
            nearest_km=nearest_km,
            seen_places=seen_places,
        )
