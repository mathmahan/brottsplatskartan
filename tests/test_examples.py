"""Structural checks on the example YAML files.

These exist because the example files were twice the wrong *shape* while being
perfectly valid YAML, which neither a parse nor a template render catches:

* dashboard.yaml was a bare list of cards, which the raw configuration editor
  rejects because it wants a whole dashboard mapping;
* the automations were under an `automation:` key, which collides with the
  `automation: !include automations.yaml` that a default Home Assistant
  configuration already has.
"""

import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILURES = []

import re  # noqa: E402

# Keys a stock configuration.yaml already defines, usually via !include.
# Anything we tell people to append must avoid them.
RESERVED_KEYS = {
    "automation", "script", "scene", "sensor", "binary_sensor", "switch",
    "light", "group", "default_config", "frontend", "homeassistant",
}

# A representative stock configuration.yaml, in the shape HA ships.
STOCK_CONFIG = """
default_config:
frontend:
  themes: !include_dir_merge_named themes
automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
"""


class StrictLoader(yaml.SafeLoader):
    """Mirrors Home Assistant's loader, which rejects duplicate keys."""


def _no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.MarkedYAMLError(
                context="duplicate key",
                problem=f"duplicate key: {key!r}",
                problem_mark=key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)
for tag in ("!include", "!include_dir_merge_named", "!include_dir_list",
            "!include_dir_merge_list", "!include_dir_named", "!secret", "!env_var"):
    StrictLoader.add_constructor(tag, lambda loader, node: f"<{node.value}>")


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILURES.append(name)


JINJA = re.compile(r"\{\{|\{%|\{#")
# Entity ids the integration creates. A templated card must discover these
# through integration_entities(), not hardcode them, so the cards keep working
# when the config entry is renamed.
INTEGRATION_IDS = re.compile(
    r"sensor\.brottsplatskartan_\w*_(incidents|latest_incident)\b"
)


def walk(cards):
    """Yield every card, descending into conditional and stack wrappers."""
    for card in cards:
        yield card
        if isinstance(card.get("card"), dict):
            yield from walk([card["card"]])
        if isinstance(card.get("cards"), list):
            yield from walk(card["cards"])


def cards_of(path):
    """Load a dashboard file and return its cards, checking the outer shape."""
    doc = yaml.safe_load(path.read_text())
    name = path.name
    check(f"{name} is a mapping, not a bare card list", isinstance(doc, dict), True)
    if not isinstance(doc, dict):
        return []
    check(f"{name}'s only top-level key is 'views'", sorted(doc), ["views"])
    check(f"{name}: views is a list", isinstance(doc.get("views"), list), True)
    cards = [c for v in doc.get("views", []) for c in walk(v.get("cards", []))]
    check(f"{name} has cards", len(cards) > 0, True)
    check(f"{name}: every card declares a type",
          [c for c in cards if "type" not in c], [])
    check(f"{name}: every view has a title",
          [v for v in doc.get("views", []) if not v.get("title")], [])

    # A map card must not set hours_to_show: it draws recorded history as well
    # as current positions, and since an incident never moves that puts a
    # second pin on top of every marker.
    maps = [c for c in cards if c.get("type") == "map"]
    check(f"{name} has a map card", len(maps) > 0, True)
    check(f"{name}: no map card sets hours_to_show",
          [c for c in maps if "hours_to_show" in c], [])
    check(f"{name}: every map card names the geo_location source",
          [c for c in maps if "brottsplatskartan_local"
           not in (c.get("geo_location_sources") or [])], [])
    return cards


def main():
    # ---------------- dashboard.yaml (templated) ----------------
    cards = cards_of(ROOT / "dashboard.yaml")
    markdown = [c for c in cards if c.get("type") == "markdown" and c.get("content")]
    check("dashboard.yaml has markdown cards", len(markdown) > 0, True)

    for card in markdown:
        label = card.get("title") or "conditional card"
        body = card["content"]
        # Every visible string belongs in the card's TEXT block, so a user
        # changing wording edits one block instead of hunting through markup.
        check(f"{label}: has a TEXT block", "===== TEXT" in body, True)
        check(f"{label}: has a set of text variables",
              len(re.findall(r"\{% set t_\w+", body)) > 0, True)

    # The integration's own sensors must be discovered, not hardcoded. The
    # nearest-incident sensor is exempt: it is a user-created template sensor
    # from examples/configuration.yaml, so there is nothing to discover it by.
    for card in markdown:
        label = card.get("title") or "conditional card"
        hardcoded = INTEGRATION_IDS.findall(card["content"])
        check(f"{label}: no hardcoded integration entity id", hardcoded, [])

    check("templated cards use integration_entities()",
          len([c for c in markdown if "integration_entities(" in c["content"]]) >= 3,
          True)

    # ---------------- dashboard-simple.yaml (no templates) ----------------
    simple_path = ROOT / "dashboard-simple.yaml"
    check("the no-template dashboard exists", simple_path.exists(), True)
    simple = cards_of(simple_path)
    jinja_cards = [
        c["type"] for c in simple
        if JINJA.search(yaml.dump(c, allow_unicode=True))
    ]
    check("dashboard-simple.yaml contains no Jinja at all", jinja_cards, [])
    check("dashboard-simple.yaml uses only built-in card types",
          [c["type"] for c in simple if c["type"].startswith("custom:")], [])

    # ---------------- examples/configuration.yaml ----------------
    cfg_text = (ROOT / "examples" / "configuration.yaml").read_text()
    cfg = yaml.safe_load(cfg_text)
    check("configuration example is a mapping", isinstance(cfg, dict), True)
    check("configuration example avoids keys a stock config already defines",
          sorted(set(cfg) & RESERVED_KEYS), [])

    # It must merge into a stock configuration.yaml without a duplicate key.
    try:
        merged = yaml.load(STOCK_CONFIG + "\n" + cfg_text, Loader=StrictLoader)
        check("appends to a stock configuration.yaml cleanly",
              set(cfg) <= set(merged), True)
    except yaml.MarkedYAMLError as err:
        check("appends to a stock configuration.yaml cleanly",
              f"rejected: {err.problem}", True)

    # ---------------- examples/automations.yaml ----------------
    autos = yaml.safe_load((ROOT / "examples" / "automations.yaml").read_text())
    check("automations example is a list, ready to append to automations.yaml",
          isinstance(autos, list), True)
    check("no automation is wrapped in an 'automation' key",
          [a for a in autos if isinstance(a, dict) and "automation" in a], [])
    for auto in autos:
        missing = {"id", "alias", "triggers", "actions"} - set(auto)
        check(f"{auto.get('alias', auto)} has id/alias/triggers/actions",
              sorted(missing), [])
    check("automation ids are unique",
          len({a["id"] for a in autos}), len(autos))
    # Modern syntax: the pre-2024.10 spellings should be gone.
    check("no legacy 'trigger:'/'action:'/'platform:'/'service:' spellings",
          [a["alias"] for a in autos
           if {"trigger", "action", "condition"} & set(a)], [])

    # ---------------- examples/ui-editor/*.yaml ----------------
    # These are for the automation editor's YAML mode, which takes ONE
    # automation object. Handing it a list makes the frontend send an object
    # keyed "0", and Home Assistant answers "not a valid option at '['0']'".
    ui_files = sorted((ROOT / "examples" / "ui-editor").glob("*.yaml"))
    check("there are ui-editor examples", len(ui_files) > 0, True)
    for path in ui_files:
        doc = yaml.safe_load(path.read_text())
        check(f"{path.name} is a single mapping, not a list",
              isinstance(doc, dict), True)
        if not isinstance(doc, dict):
            continue
        check(f"{path.name} carries no id (the UI assigns it)",
              "id" not in doc, True)
        check(f"{path.name} has alias/triggers/actions",
              sorted({"alias", "triggers", "actions"} - set(doc)), [])
        check(f"{path.name} uses modern trigger/action keys",
              sorted({"trigger", "action", "condition"} & set(doc)), [])

    # Every automation in automations.yaml should have a ui-editor counterpart,
    # so neither set silently falls behind the other.
    ui_aliases = {
        yaml.safe_load(p.read_text())["alias"]
        for p in ui_files
        if isinstance(yaml.safe_load(p.read_text()), dict)
    }
    check("every automations.yaml entry has a ui-editor counterpart",
          sorted({a["alias"] for a in autos} - ui_aliases), [])

    # ---------------- no stale references ----------------
    # The nearest-incident distance and the proximity flag used to be template
    # sensors people had to write by hand. They are entities now, so no
    # example may still point at the old hand-made ids.
    retired = (
        "sensor.brottsplatskartan_nearest_incident",
        "sensor.brottsplatskartan_incident_nearby",
    )
    example_files = [
        ROOT / "dashboard.yaml",
        ROOT / "dashboard-simple.yaml",
        ROOT / "examples" / "configuration.yaml",
        ROOT / "examples" / "automations.yaml",
        *sorted((ROOT / "examples" / "ui-editor").glob("*.yaml")),
    ]
    for path in example_files:
        text = path.read_text()
        check(f"{path.name}: no retired template-sensor ids",
              [name for name in retired if name in text], [])

    # The built-in entities should actually be used somewhere.
    all_text = "\n".join(p.read_text() for p in example_files)
    check("examples use the built-in nearest-incident sensor",
          "_nearest_incident" in all_text, True)
    check("examples use the built-in proximity binary sensor",
          "_incident_nearby" in all_text, True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all example-file checks passed")
    return 0


sys.exit(main())
