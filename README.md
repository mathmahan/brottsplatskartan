# Brottsplatskartan (local)

A private replacement for the core `brottsplatskartan` integration, built to fix
the three things that made the official one confusing:

| | Official integration | This one |
|---|---|---|
| Area granularity | County only (`Stockholms län`) | County fetch, filtered to municipalities (`Stockholm`) |
| Time window | Calendar day, resets at local midnight | Rolling N hours (default 24) |
| Poll interval | Hardcoded 30 min | Configurable, default 15 min, floor 5 min |
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

Then restart Home Assistant. You can run this alongside the official
integration — the domain is different, so nothing collides.

## Configure

In `configuration.yaml`:

```yaml
brottsplatskartan_local:
  area: "Stockholms län"
  municipalities:
    - Stockholm
  hours: 24
  scan_interval: "00:15:00"
```

| Option | Default | Notes |
|---|---|---|
| `area` | `Stockholms län` | Must be one of the 21 counties the API accepts. |
| `municipalities` | `[]` | Filters the county down. Empty = whole county. Matching ignores case and the `kommun`/`stad` suffixes, so `Stockholm`, `Stockholms kommun` and `Stockholms stad` are the same thing. |
| `hours` | `24` | Rolling window, 1–168. |
| `scan_interval` | `00:15:00` | Minimum 5 minutes — the API rate-limits per app id. |
| `max_pages` | `6` | Pagination safety stop. Raise it if a wide window looks truncated. |
| `max_attribute_incidents` | `25` | How many incidents to put in the sensor attributes. `0` omits the list. |
| `location_keys` | *(auto)* | Override which API fields are treated as the municipality. Only needed if the API renames them — see `probe_api.py`. |
| `app_id` | `ha-<machine id>` | Rate-limit identity. Keep it stable. |

## Entities

- **`sensor.brottsplatskartan_stockholm_incidents`** — count in the window.
  Attributes: `by_type` (per-crime-type counts), `incidents` (the full list),
  `window_hours`, `area`, `municipalities`, `fetched_in_county`.
- **`sensor.brottsplatskartan_stockholm_latest_incident`** — newest headline,
  with `description` and `url` in attributes.
- **`geo_location.*`** — one map marker per incident that has coordinates, with
  `distance` from home in km. Add the Map card with `geo_location_sources: [brottsplatskartan_local]`.
- **`event.brottsplatskartan_stockholm_new_incident`** — fires `new_incident`
  each time an unseen incident appears. A restart does not replay the window.

Every new incident is also put on the event bus as `brottsplatskartan_local_new_incident`,
which is easier to consume when several arrive in the same poll (the event
entity only holds the most recent).

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

26 checks covering the rolling window, pagination, both upstream bugs,
de-duplication, rate limiting, field parsing and municipality normalization.
They run against a fake API server with stubbed Home Assistant modules
(`tests/stubs/`), so no Home Assistant install is required and no real network
request is made.

## Layout

```
custom_components/brottsplatskartan_local/
  api.py           direct API client: paging, window filter, field normalization
  coordinator.py   DataUpdateCoordinator, municipality filtering, per-type counts
  sensor.py        count sensor + latest-incident sensor
  geo_location.py  one map marker per incident, added/removed as they come and go
  event.py         fires on each newly seen incident
tools/probe_api.py what the API actually returns, for debugging counts
tests/test_api.py  the suite above
```
