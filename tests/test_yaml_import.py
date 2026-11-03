"""Run a real user's configuration.yaml block through CONFIG_SCHEMA and the import.

The block below is copied verbatim from an actual installation, including the
`scan_interval: "00:15:00"` string form, which is the case most likely to go
wrong: config entries are JSON, so a timedelta cannot be stored and has to be
converted to whole minutes on the way in.
"""

import asyncio
import importlib
import pathlib
import sys
from datetime import timedelta

import voluptuous as vol
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "brottsplatskartan_local"

sys.path.insert(0, str(ROOT / "tests" / "stubs"))
# Unlike the other suites, this one needs the component's own __init__.py to
# run, since CONFIG_SCHEMA lives there. Importing it as a real package from
# custom_components/ is simpler than mounting a synthetic one, and the stubs
# now cover everything __init__.py pulls in.
sys.path.insert(0, str(COMPONENT.parent))

component = importlib.import_module("brottsplatskartan_local")
cf = importlib.import_module("brottsplatskartan_local.config_flow")
const = importlib.import_module("brottsplatskartan_local.const")

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILURES.append(name)


# Verbatim from a live configuration.yaml.
USER_YAML = """
brottsplatskartan_local:
  area: "Stockholms län"
  municipalities:
    - Stockholm
  hours: 24
  scan_interval: "00:15:00"
"""


def simulate_import(raw_yaml: str) -> dict:
    """Do what async_setup does to a YAML block, then run the import step."""
    config = component.CONFIG_SCHEMA(yaml.safe_load(raw_yaml))
    conf = config[const.DOMAIN]

    import_data = dict(conf)
    interval = import_data.pop("scan_interval", const.DEFAULT_SCAN_INTERVAL)
    import_data[const.CONF_UPDATE_INTERVAL] = max(
        const.MIN_UPDATE_INTERVAL, int(interval.total_seconds() // 60)
    )
    return asyncio.run(cf.BpkConfigFlow().async_step_import(import_data))


def main():
    # --- the block validates, and fills in the options it does not mention ---
    config = component.CONFIG_SCHEMA(yaml.safe_load(USER_YAML))
    conf = config[const.DOMAIN]
    check("area accepted", conf[const.CONF_AREA], "Stockholms län")
    check("municipalities accepted", conf[const.CONF_MUNICIPALITIES], ["Stockholm"])
    check("hours accepted", conf[const.CONF_HOURS], 24)
    check("scan_interval string parsed to timedelta",
          conf["scan_interval"], timedelta(minutes=15))
    check("unmentioned options defaulted",
          (conf[const.CONF_MAX_PAGES], conf[const.CONF_MAX_MARKERS],
           conf[const.CONF_MAX_ATTRIBUTE_INCIDENTS]),
          (const.DEFAULT_MAX_PAGES, const.DEFAULT_MAX_MARKERS,
           const.DEFAULT_MAX_ATTRIBUTE_INCIDENTS))

    # --- it becomes the right config entry ---
    entry = simulate_import(USER_YAML)
    check("import creates an entry", entry["type"], "create_entry")
    check("entry title", entry["title"], "Brottsplatskartan Stockholm")
    check("county stored in data", entry["data"][const.CONF_AREA], "Stockholms län")
    check("app id minted", entry["data"][const.CONF_APP_ID].startswith("ha-"), True)
    check("municipalities carried to options",
          entry["options"][const.CONF_MUNICIPALITIES], ["Stockholm"])
    check("window carried over", entry["options"][const.CONF_HOURS], 24)
    check("00:15:00 became 15 minutes",
          entry["options"][const.CONF_UPDATE_INTERVAL], 15)
    check("interval stored as an int, not a timedelta",
          type(entry["options"][const.CONF_UPDATE_INTERVAL]).__name__, "int")
    check("no timedelta anywhere in the stored entry",
          any(isinstance(v, timedelta)
              for v in list(entry["data"].values()) + list(entry["options"].values())),
          False)

    # --- other interval spellings ---
    for raw, want_minutes in (
        ('scan_interval: "01:00:00"', 60),
        ('scan_interval: "00:30:00"', 30),
        ("scan_interval: 900", 15),
    ):
        block = f'brottsplatskartan_local:\n  area: "Stockholms län"\n  {raw}\n'
        got = simulate_import(block)["options"][const.CONF_UPDATE_INTERVAL]
        check(f"{raw.strip()} -> {want_minutes} min", got, want_minutes)

    # --- a block with nothing in it still imports ---
    bare = simulate_import("brottsplatskartan_local:\n")
    check("empty block uses the default county",
          bare["data"][const.CONF_AREA], const.DEFAULT_AREA)
    check("empty block has no filter",
          bare["options"][const.CONF_MUNICIPALITIES], [])

    # --- a sub-minimum interval is rejected outright, not silently raised ---
    # Failing loudly is deliberate: silently changing someone's configured
    # interval would be worse than telling them it is not allowed.
    for bad in ('"00:00:30"', '"00:02:00"', "60"):
        try:
            component.CONFIG_SCHEMA(yaml.safe_load(
                f'brottsplatskartan_local:\n  scan_interval: {bad}\n'
            ))
            check(f"interval {bad} rejected", "accepted", "vol.Invalid")
        except vol.Invalid as err:
            check(f"interval {bad} rejected by the schema",
                  "at least 300s" in str(err), True)

    # --- an unknown county is rejected ---
    try:
        component.CONFIG_SCHEMA(yaml.safe_load(
            'brottsplatskartan_local:\n  area: "Stockholm"\n'
        ))
        check("bare 'Stockholm' as area rejected", "accepted", "vol.Invalid")
    except vol.Invalid:
        check("bare 'Stockholm' as area rejected (it is a kommun, not a county)",
              True, True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all YAML-import checks passed")
    return 0


sys.exit(main())
