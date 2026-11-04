"""Drive the real config, reconfigure and options flows."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.brottsplatskartan_local.const import DOMAIN

SETTINGS = {
    "municipalities": ["Stockholm"],
    "hours": 24,
    "update_interval": 15,
    "nearby_radius": 1.0,
    "advanced": {
        "max_attribute_incidents": 25,
        "max_markers": 100,
        "max_pages": 6,
        "location_keys": ["title_location", "location_string_2", "location_string"],
        "app_id": "ha-test",
    },
}


async def test_user_flow_creates_entry(hass: HomeAssistant, api) -> None:
    """Two steps, then an entry whose options hold everything tunable."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": "Stockholms län"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    # The picker is filled from live data, so the county's municipalities show.
    assert "Stockholm" in result["description_placeholders"]["found"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SETTINGS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Brottsplatskartan Stockholm"
    # The county and the rate-limit identity are entry data; the rest options.
    assert result["data"] == {"area": "Stockholms län", "app_id": "ha-test"}
    assert result["options"]["municipalities"] == ["Stockholm"]
    assert result["options"]["hours"] == 24
    assert result["options"]["nearby_radius"] == 1.0
    # Advanced fields are flattened out of their section.
    assert result["options"]["max_markers"] == 100
    assert "advanced" not in result["options"]
    assert "app_id" not in result["options"]


async def test_discovery_failure_still_lets_you_configure(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """An unreachable API must not block setup; the picker takes free text."""
    aioclient_mock.get(
        "https://brottsplatskartan.se/api/events", status=500
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": "Stockholms län"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["found"] == "—"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**SETTINGS, "municipalities": ["Kungsholmen"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["municipalities"] == ["Kungsholmen"]


async def test_duplicate_places_aborts(hass: HomeAssistant, api) -> None:
    """A second entry over the same places is refused, whatever the order."""
    first = MockConfigEntry(
        domain=DOMAIN,
        data={"area": "Stockholms län", "app_id": "ha-a"},
        options={"municipalities": ["Solna", "Stockholm"]},
        unique_id="stockholms län|solna,stockholm",
    )
    first.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": "Stockholms län"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        # Same two places, reversed and with a suffix. This is the case the
        # old data/options equality check let through.
        {**SETTINGS, "municipalities": ["stockholms kommun", "Solna"]},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_different_places_allowed(hass: HomeAssistant, api) -> None:
    """Two entries for one county with different places are fine."""
    first = MockConfigEntry(
        domain=DOMAIN,
        data={"area": "Stockholms län", "app_id": "ha-a"},
        options={"municipalities": ["Stockholm"]},
        unique_id="stockholms län|stockholm",
    )
    first.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": "Stockholms län"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**SETTINGS, "municipalities": ["Nacka"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Brottsplatskartan Nacka"


async def test_options_flow_updates_title_and_unique_id(
    hass: HomeAssistant, api
) -> None:
    """Changing places renames the entry and re-identifies it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Brottsplatskartan Stockholm",
        data={"area": "Stockholms län", "app_id": "ha-test"},
        options={"municipalities": ["Stockholm"], "hours": 24,
                 "update_interval": 15, "nearby_radius": 1.0},
        unique_id="stockholms län|stockholm",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**SETTINGS, "municipalities": ["Nacka"], "hours": 48,
         "update_interval": 30, "nearby_radius": 2.5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.title == "Brottsplatskartan Nacka"
    assert entry.unique_id == "stockholms län|nacka"
    assert entry.options["hours"] == 48
    assert entry.options["update_interval"] == 30
    assert entry.options["nearby_radius"] == 2.5
    # A saved 0 must survive, not be replaced by the default.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**SETTINGS, "municipalities": ["Nacka"],
         "advanced": {**SETTINGS["advanced"], "max_markers": 0}},
    )
    await hass.async_block_till_done()
    assert entry.options["max_markers"] == 0


async def test_reconfigure_changes_the_county(hass: HomeAssistant, api) -> None:
    """The county is editable without deleting the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Brottsplatskartan Stockholm",
        data={"area": "Stockholms län", "app_id": "ha-test"},
        options={"municipalities": ["Stockholm"], "hours": 24,
                 "update_interval": 15, "nearby_radius": 1.0},
        unique_id="stockholms län|stockholm",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": "Skåne län"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_settings"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**SETTINGS, "municipalities": ["Malmö"]}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert entry.data["area"] == "Skåne län"
    assert entry.title == "Brottsplatskartan Malmö"
    assert entry.unique_id == "skåne län|malmö"
