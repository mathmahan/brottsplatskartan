"""Parse real rows captured from the live API (Stockholms län, Nov 2026).

These lock in the field names actually observed, so a future refactor cannot
quietly go back to guessing. The rows are abridged copies of real responses.
"""

import importlib
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "brottsplatskartan_local"

sys.path.insert(0, str(ROOT / "tests" / "stubs"))
_pkg = types.ModuleType("bpk")
_pkg.__path__ = [str(COMPONENT)]
sys.modules["bpk"] = _pkg
api = importlib.import_module("bpk.api")

FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILURES.append(name)


# Verbatim from the live API, long HTML/image values abridged.
STOCKHOLM_ROW = {
    "administrative_area_level_1": "Stockholms län",
    "administrative_area_level_2": None,
    "content": "<p>Inringande vittne beskriver en man som med hjälp av en tigersåg...</p>",
    "content_formatted": "<p>Inringande vittne beskriver en man...</p>",
    "content_teaser": "Inringande vittne beskriver en man som med hjälp av en tigersåg...",
    "date_human": "49 minuter sedan",
    "description": "Polisen får in ett samtal om ett försök till inbrott i en container på Kungsholmen.",
    "external_source_link": "https://polisen.se/aktuellt/handelser/2026/november/3/3-november-21.07-stold-stockholm/",
    "headline": "Försök till inbrott i container på Alströmergatan, Kungsholmen",
    "id": 512915,
    "image": "https://kartbilder.brottsplatskartan.se/styles/basic-preview/static/auto/640x320.jpg?latlng=1",
    "image_far": "https://kartbilder.brottsplatskartan.se/styles/basic-preview/static/18.04,59.34,5/640x320@2x.jpg",
    "lat": 59.3357055,
    "lng": 18.0314941,
    "location_string": "Kungsholmen, Alströmergatan, Fridhemsgatan, Stockholm, Stockholms län",
    "location_string_2": "Kungsholmen, Alströmergatan, Fridhemsgatan, Stockholm",
    "permalink": "https://brottsplatskartan.se/stockholm/stold-stockholm-kungsholmen-512915",
    "pubdate_iso8601": "2026-11-03T21:38:54+01:00",
    "pubdate_unix": "1793738334",
    "title_location": "Stockholm",
    "title_type": "Stöld",
}

# Other municipalities in the same county, from the observed place list.
SODERTALJE_ROW = {
    **STOCKHOLM_ROW,
    "id": 512800,
    "headline": "Stöld på Birkavägen",
    "title_location": "Södertälje",
    "location_string": "Birkavägen, Filen, Södertälje, Stockholms län",
    "location_string_2": "Birkavägen, Filen, Södertälje",
}
NACKA_ROW = {
    **STOCKHOLM_ROW,
    "id": 512801,
    "title_location": "Nacka",
    "location_string": "Nacka, Stockholms län",
    "location_string_2": "Nacka",
}
# The nasty one: a street in another kommun whose name starts with "Stockholm".
STOCKHOLMSVAGEN_IN_NACKA = {
    **STOCKHOLM_ROW,
    "id": 512802,
    "title_location": "Nacka",
    "location_string": "Stockholmsvägen, Nacka, Stockholms län",
    "location_string_2": "Stockholmsvägen, Nacka",
}
# A row whose only location is the county itself (3 such rows were observed).
COUNTY_ONLY_ROW = {
    **STOCKHOLM_ROW,
    "id": 512803,
    "title_location": None,
    "location_string": "Stockholms län",
    "location_string_2": None,
}
SOLNA_ROW = {
    **STOCKHOLM_ROW,
    "id": 512804,
    "title_location": "Solna",
    "location_string": "Stockholm, Huvudsta, Lönen, Stockholms län",
    "location_string_2": "Stockholm, Huvudsta, Lönen",
}

KEYS = api.DEFAULT_LOCATION_KEYS


def main():
    inc = api.parse_incident(STOCKHOLM_ROW, KEYS)

    # Fields read from the real key names.
    check("headline used as title", inc.title,
          "Försök till inbrott i container på Alströmergatan, Kungsholmen")
    check("type", inc.incident_type, "Stöld")
    check("municipality from title_location", inc.municipality, "Stockholm")
    check("place is the most specific component", inc.place, "Kungsholmen")
    check("location is the readable hierarchy", inc.location,
          "Kungsholmen, Alströmergatan, Fridhemsgatan, Stockholm")
    check("county", inc.county, "Stockholms län")
    check("latitude", inc.latitude, 59.3357055)
    check("longitude", inc.longitude, 18.0314941)
    check("permalink -> url", inc.url,
          "https://brottsplatskartan.se/stockholm/stold-stockholm-kungsholmen-512915")
    check("external_source_link -> source_url", inc.source_url,
          "https://polisen.se/aktuellt/handelser/2026/november/3/3-november-21.07-stold-stockholm/")
    check("description is the plain-text summary", inc.description,
          "Polisen får in ett samtal om ett försök till inbrott i en container på Kungsholmen.")
    check("date_human", inc.date_human, "49 minuter sedan")
    check("image captured", inc.image.startswith("https://kartbilder."), True)
    check("image_far -> image_wide", "640x320@2x" in inc.image_wide, True)
    check("published parsed with offset", inc.published.isoformat(),
          "2026-11-03T20:38:54+00:00")

    # The hierarchy is split into components, and the county is not one.
    check("hierarchy split into place candidates", sorted(inc.places),
          ["alströmergatan", "fridhemsgatan", "kungsholmen", "stockholm"])
    check("county excluded from candidates", "stockholms län" in inc.places, False)

    # as_dict omits images unless asked.
    check("as_dict omits image by default", "image" in inc.as_dict(), False)
    check("as_dict can include image", "image" in inc.as_dict(include_image=True), True)

    # Filtering on a municipality.
    rows = [STOCKHOLM_ROW, SODERTALJE_ROW, NACKA_ROW, STOCKHOLMSVAGEN_IN_NACKA,
            COUNTY_ONLY_ROW, SOLNA_ROW]
    incidents = [api.parse_incident(r, KEYS) for r in rows]
    check("all real rows parsed", all(i is not None for i in incidents), True)

    want = {api.normalize_place("Stockholm")}
    kept = api.filter_by_municipality(incidents, want)
    check("Stockholm filter keeps the Kungsholmen row and the Huvudsta/Solna row",
          sorted(i.uid for i in kept), ["512804", "512915"])

    check("Stockholmsvägen in Nacka is NOT Stockholm",
          "512802" in {i.uid for i in kept}, False)
    check("county-only row is not Stockholm",
          "512803" in {i.uid for i in kept}, False)
    check("Södertälje is not Stockholm",
          "512800" in {i.uid for i in kept}, False)

    # District-level filtering, enabled by splitting the hierarchy.
    kept = api.filter_by_municipality(incidents, {api.normalize_place("Kungsholmen")})
    check("can filter to a single district", [i.uid for i in kept], ["512915"])

    kept = api.filter_by_municipality(
        incidents, {api.normalize_place("Nacka"), api.normalize_place("Södertälje")}
    )
    check("multi-kommun filter", sorted(i.uid for i in kept),
          ["512800", "512801", "512802"])

    # A row with no usable place must not match anything.
    inc = api.parse_incident(COUNTY_ONLY_ROW, KEYS)
    check("county-only row has no place candidates", sorted(inc.places), [])
    check("county-only row has no municipality", inc.municipality, None)

    # --- config entry identity (api.entry_unique_id) ---
    # Order-independent, so a reordered municipality list cannot slip past the
    # duplicate check and create a second entry over the same incidents.
    uid = api.entry_unique_id
    check("order does not change identity",
          uid("Stockholms län", ["Solna", "Stockholm"]),
          uid("Stockholms län", ["Stockholm", "Solna"]))
    check("the kommun suffix does not change identity",
          uid("Stockholms län", ["Stockholms kommun"]),
          uid("Stockholms län", ["Stockholm"]))
    check("case does not change identity",
          uid("Stockholms län", ["STOCKHOLM"]), uid("Stockholms län", ["Stockholm"]))
    check("repeats collapse",
          uid("Stockholms län", ["Stockholm", "Stockholm"]),
          uid("Stockholms län", ["Stockholm"]))
    check("the county's own name is not a place",
          uid("Stockholms län", ["Stockholms län"]), uid("Stockholms län", []))
    check("a different place set is a different entry",
          uid("Stockholms län", ["Stockholm"]) != uid("Stockholms län", ["Nacka"]), True)
    check("whole county differs from a filtered entry",
          uid("Stockholms län", []) != uid("Stockholms län", ["Stockholm"]), True)
    check("a different county is a different entry",
          uid("Stockholms län", []) != uid("Skåne län", []), True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all real-schema checks passed")
    return 0


sys.exit(main())
