# Brottsplatskartan (local)

A private replacement for Home Assistant's core `brottsplatskartan`
integration, built to fix what made the official one confusing — and then to
go rather further.

| | Official | This |
|---|---|---|
| Area granularity | County only (`Stockholms län`) | County fetch, filtered to **municipalities or districts** (`Stockholm`, `Kungsholmen`) |
| Time window | Calendar day, resets at midnight | Rolling 1–168 h |
| Poll interval | Hardcoded 30 min | Configurable in the UI, 5 min floor |
| Configuration | Config entry, county only | Everything in the UI, county included |
| Entities | One count sensor | Count, latest, nearest, proximity flag, map markers, event |
| Actions | none | `refresh`, `get_incidents` (returns response data) |
| Empty page mid-pagination | Discards everything → count hits 0 | Keeps it |
| Out-of-order row | Stops paging → undercounts | Pages until a full page is out of window |

It talks to the API directly and does **not** use the `brottsplatskartan` PyPI
package, so none of its bugs are inherited.

## Install

Add this repository to HACS as a custom repository (category: Integration), or
copy the folder in by hand:

```bash
cp -r custom_components/brottsplatskartan_local <config>/custom_components/
```

Restart Home Assistant, then **Settings → Devices & services → Add
integration** and search for *Brottsplatskartan (local)*.

It runs happily alongside the official integration — different domain, nothing
collides. You can add it more than once, for example one entry for your own
municipality and another for the whole county.

> **There is no YAML configuration.** If an old `brottsplatskartan_local:`
> block is still in `configuration.yaml`, delete it. Home Assistant will tell
> you so in Repairs and ignore the block in the meantime; it will not break
> your configuration.

## Configure

Setup is two steps in the UI:

1. **Pick a county.** The API's `area` parameter accepts nothing finer.
2. **Narrow it down and tune it.** The integration queries that county first
   and lists the municipalities actually reporting incidents right now, so you
   pick from live values rather than a hard-coded table that would go stale.
   The field is open, so you can also type a **district** — `Kungsholmen`,
   `Södermalm`, `Norrmalm` — because the filter matches any component of the
   reported location. Leave it empty for the whole county.

Everything is editable afterwards, with no restart and no YAML:

| Where | What |
|---|---|
| **Configure** | places, time window, update interval, nearby radius, and an *Advanced* section for attribute/marker/page caps, the location fields and the API client id |
| **Reconfigure** (⋮ on the entry) | the county |

| Option | Default | Notes |
|---|---|---|
| County | `Stockholms län` | Changed via Reconfigure. |
| Municipalities or districts | *(empty)* | Empty = whole county. Case- and suffix-insensitive, so `Stockholm` ≡ `Stockholms kommun` ≡ `Stockholms stad`. Comparison is exact, so `Stockholmsvägen` in Nacka does *not* count as Stockholm. |
| Time window | `24 h` | Rolling, 1–168 h. Does not reset at midnight. |
| Update interval | `15 min` | Minimum 5 — the API rate-limits per installation. |
| Nearby radius | `1 km` | How close an incident must be for the proximity sensor to turn on. |
| Incidents listed in attributes | `25` | For dashboard cards. `0` omits the list. |
| Maximum map markers | `100` | A wide window over a county can return hundreds; the newest are kept. `0` = no cap. |
| Maximum API pages per update | `6` | Pagination safety stop. Raise it if a long window looks truncated. |
| Location fields | *(auto)* | Which API fields count as place names. Only touch it if the API renames them. |
| API client id | `ha-<machine id>` | Rate-limit identity. Change it only if you are being rate limited. |

The UI is translated into English and Swedish. Entity names are deliberately
left in English so entity ids do not change with Home Assistant's language.

## Entities

- **`sensor.<entry>_incidents`** — count in the window. Attributes: `by_type`
  (per-crime-type counts), `incidents` (the full list, each with `title`,
  `type`, `place`, `location`, `description`, `url`, `source_url`,
  `date_human`, coordinates and `distance_km`), `window_hours`, `area`,
  `municipalities`, `fetched_in_county`, `truncated`.
- **`sensor.<entry>_latest_incident`** — newest headline, with the same fields
  plus `image` / `image_wide`: the API's own rendered map thumbnail. Images
  are only on this entity and in events — the URLs run to several hundred
  characters, so a list of 25 would overflow what the recorder stores.
- **`sensor.<entry>_nearest_incident`** — kilometres to the closest incident,
  with that incident in its attributes.
- **`binary_sensor.<entry>_incident_nearby`** — on while the nearest incident
  is inside the configured radius, with the tripping incident attached.
  Trigger proximity automations on this; no template needed.
- **`geo_location.*`** — one marker per incident with coordinates, named
  `<type>: <place>` (e.g. `Stöld: Kungsholmen`), distance from home as its
  state, and the headline, description, both links and the map image in its
  attributes. **Add `geo_location_sources` to the Map card or nothing
  appears.** These entities carry no `unique_id` on purpose, so they do not
  accumulate in the entity registry.
- **`event.<entry>_new_incident`** — fires `new_incident` per unseen incident.
  A restart does not replay the window.

Every new incident also goes on the event bus as
`brottsplatskartan_local_new_incident`, which is easier to consume when
several arrive in one poll (the event entity holds only the most recent).

## Actions

Both are in **Developer Tools → Actions**, targeted at the count sensor.

- **`brottsplatskartan_local.refresh`** — fetch now instead of waiting.
- **`brottsplatskartan_local.get_incidents`** — returns the incidents as
  response data, for scripts and templates. Not capped by the attribute limit,
  and it does include the map images. Optional `limit`, `incident_type` (case
  insensitive) and `within_km` filters.

```yaml
action: brottsplatskartan_local.get_incidents
target:
  entity_id: sensor.brottsplatskartan_stockholm_incidents
data:
  incident_type: [Stöld, Rån]
  within_km: 2
response_variable: nearby
```

## Dashboard

Two versions, same data. Pick by how you prefer to make changes.

| | `dashboard.yaml` | `dashboard-simple.yaml` |
|---|---|---|
| Cards | 8 | 8 |
| Entity ids to edit | only the 4 non-templatable cards | 8 places, marked `<<<` |
| Editable in the visual editor | no (markdown templates) | **yes, every card** |
| Per-crime-type breakdown | yes | no |
| Incident feed with links | yes | no (click a map marker instead) |
| Static map image | yes | no |

Paste either whole file into:

> Settings → Dashboards → *your dashboard* → ✏️ → ⋮ → **Raw configuration editor**

For a single card, use **Add card → Manual** and paste one entry from under
`cards:`.

### Changing the wording

Every markdown card in `dashboard.yaml` opens with a block like this, and
nothing outside it needs touching:

```jinja
{#- ===== TEXT — change these and nothing else ===== -#}
{% set t_incidents = "händelser senaste" %}
{% set t_hours = "h" %}
{% set t_none = "Inga händelser i fönstret." %}
{#- ===== end of text ===== -#}
```

Card headings are the plain `title:` keys, so those are ordinary YAML.

### Entity ids

The markdown cards find their sensors through
`integration_entities('brottsplatskartan_local')`, so they work whatever your
entry is named and survive a rename. Graph, entities and conditional cards
cannot take a template, so those four keep literal ids — grouped together and
commented.

`dashboard-simple.yaml` uses literal ids throughout. That is the trade for
being clickable in the visual editor, which cannot evaluate a template.

## Optional extras

`examples/` holds things that are **not required** — the integration needs
nothing in `configuration.yaml`.

- **`examples/configuration.yaml`** — a single-crime-type template sensor, and
  recorder exclusions to keep the database small.
- **`examples/automations.yaml`** — two automations as a list, for the file
  `automation: !include automations.yaml` points at.
- **`examples/ui-editor/*.yaml`** — the same two as single objects, for
  **Settings → Automations & scenes → Create automation → ⋮ → Edit in YAML**.

> Each ui-editor file is a single automation **object**. Paste a list —
> anything starting with `- ` — and Home Assistant answers *"Message
> malformed: not a valid option at `['0']`"*, because the frontend turns the
> list into an object keyed `"0"`.

If your `configuration.yaml` already has a `template:` or `recorder:` key,
merge the items into the one you have; duplicate keys at the same level make
Home Assistant reject the whole configuration.

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

## Troubleshooting

### Every incident appears twice on the map

**1. The map card has `hours_to_show`.** That option makes the card draw each
entity's *recorded history* as well as its current position. An incident never
moves, so every marker gets a second pin at the same spot. Remove the line.
Neither dashboard sets it.

**2. Two config entries cover the same incidents.** Check **Settings →
Devices & services**: one entry for `Stockholm` and another for the whole
county gives every Stockholm incident a marker from each. The integration
raises a **Repairs** issue naming both when it detects this. Delete whichever
you do not want.

Entries are identified by county plus their normalized, sorted place list, so
a second entry over the same places is refused outright. To count what you
have, in **Developer Tools → Template**:

```jinja
{{ states.geo_location | selectattr('attributes.source', 'eq', 'brottsplatskartan_local') | list | count }} markers
{{ states.geo_location | selectattr('attributes.source', 'eq', 'brottsplatskartan_local') | map(attribute='attributes.incident_id') | unique | list | count }} distinct incidents
```

Numbers **differ** → cause 2. Numbers **match** but the map looks doubled →
cause 1. The difference need not be a clean doubling: a county entry (10
incidents) beside a Stockholm entry (4 of those 10) gives 14 markers for 10
incidents.

### The count is 0 but the county has incidents

The place filter matched nothing. The count sensor then exposes
`places_seen_in_county`, listing what the API actually returned — put one of
those in the filter. To look directly:

```bash
python3 tools/probe_api.py "Stockholms län" Stockholm
```

Plain stdlib, no Home Assistant needed. It prints every field name on the
first row, which location fields are present, and today-vs-24h counts side by
side, so you can see exactly where a number comes from. Its matching mirrors
the integration's, so its counts are the sensor's counts.

## Tests

Two layers.

**Pure logic**, no Home Assistant install required:

```bash
pip install aiohttp voluptuous pyyaml
python3 tests/run_all.py
```

- `test_api.py` — paging, the rolling window, both upstream bugs,
  de-duplication, rate limiting, against a fake API server.
- `test_real_schema.py` — parsing rows captured verbatim from the live API,
  plus entry identity. Pins the filtering traps: a street called
  `Stockholmsvägen` in Nacka must not count as Stockholm, and a row whose only
  location is `Stockholms län` must match no municipality.
- `test_examples.py` — the *shape* of the YAML examples, not just their syntax:
  that the dashboards are `views` mappings and not bare card lists, that no
  example uses a key a stock `configuration.yaml` already defines, that the
  ui-editor files are objects rather than lists, and that nothing still points
  at a retired template sensor. Each of those was wrong at some point while
  being perfectly valid YAML.

**Against real Home Assistant**, driving the genuine config flow, entity
platform, service registry and issue registry:

```bash
pip install pytest-homeassistant-custom-component
pytest tests_ha
```

- `test_config_flow.py` — the user flow end to end, discovery failing without
  blocking setup, duplicate places aborting, the options flow renaming and
  re-identifying the entry, a saved `0` surviving, and the reconfigure flow
  changing the county.
- `test_init.py` — the exact entity ids the dashboards reference and their
  states, markers matching the nearest sensor, the proximity sensor on both
  sides of its radius, both actions and their filters, the overlap repair
  issue, unique-id backfill and unload.

`run_all.py` exits non-zero if any suite fails — run it that way rather than
looping over the files in a shell, which reports only the last suite's status.

## Layout

```
custom_components/brottsplatskartan_local/
  api.py             direct API client: paging, window filter, field normalization
  coordinator.py     polling, place filtering, per-type counts, distances
  config_flow.py     config, reconfigure and options flows with live discovery
  sensor.py          count, latest and nearest sensors, plus the two actions
  binary_sensor.py   proximity flag
  geo_location.py    one map marker per incident
  event.py           fires on each newly seen incident
  services.yaml      action descriptions
  strings.json       UI labels, help text, repair issues
  translations/      en, sv
tools/probe_api.py           what the API actually returns, for debugging counts
tests/                       pure-logic suites + run_all.py
tests_ha/                    real Home Assistant integration tests
dashboard.yaml               8 cards, auto-discovered ids, text hoisted
dashboard-simple.yaml        8 native cards, no templates, UI-editable
examples/                    optional template sensor, recorder, automations
```

## Versions

Developed and tested against Home Assistant **2026.2.3**. `hacs.json`
declares a minimum of 2025.2.0, which is when the newest APIs used here
(`DataUpdateCoordinator`'s `config_entry` argument, the no-argument options
flow constructor, reconfigure flows) were all available.
