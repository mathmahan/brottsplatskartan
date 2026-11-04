"""Config, reconfigure and options flow for the local Brottsplatskartan integration.

Everything is set from the UI: the county through the config and reconfigure
flows, and every other setting through the options flow. There is no YAML.
"""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DEFAULT_LOCATION_KEYS,
    BpkError,
    BpkRateLimited,
    async_discover_municipalities,
    entry_unique_id,
)
from .const import (
    AREAS,
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
    DEFAULT_AREA,
    DEFAULT_HOURS,
    DEFAULT_MAX_ATTRIBUTE_INCIDENTS,
    DEFAULT_MAX_MARKERS,
    DEFAULT_MAX_PAGES,
    DEFAULT_NAME,
    DEFAULT_NEARBY_RADIUS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER,
    MIN_UPDATE_INTERVAL,
    SECTION_ADVANCED,
)

#: Numeric options come back from NumberSelector as floats and have to be
#: stored as ints, except the radius which is genuinely fractional.
INT_OPTIONS = (
    CONF_HOURS,
    CONF_UPDATE_INTERVAL,
    CONF_MAX_ATTRIBUTE_INCIDENTS,
    CONF_MAX_MARKERS,
    CONF_MAX_PAGES,
)


def _area_selector() -> selector.SelectSelector:
    """Dropdown of the 21 counties the API accepts."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=AREAS, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _municipality_selector(options: list[str]) -> selector.SelectSelector:
    """Multi-select of discovered municipalities, open to typed-in values.

    `custom_value` matters: the filter also matches districts and street names
    ("Kungsholmen", "Södermalm"), which are too numerous to list but which a
    user may well want. Discovery only offers the kommun names.
    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
            sort=False,
        )
    )


def _number(
    minimum: float, maximum: float, step: float = 1, unit: str | None = None
) -> selector.NumberSelector:
    """A plain number box."""
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _settings_schema(
    defaults: dict[str, Any], *, places: list[str], app_id: str
) -> vol.Schema:
    """Everything except the county, as one form with a collapsed advanced part.

    Shared by the config flow's second step, the reconfigure flow and the
    options flow, so the three can never drift apart.
    """
    advanced = {
        vol.Optional(
            CONF_MAX_ATTRIBUTE_INCIDENTS,
            default=defaults.get(
                CONF_MAX_ATTRIBUTE_INCIDENTS, DEFAULT_MAX_ATTRIBUTE_INCIDENTS
            ),
        ): _number(0, 200),
        vol.Optional(
            CONF_MAX_MARKERS,
            default=defaults.get(CONF_MAX_MARKERS, DEFAULT_MAX_MARKERS),
        ): _number(0, 500),
        vol.Optional(
            CONF_MAX_PAGES, default=defaults.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES)
        ): _number(1, 40),
        vol.Optional(
            CONF_LOCATION_KEYS,
            default=list(defaults.get(CONF_LOCATION_KEYS) or DEFAULT_LOCATION_KEYS),
        ): selector.TextSelector(selector.TextSelectorConfig(multiple=True)),
        vol.Optional(CONF_APP_ID, default=app_id): selector.TextSelector(),
    }
    return vol.Schema(
        {
            vol.Optional(
                CONF_MUNICIPALITIES,
                default=list(defaults.get(CONF_MUNICIPALITIES) or []),
            ): _municipality_selector(places),
            vol.Optional(
                CONF_HOURS, default=defaults.get(CONF_HOURS, DEFAULT_HOURS)
            ): _number(1, 168, unit="h"),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): _number(MIN_UPDATE_INTERVAL, 1440, unit="min"),
            vol.Optional(
                CONF_NEARBY_RADIUS,
                default=defaults.get(CONF_NEARBY_RADIUS, DEFAULT_NEARBY_RADIUS),
            ): _number(0.1, 100, step=0.1, unit="km"),
            vol.Required(SECTION_ADVANCED): section(
                vol.Schema(advanced), {"collapsed": True}
            ),
        }
    )


def parse_settings(user_input: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Turn a submitted settings form into stored options, plus the app id.

    The advanced fields arrive nested under their section key; they are
    flattened back out so the stored options keep one flat shape. The app id
    belongs in the entry's data rather than its options, so it is returned
    separately.
    """
    submitted = dict(user_input)
    advanced = dict(submitted.pop(SECTION_ADVANCED, None) or {})
    app_id = advanced.pop(CONF_APP_ID, None)
    options: dict[str, Any] = {**submitted, **advanced}

    options[CONF_MUNICIPALITIES] = [
        name.strip()
        for name in (options.get(CONF_MUNICIPALITIES) or [])
        if name.strip()
    ]
    options[CONF_LOCATION_KEYS] = [
        key.strip()
        for key in (options.get(CONF_LOCATION_KEYS) or [])
        if key.strip()
    ] or list(DEFAULT_LOCATION_KEYS)

    for key in INT_OPTIONS:
        if key in options:
            options[key] = int(options[key])
    if CONF_NEARBY_RADIUS in options:
        options[CONF_NEARBY_RADIUS] = round(float(options[CONF_NEARBY_RADIUS]), 2)

    return options, (app_id.strip() if isinstance(app_id, str) and app_id.strip() else None)


def entry_title(area: str, municipalities: list[str]) -> str:
    """Entry title, which also becomes the device name and entity prefix."""
    if municipalities:
        return f"{DEFAULT_NAME} {', '.join(municipalities)}"
    return f"{DEFAULT_NAME} {area}"


class BpkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two steps: pick a county, then narrow it down and tune it."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._area: str = DEFAULT_AREA
        self._app_id: str = f"ha-{uuid.getnode():x}"
        self._discovered: list[str] = []

    # ---------------------------------------------------------------- helpers

    async def _async_discover(self) -> None:
        """Ask the API which municipalities this county actually reports.

        A failure here is not fatal: the picker falls back to free text, which
        is all the filter needs anyway.
        """
        try:
            self._discovered, _ = await async_discover_municipalities(
                async_get_clientsession(self.hass),
                app_id=self._app_id,
                area=self._area,
            )
        except BpkRateLimited:
            LOGGER.debug("Rate limited while listing municipalities")
            self._discovered = []
        except BpkError as err:
            LOGGER.debug("Could not list municipalities for %s: %s", self._area, err)
            self._discovered = []

    def _settings_form(
        self, step_id: str, defaults: dict[str, Any]
    ) -> ConfigFlowResult:
        """Show the shared settings form."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=_settings_schema(
                defaults, places=self._discovered, app_id=self._app_id
            ),
            description_placeholders={
                "area": self._area,
                "found": ", ".join(self._discovered[:12]) or "—",
            },
        )

    def _unique_id_taken(self, unique_id: str, *, exclude: str | None = None) -> bool:
        """Is another entry already covering exactly these places?"""
        return any(
            other.unique_id == unique_id and other.entry_id != exclude
            for other in self.hass.config_entries.async_entries(DOMAIN)
        )

    # ------------------------------------------------------------------ setup

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the county to fetch."""
        if user_input is not None:
            self._area = user_input[CONF_AREA]
            await self._async_discover()
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_AREA, default=DEFAULT_AREA): _area_selector()}
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Narrow the county down and tune the rest."""
        if user_input is None:
            return self._settings_form("settings", {})

        options, app_id = parse_settings(user_input)
        municipalities = options[CONF_MUNICIPALITIES]

        # Several entries for one county are allowed, with different place
        # sets, but not two covering the same places.
        await self.async_set_unique_id(entry_unique_id(self._area, municipalities))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=entry_title(self._area, municipalities),
            data={CONF_AREA: self._area, CONF_APP_ID: app_id or self._app_id},
            options=options,
        )

    # ------------------------------------------------------------ reconfigure

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the county of an existing entry, then its settings.

        Without this the county would be the one thing needing a delete and
        re-add, since it is the only setting that lives in the entry's data.
        """
        entry = self._get_reconfigure_entry()
        self._app_id = entry.data.get(CONF_APP_ID) or self._app_id

        if user_input is not None:
            self._area = user_input[CONF_AREA]
            await self._async_discover()
            return await self.async_step_reconfigure_settings()

        self._area = entry.data.get(CONF_AREA, DEFAULT_AREA)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_AREA, default=self._area): _area_selector()}
            ),
        )

    async def async_step_reconfigure_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pick places and settings for a reconfigured entry."""
        entry = self._get_reconfigure_entry()

        if user_input is None:
            # Keep whatever is already configured as the starting point, and
            # make sure it stays selectable even if discovery did not list it.
            configured = list(entry.options.get(CONF_MUNICIPALITIES) or [])
            self._discovered += [
                name for name in configured if name not in self._discovered
            ]
            return self._settings_form("reconfigure_settings", dict(entry.options))

        options, app_id = parse_settings(user_input)
        municipalities = options[CONF_MUNICIPALITIES]
        unique_id = entry_unique_id(self._area, municipalities)
        if self._unique_id_taken(unique_id, exclude=entry.entry_id):
            return self.async_abort(reason="already_configured")

        return self.async_update_reload_and_abort(
            entry,
            unique_id=unique_id,
            title=entry_title(self._area, municipalities),
            data={CONF_AREA: self._area, CONF_APP_ID: app_id or self._app_id},
            options=options,
        )

    # ---------------------------------------------------------------- options

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BpkOptionsFlow:
        """Return the options flow."""
        return BpkOptionsFlow()


class BpkOptionsFlow(OptionsFlow):
    """Change places and tuning without restarting Home Assistant."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the current settings, with a freshly discovered place list."""
        entry = self.config_entry
        area: str = entry.data[CONF_AREA]
        app_id: str = entry.data.get(CONF_APP_ID, "")

        if user_input is not None:
            options, new_app_id = parse_settings(user_input)
            municipalities = options[CONF_MUNICIPALITIES]
            unique_id = entry_unique_id(area, municipalities)

            if any(
                other.unique_id == unique_id and other.entry_id != entry.entry_id
                for other in self.hass.config_entries.async_entries(DOMAIN)
            ):
                return self.async_abort(reason="already_configured")

            # Keep the title and unique id in step with the places being
            # watched: the title so device and entity names stay meaningful,
            # the unique id so a later entry over the same places is still
            # recognised as a duplicate. The app id lives in data, not options.
            data = dict(entry.data)
            if new_app_id:
                data[CONF_APP_ID] = new_app_id
            self.hass.config_entries.async_update_entry(
                entry,
                title=entry_title(area, municipalities),
                unique_id=unique_id,
                data=data,
            )
            return self.async_create_entry(data=options)

        discovered: list[str] = []
        try:
            discovered, _ = await async_discover_municipalities(
                async_get_clientsession(self.hass), app_id=app_id or "ha", area=area
            )
        except BpkError as err:
            LOGGER.debug("Options flow could not list municipalities: %s", err)

        # Anything already configured must stay selectable even if it did not
        # turn up in this round of discovery (a quiet municipality, or a
        # district that discovery never lists).
        configured = list(entry.options.get(CONF_MUNICIPALITIES) or [])
        places = discovered + [m for m in configured if m not in discovered]

        return self.async_show_form(
            step_id="init",
            data_schema=_settings_schema(
                dict(entry.options), places=places, app_id=app_id
            ),
            description_placeholders={
                "area": area,
                "found": ", ".join(discovered[:12]) or "—",
            },
        )
