#!/usr/bin/env python3
"""Standalone probe for the Brottsplatskartan API. Run it OUTSIDE Home Assistant.

    python3 probe_api.py "Stockholms län" Stockholm

Prints the field names the API actually returns, today's rows with their
municipality, and what a 24h window plus a municipality filter would count.
Use it to confirm the integration's `location_keys` match reality.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

URL = "https://brottsplatskartan.se/api/events"
# Same key order and matching rules as the integration's api.py, so the
# numbers this prints are the numbers the sensor will show.
LOCATION_KEYS = (
    "title_location", "administrative_area_level_2", "admin_area_level_2",
    "kommun", "municipality", "city",
    "location_string_2", "location_string", "location",
)
PLACE_SUFFIXES = (" kommun", " stad", " municipality")


def normalize_place(value):
    """Mirror of api.normalize_place: comparable form, or None for a county."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or text.endswith(" län") or text.endswith(" lan"):
        return None
    for suffix in PLACE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    text = text.strip()
    if text.endswith("s"):
        text = text[:-1]
    return text or None


def place_candidates(row):
    """Every place a row mentions. Comma-separated fields are split up."""
    out = set()
    for key in LOCATION_KEYS:
        value = row.get(key)
        if not isinstance(value, str):
            continue
        for part in value.split(","):
            if (norm := normalize_place(part)) is not None:
                out.add(norm)
    return out


def fetch(area: str, app: str = "ha-probe", max_pages: int = 6) -> list[dict]:
    url = f"{URL}?{urllib.parse.urlencode({'app': app, 'area': area})}"
    rows: list[dict] = []
    for _ in range(max_pages):
        with urllib.request.urlopen(url, timeout=30) as resp:
            if resp.headers.get("x-ratelimit-reset"):
                print("!! rate limited", file=sys.stderr)
                break
            payload = json.load(resp)
        page = payload.get("data") or []
        if not page:
            break
        rows.extend(page)
        nxt = (payload.get("links") or {}).get("next_page_url")
        if not nxt:
            break
        url = nxt
    return rows


def main() -> int:
    area = sys.argv[1] if len(sys.argv) > 1 else "Stockholms län"
    wanted = [a.lower() for a in sys.argv[2:]]

    rows = fetch(area)
    if not rows:
        print("no rows returned")
        return 1

    print(f"=== {len(rows)} rows fetched for {area} ===\n")
    print("--- field names on the first row ---")
    for key in sorted(rows[0]):
        print(f"  {key} = {rows[0][key]!r}"[:160])

    print("\n--- which of the integration's location_keys exist ---")
    for key in LOCATION_KEYS:
        present = sum(1 for r in rows if r.get(key))
        if present:
            sample = next(r[key] for r in rows if r.get(key))
            print(f"  {key}: present on {present}/{len(rows)} rows, e.g. {sample!r}")

    now = datetime.now(timezone.utc)
    windows = {"last 24h": now - timedelta(hours=24)}
    today_local = datetime.now().date()

    def pub(r):
        try:
            return datetime.fromisoformat(r["pubdate_iso8601"])
        except (KeyError, ValueError):
            return None

    print("\n--- counts ---")
    in_today = [r for r in rows if (p := pub(r)) and p.date() == today_local]
    print(f"  published today (what the official integration counts): {len(in_today)}")
    for label, since in windows.items():
        inw = [r for r in rows if (p := pub(r)) and p >= since]
        print(f"  published in the {label}: {len(inw)}")

    if wanted:
        want = {n for w in wanted if (n := normalize_place(w)) is not None}

        def matches(r):
            return bool(place_candidates(r) & want)

        for label, since in windows.items():
            inw = [r for r in rows if (p := pub(r)) and p >= since and matches(r)]
            print(f"  {label} filtered to {wanted}: {len(inw)}")

    print("\n--- distinct places seen (use these to pick municipalities) ---")
    places = Counter()
    for r in rows:
        for key in LOCATION_KEYS:
            if isinstance(v := r.get(key), str) and v.strip():
                places[v.strip()] += 1
    for place, n in places.most_common(40):
        print(f"  {n:4d}  {place}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
