"""Stub of homeassistant.config_entries, enough to import a config flow."""
SOURCE_IMPORT = "import"

class ConfigEntry:  # noqa: D101
    def __init__(self, data=None, options=None, title="", entry_id="e1"):
        self.data = data or {}
        self.options = options or {}
        self.title = title
        self.entry_id = entry_id

class ConfigFlowResult(dict):  # noqa: D101
    pass

class _BaseFlow:
    hass = None
    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}
    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}
    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}
    def _async_abort_entries_match(self, match):
        return None

class ConfigFlow(_BaseFlow):  # noqa: D101
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

class OptionsFlow(_BaseFlow):  # noqa: D101
    _config_entry = None
    @property
    def config_entry(self):
        return self._config_entry
