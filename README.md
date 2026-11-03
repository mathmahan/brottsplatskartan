# Brottsplatskartan (local)

A private replacement for the core `brottsplatskartan` integration, built to fix
the three things that made the official one confusing:

| | Official integration | This one |
|---|---|---|
| Area granularity | County only (`Stockholms län`) | County fetch, filtered to municipalities *or districts* (`Stockholm`, `Kungsholmen`) |
| Time window | Calendar day, resets at local midnight | Rolling N hours (default 24) |
| Poll interval | Hardcoded 30 min | Configurable in the UI, default 15 min, floor 5 min |
| Empty page mid-pagination | Discards everything collected so far → count drops to 0 | Keeps what it has |
| Out-of-order row | Stops paging at the first one → undercounts | Pages until a whole page is out of window |
| Incident detail | Count + per-type counts | Count, per-type, full list, map markers, events |

It talks to the API directly and does **not** use the `brottsplatskartan` PyPI
package, so none of those bugs are inherited.

## Install

Either add this repository to HACS as a custom repository (category:
Integration), or copy the component folder in by hand:

```bash
cp -r custom_components/brottsplatskartan_local <config>/custom_components/
```

Restart Home Assistant, then go to **Settings → Devices & services → Add
integration** and search for *Brottsplatskartan (local)*.

You can run this alongside the official integration — the domain is different,
so nothing collides. You can also add it more than once, for example one entry
for your own municipality and another for the whole county.

## Configure

Setup is two steps in the UI:

1. **Pick a county.** The API only accepts whole counties, so this is as
   coarse as the fetch gets.
2. **Narrow it down.** The integration queries the county first and lists the
   municipalities actually reporting incidents right now, so you pick from
   real values rather than a hard-coded table that would go stale. The field is
   open, so you can also type a **district** — `Kungsholmen`, `Södermalm`,
   `Norrmalm` — because the filter matches any component of the location the
   API reports. Leave it empty to count the whole county.

Everything except the county is editable afterwards under **Configure**, and
changes apply immediately — no restart.

| Option | Default | Notes |
|---|---|---|
| County | `Stockholms län` | Set at setup. To watch a different one, add a second entry. |
| Municipalities or districts | *(empty)* | Empty = whole county. Matches a municipality **or** a district. Case- and suffix-insensitive, so `Stockholm` ≡ `Stockholms kommun` ≡ `Stockholms stad`. Comparison is exact, so `Stockholmsvägen` in Nacka does *not* count as Stockholm. |
| Time window | `24 h` | Rolling, 1–168 h. Does not reset at midnight. |
| Update interval | `15 min` | Minimum 5 — the API rate-limits per installation. |
| Incidents listed in attributes | `25` | How many to expose for dashboard cards. `0` omits the list. |
| Maximum map markers | `100` | A wide window over a whole county can return hundreds of incidents; the newest are kept. `0` = no cap. |
| Maximum API pages per update | `6` | Pagination safety stop. Raise it if a long window looks truncated. |

The UI is translated into English and Swedish.

### Upgrading from the YAML version

An existing `brottsplatskartan_local:` block in `configuration.yaml` is
imported into a config entry on the next restart, keeping your settings. Once
the integration shows up under Devices & services, delete the block.

Entity ids are unchanged, so dashboards and automations keep working. The
entities' internal unique ids *did* change, so if you ran the YAML version the
old entities will linger as unavailable — remove them from
**Settings → Devices & services → Entities** once the new ones appear.

There is also one advanced option with no UI field, since it only matters if
the API renames something: `location_keys`, which overrides the list of fields
treated as place names. Set it in YAML and let the import carry it over.

## Entities

- **`sensor.brottsplatskartan_stockholm_incidents`** — count in the window.
  Attributes: `by_type` (per-crime-type counts), `incidents` (the full list —
  each with `title`, `type`, `place`, `location`, `description`, `url`,
  `source_url`, `date_human`, coordinates), `window_hours`, `area`,
  `municipalities`, `fetched_in_county`, `truncated`.
- **`sensor.brottsplatskartan_stockholm_latest_incident`** — newest headline,
  with the same fields plus `image` / `image_wide`: the API's own rendered map
  thumbnail of the location. Images are only on this entity — the URLs run to
  several hundred characters, so a list of 25 would overflow what the recorder
  stores.
- **`geo_location.*`** — one marker per incident that has coordinates, named
  `<type>: <place>` (e.g. `Stöld: Kungsholmen`), with `distance` from home in
  km as its state and the headline, description, both links and the map image
  in its attributes. **You must add `geo_location_sources` to the Map card or
  nothing appears** — see `dashboard.yaml`. These entities are deliberately
  given no `unique_id`, so they do not accumulate in the entity registry.
- **`event.brottsplatskartan_stockholm_new_incident`** — fires `new_incident`
  each time an unseen incident appears. A restart does not replay the window.

Every new incident is also put on the event bus as `brottsplatskartan_local_new_incident`,
which is easier to consume when several arrive in the same poll (the event
entity only holds the most recent).

## Dashboard

`dashboard.yaml` holds ready-made cards — paste the one you want into a
dashboard in YAML mode (or the raw config editor):

1. **Map** with a marker per incident. Requires `geo_location_sources`.
2. **Incident feed** — type, relative time, place, description, and links to
   both Brottsplatskartan and the police's own report.
3. **Summary** — count plus a per-crime-type breakdown.
4. **Latest incident** rendered with the API's static map image.
5. **Trend** — a statistics graph over 30 days (the count sensor sets
   `state_class: measurement`, so long-term statistics work out of the box).
6. **"Nearest incident"** template sensor, derived from the markers' distances,
   plus a conditional card that only appears when something happens close by.

The same file has automations for a rich mobile notification with the map
image and action buttons, and one that only fires for incidents within 1 km.

## Automation example

```yaml
automation:
  - alias: "Notify on new incident"
    trigger:
      - platform: event
        event_type: brottsplatskartan_local_new_incident
    action:
      - service: notify.mobile_app_phone
        data:
          title: "{{ trigger.event.data.type }} i {{ trigger.event.data.municipality }}"
          message: "{{ trigger.event.data.title }}"
          data:
            url: "{{ trigger.event.data.url }}"
```

## Keep the recorder lean

The `incidents` attribute is a list, so exclude it from history:

```yaml
recorder:
  exclude:
    entity_globs:
      - geo_location.brottsplatskartan*
    entities:
      - sensor.brottsplatskartan_stockholm_latest_incident
```

## API fields

Confirmed against a live response (Stockholms län, November 2026):

| Field | Used as | Note |
|---|---|---|
| `headline` | title | `title` does not exist |
| `title_type` | crime type | e.g. `Stöld`, `Rån` |
| `title_location` | municipality | present on 60/60 rows |
| `administrative_area_level_2` | — | **always `null`** — the obvious choice, and useless |
| `administrative_area_level_1` | county | same for every row, so never matched as a municipality |
| `location_string` | districts, streets | comma-separated hierarchy, split into components |
| `description` | description | plain text; `content*` are HTML |
| `permalink` | link | Brottsplatskartan page |
| `external_source_link` | source link | polisen.se |
| `lat` / `lng` | coordinates | floats |
| `image` / `image_far` | map thumbnails | pre-rendered static maps |
| `date_human` | relative time | e.g. `49 minuter sedan` |

## If the count is 0 but the county has incidents

The municipality filter found nothing to match. The count sensor then exposes a
`places_seen_in_county` attribute listing the place names the API actually
returned — put one of those in `municipalities`. To look directly:

```bash
python3 tools/probe_api.py "Stockholms län" Stockholm
```

It needs no Home Assistant install — plain stdlib, run it from anywhere that
can reach the API.

That prints every field name on the first row, which `location_keys` are
present, and what today-vs-24h counting gives, so you can see exactly where a
number comes from.

## Tests

```bash
pip install aiohttp
python3 tests/test_api.py
```

```bash
python3 tests/test_real_schema.py
python3 tests/test_config_flow.py
```

`test_api.py` covers the rolling window, pagination, both upstream bugs,
de-duplication and rate limiting against a fake API server.
`test_real_schema.py` parses rows captured verbatim from the live API and locks
in the confirmed field names, including the cases that matter for filtering: a
street called `Stockholmsvägen` in Nacka must not count as Stockholm, and a row
whose only location is `Stockholms län` must not match any municipality.

`test_config_flow.py` checks the flow schemas: that defaults land where
intended, that saved options are pre-filled rather than reset (including a
saved `0`), that `NumberSelector`'s floats are stored as ints, and that a YAML
import maps onto the new options correctly.

All three run with stubbed Home Assistant modules (`tests/stubs/`), so no Home
Assistant install is required and no real network request is made.

## Layout

```
custom_components/brottsplatskartan_local/
  api.py            direct API client: paging, window filter, field normalization
  coordinator.py    DataUpdateCoordinator, place filtering, per-type counts
  config_flow.py    two-step UI setup with live municipality discovery, options flow
  sensor.py         count sensor + latest-incident sensor
  geo_location.py   one map marker per incident, added/removed as they come and go
  event.py          fires on each newly seen incident
  strings.json      UI labels and help text
  translations/     en, sv
tools/probe_api.py          what the API actually returns, for debugging counts
tests/test_api.py           fetch, paging and window logic
tests/test_real_schema.py   parsing and filtering against real captured rows
tests/test_config_flow.py   flow schemas, defaults, YAML import
tests/stubs/                minimal Home Assistant modules, so tests need no install
dashboard.yaml              Lovelace cards and automations
```
