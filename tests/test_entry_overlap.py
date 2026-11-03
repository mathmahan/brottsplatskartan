"""Entry identity and overlap detection.

Models the real situation that produced 14 markers for 10 distinct incidents:
one entry filtered to Stockholm kommun (4 incidents) alongside one covering
the whole of Stockholms län (10 incidents), so the 4 shared ones get a marker
from each entry.
"""

import importlib
import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "brottsplatskartan_local"

sys.path.insert(0, str(ROOT / "tests" / "stubs"))
sys.path.insert(0, str(COMPONENT.parent))

component = importlib.import_module("brottsplatskartan_local")
api = importlib.import_module("brottsplatskartan_local.api")
const = importlib.import_module("brottsplatskartan_local.const")
from homeassistant.config_entries import ConfigEntry  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILURES.append(name)


class FakeEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):
        return self._entries

    def async_update_entry(self, entry, **kwargs):
        for key, value in kwargs.items():
            setattr(entry, key, value)


class FakeHass:
    def __init__(self, entries):
        self.config_entries = FakeEntries(entries)


def make_entry(municipalities, title, entry_id, area="Stockholms län"):
    entry = ConfigEntry(
        data={const.CONF_AREA: area, const.CONF_APP_ID: "ha-x"},
        options={const.CONF_MUNICIPALITIES: municipalities},
        title=title,
        entry_id=entry_id,
    )
    entry.unique_id = None
    return entry


def warnings_for(entry, others):
    """Capture the warnings the overlap check logs for `entry`."""
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    const.LOGGER.addHandler(handler)
    const.LOGGER.setLevel(logging.WARNING)
    try:
        component._warn_about_overlapping_entries(
            FakeHass([entry, *others]),
            entry,
            entry.data[const.CONF_AREA],
            list(entry.options.get(const.CONF_MUNICIPALITIES) or []),
        )
    finally:
        const.LOGGER.removeHandler(handler)
    return records


def main():
    county = make_entry([], "Brottsplatskartan Stockholms län", "county")
    sthlm = make_entry(["Stockholm"], "Brottsplatskartan Stockholm", "sthlm")
    nacka = make_entry(["Nacka"], "Brottsplatskartan Nacka", "nacka")
    skane = make_entry([], "Brottsplatskartan Skåne län", "skane", area="Skåne län")

    # --- the reported case: a county entry beside a municipality entry ---
    logged = warnings_for(sthlm, [county])
    check("Stockholm entry warns about the county entry", len(logged), 1)
    check("the warning names the other entry",
          "Brottsplatskartan Stockholms län" in logged[0], True)
    check("the warning explains the doubled markers",
          "more than once on the map" in logged[0], True)

    # Symmetric: the county entry warns about the municipality entry too.
    check("county entry warns about the Stockholm entry",
          len(warnings_for(county, [sthlm])), 1)

    # --- non-overlapping entries stay quiet ---
    check("two different municipalities do not warn",
          warnings_for(sthlm, [nacka]), [])
    check("a different county does not warn",
          warnings_for(sthlm, [skane]), [])
    check("a lone entry does not warn", warnings_for(sthlm, []), [])
    check("a lone county entry does not warn", warnings_for(county, []), [])

    # --- overlap through a shared place in a longer list ---
    multi = make_entry(["Solna", "Stockholm"], "Brottsplatskartan Solna, Stockholm", "multi")
    check("a shared municipality in a longer list warns",
          len(warnings_for(sthlm, [multi])), 1)
    check("no shared municipality does not warn",
          warnings_for(nacka, [multi]), [])

    # --- overlap via a district inside a configured municipality ---
    kungsholmen = make_entry(["Kungsholmen"], "Brottsplatskartan Kungsholmen", "kh")
    # Deliberately not flagged: "Kungsholmen" and "Stockholm" are different
    # place names, so there is no way to know they overlap without a
    # municipality-to-district table the API does not provide.
    check("a district beside its municipality is not flagged",
          warnings_for(kungsholmen, [sthlm]), [])

    # --- identity is order- and spelling-independent ---
    uid = api.entry_unique_id
    check("order does not change identity",
          uid("Stockholms län", ["Solna", "Stockholm"]),
          uid("Stockholms län", ["Stockholm", "Solna"]))
    check("the kommun suffix does not change identity",
          uid("Stockholms län", ["Stockholms kommun"]),
          uid("Stockholms län", ["Stockholm"]))
    check("the county's own name is not a place",
          uid("Stockholms län", ["Stockholms län"]), uid("Stockholms län", []))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all entry-overlap checks passed")
    return 0


sys.exit(main())
