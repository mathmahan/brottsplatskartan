"""Exercise the fetch/page/filter logic against a fake Brottsplatskartan API.

Run from anywhere:

    python3 tests/test_api.py

No Home Assistant install is needed. `tests/stubs/homeassistant/` provides just
enough of `homeassistant.util.dt` and `homeassistant.const` for `api.py` and
`const.py` to import, and the component directory is mounted as a synthetic
`bpk` package so the real `api.py` is exercised without running the component's
`__init__.py` (which does need the full Home Assistant runtime).
"""

import asyncio
import importlib
import pathlib
import sys
import types
from datetime import timedelta

import aiohttp
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "brottsplatskartan_local"

sys.path.insert(0, str(ROOT / "tests" / "stubs"))

_pkg = types.ModuleType("bpk")
_pkg.__path__ = [str(COMPONENT)]
sys.modules["bpk"] = _pkg

api_mod = importlib.import_module("bpk.api")
async_fetch_incidents = api_mod.async_fetch_incidents
filter_by_municipality = api_mod.filter_by_municipality
normalize_place = api_mod.normalize_place

from homeassistant.util import dt as dt_util  # noqa: E402

NOW = dt_util.utcnow()
FAILURES = []


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILURES.append(name)


def row(n, hours_ago, kommun="Stockholm", kind="Stöld", lat="59.33", lng="18.07"):
    ts = (NOW - timedelta(hours=hours_ago)).astimezone()
    return {
        "id": n,
        "pubdate_iso8601": ts.isoformat(),
        "title": f"{kind}, {kommun}",
        "title_type": kind,
        "administrative_area_level_1": "Stockholms län",
        "administrative_area_level_2": kommun,
        "lat": lat,
        "lng": lng,
        "permalink": f"https://brottsplatskartan.se/handelse/{n}",
    }


def make_app(pages, *, ratelimit=False):
    """Serve `pages` (a list of row-lists) as a paginated API."""
    seen_params = []

    async def handler(request):
        seen_params.append(dict(request.query))
        if ratelimit:
            return web.json_response({}, headers={"x-ratelimit-reset": "1800000000"})
        idx = int(request.query.get("page", 1)) - 1
        data = pages[idx] if 0 <= idx < len(pages) else []
        body = {"data": data}
        if idx + 1 < len(pages):
            body["links"] = {
                "next_page_url": f"{request.url.with_query({'page': idx + 2})}"
            }
        return web.json_response(body)

    app = web.Application()
    app.router.add_get("/api/events", handler)
    return app, seen_params


async def serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return runner, f"http://127.0.0.1:{port}/api/events"


async def fetch(pages, *, hours=24, max_pages=10, ratelimit=False):
    app, seen = make_app(pages, ratelimit=ratelimit)
    runner, url = await serve(app)
    api_mod.EVENTS_URL = url
    try:
        async with aiohttp.ClientSession() as session:
            got = await async_fetch_incidents(
                session,
                app_id="ha-test",
                area="Stockholms län",
                since=NOW - timedelta(hours=hours),
                max_pages=max_pages,
            )
        return got, seen
    finally:
        await runner.cleanup()


async def main():
    # 1. Rolling window: only rows inside the window count, and a row from
    #    yesterday evening (20h ago) is INSIDE a 24h window even though it is
    #    not "today".
    got, _ = await fetch([[row(1, 1), row(2, 20), row(3, 30)]])
    check("rolling 24h window keeps 20h-old row, drops 30h-old", [i.uid for i in got], ["1", "2"])

    # 2. Pagination: collects across pages and stops once a page runs past the
    #    window.
    got, seen = await fetch([[row(1, 1), row(2, 2)], [row(3, 3), row(4, 4)], [row(5, 40)]])
    check("pages forward across 3 pages", [i.uid for i in got], ["1", "2", "3", "4"])
    check("every request carried the app id", all(p.get("app") == "ha-test" for p in seen), True)
    check("app id sent exactly once per request", all("app" in p for p in seen), True)

    # 3. The upstream bug: an empty page must NOT discard earlier results.
    got, _ = await fetch([[row(1, 1), row(2, 2)], [], [row(3, 3)]])
    check("empty middle page keeps earlier rows", [i.uid for i in got], ["1", "2"])

    # 4. The other upstream bug: one out-of-order old row must not truncate the
    #    rest of the page.
    got, _ = await fetch([[row(1, 1), row(99, 40), row(2, 2), row(3, 3)]])
    check("out-of-order old row does not truncate page", [i.uid for i in got], ["1", "2", "3"])

    # 4b. A stray old row on page 1 must not stop us paging to page 2.
    got, _ = await fetch([[row(1, 1), row(99, 40)], [row(2, 2), row(3, 3)], [row(4, 50)]])
    check("stray old row on page 1 does not stop pagination",
          [i.uid for i in got], ["1", "2", "3"])

    # 4c. A page that is entirely outside the window does stop pagination.
    got, seen = await fetch([[row(1, 1)], [row(90, 40), row(91, 41)], [row(2, 2)]])
    check("fully out-of-window page stops pagination", [i.uid for i in got], ["1"])
    check("did not fetch the page after the out-of-window one", len(seen), 2)

    # 5. De-duplication across pages.
    got, _ = await fetch([[row(1, 1), row(2, 2)], [row(2, 2), row(3, 3)]])
    check("duplicate id across pages counted once", [i.uid for i in got], ["1", "2", "3"])

    # 6. max_pages is respected.
    got, _ = await fetch([[row(n, 1)] for n in range(1, 11)], max_pages=3)
    check("max_pages stops paging", len(got), 3)

    # 7. Rate limiting surfaces as its own error.
    try:
        await fetch([[row(1, 1)]], ratelimit=True)
        check("rate limit raises", "no exception", "BpkRateLimited")
    except Exception as err:
        check("rate limit raises BpkRateLimited", type(err).__name__, "BpkRateLimited")

    # 8. Municipality filtering: county -> single kommun.
    got, _ = await fetch(
        [[row(1, 1, "Stockholm"), row(2, 1, "Södertälje"), row(3, 1, "Nacka"),
          row(4, 1, "Stockholms kommun"), row(5, 1, "Solna")]]
    )
    kept = filter_by_municipality(got, {normalize_place("Stockholm")})
    check("filters county down to Stockholm kommun", sorted(i.uid for i in kept), ["1", "4"])

    kept = filter_by_municipality(got, {normalize_place("Stockholm"), normalize_place("Solna")})
    check("multi-municipality filter", sorted(i.uid for i in kept), ["1", "4", "5"])

    check("empty filter = no filtering", len(filter_by_municipality(got, set())), 5)

    # 9. The county name must never match as a municipality.
    check("county name rejected as municipality", normalize_place("Stockholms län"), None)
    check("kommun suffix normalized", normalize_place("Stockholms kommun"), "stockholm")
    check("stad suffix normalized", normalize_place("Stockholms stad"), "stockholm")
    check("plain name normalized", normalize_place("Stockholm"), "stockholm")
    check("name ending in s is consistent", normalize_place("Hofors"), normalize_place("Hofors kommun"))

    # 10. Parsed fields survive.
    got, _ = await fetch([[row(1, 1)]])
    inc = got[0]
    check("type parsed", inc.incident_type, "Stöld")
    check("lat parsed as float", inc.latitude, 59.33)
    check("url parsed", inc.url, "https://brottsplatskartan.se/handelse/1")
    check("municipality parsed", inc.municipality, "Stockholm")

    # 11. Rows missing coordinates or a date are handled, not crashed on.
    bad = [{"id": 7, "pubdate_iso8601": (NOW - timedelta(hours=1)).astimezone().isoformat(),
            "title": "Ingen plats", "title_type": "Övrigt"},
           {"id": 8, "title": "Ingen tid"}]
    got, _ = await fetch([bad])
    check("row without date skipped, row without coords kept", [i.uid for i in got], ["7"])
    check("coord-less row has no latitude", got[0].latitude, None)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all checks passed")
    return 0


sys.exit(asyncio.run(main()))
