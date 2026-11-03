"""Config and options flow for the local Brottsplatskartan integration."""

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
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
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
    CONF_MAX_ATTRIBUTE_INCIDENTS,
    CONF_MAX_MARKERS,
    CONF_MAX_PAGES,
    CONF_MUNICIPALITIES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_AREA,
    DEFAULT_HOURS,
    DEFAULT_MAX_ATTRIBUTE_INCIDENTS,
    DEFAULT_MAX_MARKERS,
    DEFAULT_MAX_PAGES,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER,
    MIN_UPDATE_INTERVAL,
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


def _tuning_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """The options shared by the config flow's second step and the options flow."""
    return {
        vol.Optional(
            CONF_HOURS, default=defaults.get(CONF_HOURS, DEFAULT_HOURS)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=168, step=1, unit_of_measurement="h",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_UPDATE_INTERVAL,
            default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_UPDATE_INTERVAL, max=1440, step=1, unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_MAX_ATTRIBUTE_INCIDENTS,
            default=defaults.get(
                CONF_MAX_ATTRIBUTE_INCIDENTS, DEFAULT_MAX_ATTRIBUTE_INCIDENTS
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=200, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(
            CONF_MAX_MARKERS,
            default=defaults.get(CONF_MAX_MARKERS, DEFAULT_MAX_MARKERS),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=500, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Optional(
            CONF_MAX_PAGES, default=defaults.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=40, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }


def _coerce_ints(options: dict[str, Any]) -> dict[str, Any]:
    """NumberSelector hands back floats; store whole numbers."""
    for key in (
        CONF_HOURS,
        CONF_UPDATE_INTERVAL,
        CONF_MAX_ATTRIBUTE_INCIDENTS,
        CONF_MAX_MARKERS,
        CONF_MAX_PAGES,
    ):
        if key in options:
            options[key] = int(options[key])
    return options


def _title(area: str, municipalities: list[str]) -> str:
    """Entry title, which also becomes the device name and entity prefix."""
    if municipalities:
        return f"{DEFAULT_NAME} {', '.join(municipalities)}"
    return f"{DEFAULT_NAME} {area}"


class BpkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two-step setup: pick a county, then pick places inside it."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._area: str = DEFAULT_AREA
        self._app_id: str = f"ha-{uuid.getnode():x}"
        self._discovered: list[str] = []
        self._discovery_failed: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the county to fetch."""
        if user_input is not None:
            self._area = user_input[CONF_AREA]
            await self._async_discover()
            return await self.async_step_places()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AREA, default=DEFAULT_AREA): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=AREAS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def _async_discover(self) -> None:
        """Ask the API which municipalities this county actually reports.

        A failure here is not fatal: the picker falls back to free text, which
        is all the filter needs anyway.
        """
        session = async_get_clientsession(self.hass)
        try:
            self._discovered, _ = await async_discover_municipalities(
                session, app_id=self._app_id, area=self._area
            )
            self._discovery_failed = None
        except BpkRateLimited:
            self._discovered = []
            self._discovery_failed = "rate_limited"
        except BpkError as err:
            LOGGER.debug("Could not discover municipalities for %s: %s", self._area, err)
            self._discovered = []
            self._discovery_failed = "cannot_connect"

    async def async_step_places(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick municipalities (or districts) and the polling options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            municipalities = [
                name.strip()
                for name in user_input.pop(CONF_MUNICIPALITIES, [])
                if name.strip()
            ]
            # Allow several entries for one county with different place sets,
            # but not two covering the same places.
            await self.async_set_unique_id(
                entry_unique_id(self._area, municipalities)
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(self._area, municipalities),
                data={CONF_AREA: self._area, CONF_APP_ID: self._app_id},
                options=_coerce_ints(
                    {**user_input, CONF_MUNICIPALITIES: municipalities}
                ),
            )

        schema: dict[Any, Any] = {
            vol.Optional(CONF_MUNICIPALITIES, default=[]): _municipality_selector(
                self._discovered
            ),
            **_tuning_schema({}),
        }
        return self.async_show_form(
            step_id="places",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "area": self._area,
                "found": (
                    ", ".join(self._discovered[:12])
                    if self._discovered
                    else "—"
                ),
            },
        )

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create an entry from a legacy `configuration.yaml` block."""
        area = import_data.get(CONF_AREA, DEFAULT_AREA)
        municipalities = list(import_data.get(CONF_MUNICIPALITIES) or [])
        await self.async_set_unique_id(entry_unique_id(area, municipalities))
        self._abort_if_unique_id_configured()

        options = {
            CONF_MUNICIPALITIES: municipalities,
            CONF_HOURS: import_data.get(CONF_HOURS, DEFAULT_HOURS),
            CONF_UPDATE_INTERVAL: import_data.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            ),
            CONF_MAX_ATTRIBUTE_INCIDENTS: import_data.get(
                CONF_MAX_ATTRIBUTE_INCIDENTS, DEFAULT_MAX_ATTRIBUTE_INCIDENTS
            ),
            CONF_MAX_MARKERS: import_data.get(CONF_MAX_MARKERS, DEFAULT_MAX_MARKERS),
            CONF_MAX_PAGES: import_data.get(CONF_MAX_PAGES, DEFAULT_MAX_PAGES),
        }
        return self.async_create_entry(
            title=_title(area, municipalities),
            data={
                CONF_AREA: area,
                CONF_APP_ID: import_data.get(CONF_APP_ID)
                or f"ha-{uuid.getnode():x}",
            },
            options=_coerce_ints(options),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BpkOptionsFlow:
        """Return the options flow."""
        return BpkOptionsFlow()


class BpkOptionsFlow(OptionsFlow):
    """Change places and polling without restarting Home Assistant."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the current options, with a freshly discovered place list."""
        entry = self.config_entry
        area: str = entry.data[CONF_AREA]
        current: dict[str, Any] = dict(entry.options)

        if user_input is not None:
            municipalities = [
                name.strip()
                for name in user_input.pop(CONF_MUNICIPALITIES, [])
                if name.strip()
            ]
            options = _coerce_ints(
                {**user_input, CONF_MUNICIPALITIES: municipalities}
            )
            # Keep the title and the unique id in step with the places being
            # watched: the title so device and entity names stay meaningful,
            # the unique id so a later entry covering the same places is still
            # recognised as a duplicate.
            self.hass.config_entries.async_update_entry(
                entry,
                title=_title(area, municipalities),
                unique_id=entry_unique_id(area, municipalities),
            )
            return self.async_create_entry(data=options)

        discovered: list[str] = []
        try:
            discovered, _ = await async_discover_municipalities(
                async_get_clientsession(self.hass),
                app_id=entry.data[CONF_APP_ID],
                area=area,
            )
        except BpkError as err:
            LOGGER.debug("Options flow could not list municipalities: %s", err)

        # Anything already configured must stay selectable even if it did not
        # turn up in this round of discovery (quiet municipality, or a district
        # that discovery never lists).
        configured: list[str] = list(current.get(CONF_MUNICIPALITIES) or [])
        options_list = discovered + [m for m in configured if m not in discovered]

        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_MUNICIPALITIES, default=configured
            ): _municipality_selector(options_list),
            **_tuning_schema(current),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders={"area": area},
        )
