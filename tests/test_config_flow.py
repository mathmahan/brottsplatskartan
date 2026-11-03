"""Exercise the config and options flow schemas with stubbed Home Assistant.

This does not drive a real flow — that needs the Home Assistant test harness.
It checks the parts that are easy to get wrong and that no runtime would catch
for you: that the schemas build, that defaults land where intended, that
NumberSelector's floats are stored as ints, and that the titles and imported
options come out right.
"""

import asyncio
import importlib
import pathlib
import sys
import types

import voluptuous as vol

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "brottsplatskartan_local"

sys.path.insert(0, str(ROOT / "tests" / "stubs"))
_pkg = types.ModuleType("bpk")
_pkg.__path__ = [str(COMPONENT)]
sys.modules["bpk"] = _pkg

cf = importlib.import_module("bpk.config_flow")
const = importlib.import_module("bpk.const")

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILURES.append(name)


def main():
    # --- the shared tuning schema builds and applies defaults ---
    schema = vol.Schema(cf._tuning_schema({}))
    result = schema({})
    check("default window is 24h", result[const.CONF_HOURS], const.DEFAULT_HOURS)
    check("default interval is 15 min",
          result[const.CONF_UPDATE_INTERVAL], const.DEFAULT_UPDATE_INTERVAL)
    check("default marker cap", result[const.CONF_MAX_MARKERS], const.DEFAULT_MAX_MARKERS)
    check("default attribute cap",
          result[const.CONF_MAX_ATTRIBUTE_INCIDENTS],
          const.DEFAULT_MAX_ATTRIBUTE_INCIDENTS)
    check("default page cap", result[const.CONF_MAX_PAGES], const.DEFAULT_MAX_PAGES)

    # --- existing options are pre-filled, not reset to defaults ---
    current = {const.CONF_HOURS: 72, const.CONF_UPDATE_INTERVAL: 30,
               const.CONF_MAX_MARKERS: 0}
    result = vol.Schema(cf._tuning_schema(current))({})
    check("options flow pre-fills the saved window", result[const.CONF_HOURS], 72)
    check("options flow pre-fills the saved interval",
          result[const.CONF_UPDATE_INTERVAL], 30)
    check("a saved 0 cap is kept, not replaced by the default",
          result[const.CONF_MAX_MARKERS], 0)

    # --- NumberSelector hands back floats; they must be stored as ints ---
    coerced = cf._coerce_ints({
        const.CONF_HOURS: 24.0,
        const.CONF_UPDATE_INTERVAL: 15.0,
        const.CONF_MAX_MARKERS: 100.0,
        const.CONF_MAX_ATTRIBUTE_INCIDENTS: 25.0,
        const.CONF_MAX_PAGES: 6.0,
        const.CONF_MUNICIPALITIES: ["Stockholm"],
    })
    check("floats coerced to int",
          [type(coerced[k]).__name__ for k in
           (const.CONF_HOURS, const.CONF_UPDATE_INTERVAL, const.CONF_MAX_MARKERS,
            const.CONF_MAX_ATTRIBUTE_INCIDENTS, const.CONF_MAX_PAGES)],
          ["int"] * 5)
    check("municipalities untouched by coercion",
          coerced[const.CONF_MUNICIPALITIES], ["Stockholm"])
    check("coercion tolerates missing keys", cf._coerce_ints({}), {})

    # --- titles ---
    check("title from municipalities", cf._title("Stockholms län", ["Stockholm"]),
          "Brottsplatskartan Stockholm")
    check("title from several municipalities",
          cf._title("Stockholms län", ["Stockholm", "Solna"]),
          "Brottsplatskartan Stockholm, Solna")
    check("title falls back to the county",
          cf._title("Stockholms län", []), "Brottsplatskartan Stockholms län")

    # --- municipality selector keeps API order (frequency), does not sort ---
    sel = cf._municipality_selector(["Stockholm", "Nacka", "Sigtuna"])
    check("selector is multi-select", sel.config["multiple"], True)
    check("selector accepts typed-in districts", sel.config["custom_value"], True)
    check("selector does not re-sort the frequency order", sel.config["sort"], False)
    check("selector options come from discovery",
          sel.config["options"], ["Stockholm", "Nacka", "Sigtuna"])

    # --- YAML import maps old keys onto options ---
    flow = cf.BpkConfigFlow()
    imported = asyncio.run(flow.async_step_import({
        const.CONF_AREA: "Stockholms län",
        const.CONF_MUNICIPALITIES: ["Stockholm"],
        const.CONF_HOURS: 48,
        const.CONF_UPDATE_INTERVAL: 20,
        const.CONF_APP_ID: "ha-abc123",
    }))
    check("import creates an entry", imported["type"], "create_entry")
    check("import title", imported["title"], "Brottsplatskartan Stockholm")
    check("import keeps the area in data",
          imported["data"][const.CONF_AREA], "Stockholms län")
    check("import keeps the app id stable",
          imported["data"][const.CONF_APP_ID], "ha-abc123")
    check("import moves municipalities to options",
          imported["options"][const.CONF_MUNICIPALITIES], ["Stockholm"])
    check("import keeps the window", imported["options"][const.CONF_HOURS], 48)
    check("import keeps the interval",
          imported["options"][const.CONF_UPDATE_INTERVAL], 20)
    check("import fills in missing options with defaults",
          imported["options"][const.CONF_MAX_MARKERS], const.DEFAULT_MAX_MARKERS)

    # An import with nothing but an area must still work.
    bare = asyncio.run(cf.BpkConfigFlow().async_step_import({}))
    check("bare import uses the default area",
          bare["data"][const.CONF_AREA], const.DEFAULT_AREA)
    check("bare import has no municipality filter",
          bare["options"][const.CONF_MUNICIPALITIES], [])
    check("bare import mints an app id",
          bare["data"][const.CONF_APP_ID].startswith("ha-"), True)

    # --- the places step stores what was picked, trimming blanks ---
    flow = cf.BpkConfigFlow()
    flow._area = "Stockholms län"
    created = asyncio.run(flow.async_step_places({
        const.CONF_MUNICIPALITIES: ["Stockholm", "  ", " Kungsholmen "],
        const.CONF_HOURS: 24.0,
        const.CONF_UPDATE_INTERVAL: 15.0,
        const.CONF_MAX_ATTRIBUTE_INCIDENTS: 25.0,
        const.CONF_MAX_MARKERS: 100.0,
        const.CONF_MAX_PAGES: 6.0,
    }))
    check("blank entries dropped and names trimmed",
          created["options"][const.CONF_MUNICIPALITIES], ["Stockholm", "Kungsholmen"])
    check("picked places shape the title",
          created["title"], "Brottsplatskartan Stockholm, Kungsholmen")
    check("area is not duplicated into options",
          const.CONF_AREA in created["options"], False)

    # --- entry identity is order-independent ---
    uid = cf.entry_unique_id
    check("same places in a different order give the same id",
          uid("Stockholms län", ["Solna", "Stockholm"]),
          uid("Stockholms län", ["Stockholm", "Solna"]))
    check("suffix spellings give the same id",
          uid("Stockholms län", ["Stockholms kommun"]),
          uid("Stockholms län", ["Stockholm"]))
    check("case does not matter",
          uid("Stockholms län", ["STOCKHOLM"]), uid("Stockholms län", ["Stockholm"]))
    check("duplicates within the list collapse",
          uid("Stockholms län", ["Stockholm", "Stockholm"]),
          uid("Stockholms län", ["Stockholm"]))
    check("a different place set is a different entry",
          uid("Stockholms län", ["Stockholm"]) != uid("Stockholms län", ["Nacka"]), True)
    check("whole county differs from a filtered entry",
          uid("Stockholms län", []) != uid("Stockholms län", ["Stockholm"]), True)
    check("a different county is a different entry",
          uid("Stockholms län", []) != uid("Skåne län", []), True)

    # --- a second entry over the same places is refused ---
    from homeassistant.config_entries import AbortFlow

    existing = uid("Stockholms län", ["Stockholm"])
    flow = cf.BpkConfigFlow()
    flow.configured_unique_ids = {existing}
    flow._area = "Stockholms län"
    try:
        asyncio.run(flow.async_step_places({
            # Same place, written differently and in another order.
            const.CONF_MUNICIPALITIES: ["stockholms kommun"],
            const.CONF_HOURS: 24.0, const.CONF_UPDATE_INTERVAL: 15.0,
            const.CONF_MAX_ATTRIBUTE_INCIDENTS: 25.0,
            const.CONF_MAX_MARKERS: 100.0, const.CONF_MAX_PAGES: 6.0,
        }))
        check("duplicate entry refused", "created", "aborted")
    except AbortFlow as err:
        check("duplicate entry refused with already_configured", err.reason,
              "already_configured")

    # The YAML import must abort the same way, so a leftover block does not
    # add a second entry beside one added in the UI.
    flow = cf.BpkConfigFlow()
    flow.configured_unique_ids = {existing}
    try:
        asyncio.run(flow.async_step_import({
            const.CONF_AREA: "Stockholms län",
            const.CONF_MUNICIPALITIES: ["Stockholm"],
        }))
        check("duplicate import refused", "created", "aborted")
    except AbortFlow as err:
        check("duplicate import refused with already_configured", err.reason,
              "already_configured")

    # A genuinely different place set still goes through.
    flow = cf.BpkConfigFlow()
    flow.configured_unique_ids = {existing}
    flow._area = "Stockholms län"
    other = asyncio.run(flow.async_step_places({
        const.CONF_MUNICIPALITIES: ["Nacka"],
        const.CONF_HOURS: 24.0, const.CONF_UPDATE_INTERVAL: 15.0,
        const.CONF_MAX_ATTRIBUTE_INCIDENTS: 25.0,
        const.CONF_MAX_MARKERS: 100.0, const.CONF_MAX_PAGES: 6.0,
    }))
    check("a different municipality is still allowed",
          other["title"], "Brottsplatskartan Nacka")

    # --- the first step offers every county ---
    form = asyncio.run(cf.BpkConfigFlow().async_step_user())
    check("county step is a form", form["type"], "form")
    areas = form["data_schema"]({})[const.CONF_AREA]
    check("county step defaults to Stockholms län", areas, const.DEFAULT_AREA)
    check("all 21 counties offered", len(const.AREAS), 21)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all config-flow checks passed")
    return 0


sys.exit(main())
