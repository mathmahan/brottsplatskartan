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

Two versions, same data. Pick by how you prefer to make changes.

| | `dashboard.yaml` | `dashboard-simple.yaml` |
|---|---|---|
| Cards | 8 | 6 |
| Entity ids to edit | none — auto-discovered | 6 places, marked `<<<` |
| Editable in the visual editor | no (markdown templates) | **yes, every card** |
| Per-crime-type breakdown | yes | no |
| Incident feed with links | yes | no (click a map marker instead) |
| Static map image | yes | no |

Paste either whole file into:

> Settings → Dashboards → *your dashboard* → ✏️ → ⋮ → **Raw configuration editor**

For a single card, use **Add card → Manual** and paste one entry from
under `cards:`.

### Changing the wording

Every markdown card in `dashboard.yaml` opens with a block like this, and
nothing outside it needs touching:

```jinja
{#- ===== TEXT — change these and nothing else ===== -#}
{% set t_incidents = "händelser senaste" %}
{% set t_hours = "h" %}
{% set t_in_county = "händelser i hela" %}
{% set t_same_period = "under samma period" %}
{% set t_none = "Inga händelser i fönstret." %}
{#- ===== end of text ===== -#}
```

Card headings are the plain `title:` keys, so those are ordinary YAML.

### No entity ids to edit

The templated cards find their sensors through
`integration_entities('brottsplatskartan_local')`, so they work whatever your
config entry is named and keep working if you rename it. Only the two graph
cards take literal ids, because graph cards cannot take a template.

`dashboard-simple.yaml` uses literal ids throughout — that is the trade for
being clickable in the visual editor, which cannot evaluate a template. The
spots to change are marked `<<< entity id`.

### What the simple version gives up

The breakdown, the feed and the map image all need templating. You keep access
to the detail either way: click any map marker and the dialog shows the
headline, description, place and both links.

### The rest: template sensors, automations, recorder

A stock Home Assistant `configuration.yaml` already has
`automation: !include automations.yaml`, so these are split by where they
actually belong. Adding a second `automation:` key makes Home Assistant reject
the whole configuration.

**`examples/configuration.yaml`** → append to `configuration.yaml`. Holds
`template:` (the `nearest_incident` sensor the last two cards need, plus a
per-crime-type sensor) and `recorder:` exclusions. If you already have a
`template:` or `recorder:` key, merge the items into the one you have.

Two automations are provided, in two shapes — pick whichever route you use:

**`examples/ui-editor/*.yaml`** → one file per automation, for the UI. Go to
**Settings → Automations & scenes → Create automation → ⋮ → Edit in YAML**
and paste a whole file, replacing what is there. Home Assistant assigns the id
and the automation stays editable in the UI.

> Each of those files is a single automation **object**. If you paste a list —
> anything starting with `- ` — Home Assistant answers *"Message malformed:
> not a valid option at `['0']`"*, because the frontend turns the list into an
> object keyed `"0"` and the automation schema has no such option. That is the
> error to expect if you paste from `automations.yaml` by mistake.

**`examples/automations.yaml`** → the same two automations as a list, for
appending to the file `automation: !include automations.yaml` points at,
leading `- ` and all. Note that Home Assistant rewrites `automations.yaml`
whenever you save any automation in the UI, which strips hand-written
comments.

Both need a restart. Replace `notify.mobile_app_your_phone` with your own
notify service.

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

Two causes, in order of likelihood.

**1. The map card has `hours_to_show`.** That option makes the card draw each
entity's *recorded history* as well as its current position. An incident never
moves, so every marker gets a second pin at exactly the same spot. Remove the
line — the integration's rolling window already decides which markers exist.
The card in `dashboard.yaml` no longer sets it.

**2. You have two config entries covering the same incidents.** Check
**Settings → Devices & services → Brottsplatskartan (local)**: if there are
two entries — say one for `Stockholm` from an imported YAML block and one for
the whole county added in the UI — every Stockholm incident gets a marker from
each. Delete whichever you do not want.

The integration now says so in the log on startup when it spots this:

```
'Brottsplatskartan Stockholm' covers some of the same incidents as
'Brottsplatskartan Stockholms län'. Each entry adds its own map marker per
incident, so incidents in both will appear more than once on the map.
```

Two entries over overlapping areas are a legitimate configuration, so this is
a warning rather than an error. What is *not* legitimate is two entries over
the *same* places, and that was previously easy to create: the duplicate check
compared the place list by equality, so `[Solna, Stockholm]` did not match an
existing `[Stockholm, Solna]`. Entries are now identified by county plus their
normalized, sorted place list, and existing entries have that identity
backfilled on upgrade.

To count what you actually have, in **Developer Tools → Template**:

```jinja
{{ states.geo_location
   | selectattr('attributes.source', 'eq', 'brottsplatskartan_local')
   | list | count }} markers
{{ states.geo_location
   | selectattr('attributes.source', 'eq', 'brottsplatskartan_local')
   | map(attribute='attributes.incident_id') | unique | list | count }} distinct incidents
```

If those two numbers differ, it is cause 2 — more markers exist than there are
incidents, so more than one entry is producing them. If they match but the map
still looks doubled, it is cause 1: the entity count is right and the card is
drawing each one twice.

Note that the difference need not be a clean doubling. A county entry (10
incidents) beside a Stockholm entry (4 of those 10) gives 14 markers for 10
incidents — only the shared 4 are duplicated.

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
pip install aiohttp voluptuous pyyaml
python3 tests/run_all.py
```

`run_all.py` runs every suite and exits non-zero if any fails. Run it that way
rather than looping over the files in a shell, which reports only the last
suite's status and hides a failure in the middle.

Individually:

```bash
python3 tests/test_api.py
```

```bash
python3 tests/test_real_schema.py
python3 tests/test_config_flow.py
python3 tests/test_yaml_import.py
python3 tests/test_examples.py
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

`test_yaml_import.py` runs a real installation's `configuration.yaml` block
through `CONFIG_SCHEMA` and the import step, checking that
`scan_interval: "00:15:00"` becomes 15 whole minutes (a config entry is JSON
and cannot hold a timedelta) and that a too-short interval is rejected rather
than silently raised.

`test_examples.py` checks the *shape* of `dashboard.yaml` and the example
config files — that the dashboard is a mapping with `views` rather than a bare
card list, and that nothing is offered under a key a stock
`configuration.yaml` already defines. Both of those were wrong at one point
while being perfectly valid YAML, which is exactly what a parse check misses.

All of them run with stubbed Home Assistant modules (`tests/stubs/`), so no
Home Assistant install is required and no real network request is made.

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
tests/test_config_flow.py   flow schemas and defaults
tests/test_yaml_import.py   a real configuration.yaml block through the import
tests/stubs/                minimal Home Assistant modules, so tests need no install
dashboard.yaml                 8 cards, auto-discovered ids, text hoisted
dashboard-simple.yaml          6 native cards, no templates, UI-editable
examples/configuration.yaml    template sensors + recorder excludes
examples/automations.yaml      two automations, as a list for automations.yaml
examples/ui-editor/            the same two, one object each, for the UI editor
tests/test_examples.py         structural checks on the files above
tests/test_entry_overlap.py    entry identity and overlapping-scope warnings
tests/run_all.py               runs every suite, fails the run if any fails
```
