"""Set the integration up for real and inspect what it produces."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.brottsplatskartan_local.const import DOMAIN

# Stockholm, so the distance maths is meaningful against the fixture rows.
HOME = (59.3293, 18.0686)

COUNT = "sensor.brottsplatskartan_stockholm_incidents"
LATEST = "sensor.brottsplatskartan_stockholm_latest_incident"
NEAREST = "sensor.brottsplatskartan_stockholm_nearest_incident"
NEARBY = "binary_sensor.brottsplatskartan_stockholm_incident_nearby"
EVENT = "event.brottsplatskartan_stockholm_new_incident"


def make_entry(hass, **overrides):
    options = {
        "municipalities": ["Stockholm"],
        "hours": 24,
        "update_interval": 15,
        "nearby_radius": 1.0,
        "max_attribute_incidents": 25,
        "max_markers": 100,
        "max_pages": 6,
    }
    options.update(overrides.pop("options", {}))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=overrides.pop("title", "Brottsplatskartan Stockholm"),
        data={"area": "Stockholms län", "app_id": "ha-test", **overrides.pop("data", {})},
        options=options,
        unique_id=overrides.pop("unique_id", "stockholms län|stockholm"),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def home(hass):
    """Put the home zone in Stockholm."""
    hass.config.latitude, hass.config.longitude = HOME
    return hass


async def setup_entry(hass, **kw):
    entry = make_entry(hass, **kw)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entity_ids_and_states(home: HomeAssistant, api) -> None:
    """The entity ids the dashboards reference, with the expected states."""
    hass = home
    await setup_entry(hass)

    count = hass.states.get(COUNT)
    assert count is not None, "the count sensor id the dashboards use must exist"
    # Of the five fixture rows, two are in Stockholm kommun inside 24 hours.
    # Nacka and Södertälje are filtered out; the fifth is 40 hours old.
    assert count.state == "2"
    assert count.attributes["by_type"] == {"Stöld": 1, "Rån": 1}
    assert count.attributes["fetched_in_county"] == 4
    assert count.attributes["municipalities"] == ["Stockholm"]
    assert count.attributes["window_hours"] == 24
    assert len(count.attributes["incidents"]) == 2
    assert count.attributes["truncated"] is False
    # Images are deliberately excluded from the list to stay inside the
    # recorder's attribute limit.
    assert "image" not in count.attributes["incidents"][0]

    latest = hass.states.get(LATEST)
    assert latest is not None
    assert latest.state.startswith("Stöld i Kungsholmen")
    assert latest.attributes["place"] == "Kungsholmen"
    assert latest.attributes["municipality"] == "Stockholm"
    assert latest.attributes["description"].startswith("Polisen rapporterar")
    assert latest.attributes["url"].endswith("/handelse-1")
    assert latest.attributes["source_url"].endswith("/1/")
    assert "image_wide" in latest.attributes

    nearest = hass.states.get(NEAREST)
    assert nearest is not None
    assert float(nearest.state) < 5, "Kungsholmen is a few km from the home zone"
    assert nearest.attributes["unit_of_measurement"] == "km"
    assert nearest.attributes["device_class"] == "distance"

    assert hass.states.get(EVENT) is not None


async def test_geo_location_markers(home: HomeAssistant, api) -> None:
    """One marker per in-scope incident, with distance as its state."""
    hass = home
    await setup_entry(hass)

    markers = [
        state for state in hass.states.async_all("geo_location")
        if state.attributes.get("source") == DOMAIN
    ]
    assert len(markers) == 2, "only the filtered incidents get markers"
    # No duplicates: one marker per distinct incident.
    ids = {m.attributes["incident_id"] for m in markers}
    assert len(ids) == len(markers)

    marker = next(m for m in markers if m.attributes["type"] == "Stöld")
    assert marker.name == "Stöld: Kungsholmen"
    assert marker.attributes["headline"].startswith("Stöld i Kungsholmen")
    assert marker.attributes["description"]
    assert marker.attributes["url"].endswith("/handelse-1")
    assert marker.attributes["source_url"]
    assert float(marker.state) == pytest.approx(
        float(hass.states.get(NEAREST).state), abs=0.2
    ), "markers and the nearest sensor must agree on distance"


async def test_nearby_is_off_outside_the_radius(home: HomeAssistant, api) -> None:
    """The nearest incident is 4 km away, so a 1 km radius stays off."""
    hass = home
    await setup_entry(hass, options={"nearby_radius": 1.0})
    nearby = hass.states.get(NEARBY)
    assert nearby is not None
    assert nearby.state == "off"
    assert nearby.attributes["nearby_radius"] == 1.0
    assert nearby.attributes["distance_km"] == pytest.approx(4.0, abs=0.1)
    assert nearby.attributes["device_class"] == "safety"
    # Nothing tripped it, so no incident detail is attached.
    assert "url" not in nearby.attributes


async def test_nearby_is_on_inside_the_radius(home: HomeAssistant, api) -> None:
    """A 10 km radius turns it on and attaches the incident that tripped it.

    The radius is a config option, which is what removes the need for a
    hand-written template sensor.
    """
    hass = home
    await setup_entry(hass, options={"nearby_radius": 10.0})
    nearby = hass.states.get(NEARBY)
    assert nearby.state == "on"
    assert nearby.attributes["place"] == "Kungsholmen"
    assert nearby.attributes["url"].endswith("/handelse-1")


async def test_actions(home: HomeAssistant, api) -> None:
    """refresh and get_incidents are registered and work."""
    hass = home
    await setup_entry(hass)

    assert hass.services.has_service(DOMAIN, "refresh")
    assert hass.services.has_service(DOMAIN, "get_incidents")

    await hass.services.async_call(
        DOMAIN, "refresh", {}, target={"entity_id": COUNT}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(COUNT).state == "2"

    response = await hass.services.async_call(
        DOMAIN, "get_incidents", {}, target={"entity_id": COUNT},
        blocking=True, return_response=True,
    )
    payload = response[COUNT]
    assert payload["count"] == 2
    assert payload["area"] == "Stockholms län"
    assert payload["window_hours"] == 24
    # The action is not capped by max_attribute_incidents and does carry images.
    assert "image_wide" in payload["incidents"][0]

    filtered = await hass.services.async_call(
        DOMAIN, "get_incidents", {"incident_type": ["rån"]},
        target={"entity_id": COUNT}, blocking=True, return_response=True,
    )
    assert filtered[COUNT]["count"] == 1
    assert filtered[COUNT]["incidents"][0]["type"] == "Rån"

    limited = await hass.services.async_call(
        DOMAIN, "get_incidents", {"limit": 1},
        target={"entity_id": COUNT}, blocking=True, return_response=True,
    )
    assert limited[COUNT]["count"] == 1

    none_near = await hass.services.async_call(
        DOMAIN, "get_incidents", {"within_km": 0.1},
        target={"entity_id": COUNT}, blocking=True, return_response=True,
    )
    assert none_near[COUNT]["count"] == 0


async def test_overlapping_entries_raise_a_repair_issue(
    home: HomeAssistant, api
) -> None:
    """The doubled-markers situation is reported in Settings, not just the log."""
    hass = home
    county = make_entry(
        hass,
        title="Brottsplatskartan Stockholms län",
        options={"municipalities": []},
        unique_id="stockholms län|",
    )
    sthlm = make_entry(hass)
    # Setting up the first entry sets up the integration, and Home Assistant
    # then sets up every other entry of that domain itself — so this one call
    # loads both.
    assert await hass.config_entries.async_setup(county.entry_id)
    await hass.async_block_till_done()
    assert county.state is ConfigEntryState.LOADED
    assert sthlm.state is ConfigEntryState.LOADED

    registry = ir.async_get(hass)
    issues = [
        issue for issue in registry.issues.values()
        if issue.domain == DOMAIN and issue.translation_key == "overlapping_entries"
    ]
    assert len(issues) == 2, "both entries should flag the overlap"
    placeholders = issues[0].translation_placeholders
    assert "Brottsplatskartan" in placeholders["others"]
    assert placeholders["area"] == "Stockholms län"


async def test_no_repair_issue_for_a_single_entry(home: HomeAssistant, api) -> None:
    """One entry on its own must not be flagged."""
    hass = home
    await setup_entry(hass)
    registry = ir.async_get(hass)
    assert not [
        issue for issue in registry.issues.values() if issue.domain == DOMAIN
    ]


async def test_unique_id_is_backfilled(home: HomeAssistant, api) -> None:
    """An entry predating unique ids gets one, so duplicates are caught later."""
    hass = home
    entry = await setup_entry(hass, unique_id=None)
    assert entry.unique_id == "stockholms län|stockholm"


async def test_unload(home: HomeAssistant, api) -> None:
    """Unloading removes the entities."""
    hass = home
    entry = await setup_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    # Registered entities keep a restored, unavailable state rather than
    # disappearing from the state machine.
    for entity_id in (COUNT, LATEST, NEAREST, NEARBY):
        assert hass.states.get(entity_id).state == "unavailable"
    assert not [
        state for state in hass.states.async_all("geo_location")
        if state.attributes.get("source") == DOMAIN
    ], "markers have no unique id, so they really do go away"
