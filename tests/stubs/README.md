# Test stubs

Just enough of `homeassistant` for `api.py` and `const.py` to import, so the
pure-logic suites in `../` run with no Home Assistant installed: the API
client, the field parsing, the place matching and the YAML example shapes.

Anything that needs the real config flow, entity platform, service registry or
issue registry is tested in `../../tests_ha/` against an actual Home Assistant
instance, via `pytest-homeassistant-custom-component`. Do not grow these stubs
to cover that — a fake Home Assistant that drifts from the real one is worse
than no test.
