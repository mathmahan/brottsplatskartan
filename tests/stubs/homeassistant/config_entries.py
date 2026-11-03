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

class AbortFlow(Exception):
    """Raised by the stub when a flow aborts."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class _BaseFlow:
    hass = None
    unique_id = None
    #: Unique ids the stub should treat as already configured.
    configured_unique_ids: set = set()
    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}
    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}
    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}
    def _async_abort_entries_match(self, match):
        return None

    async def async_set_unique_id(self, unique_id, *, raise_on_progress=True):
        self.unique_id = unique_id
        return None

    def _abort_if_unique_id_configured(self, updates=None, reload_on_update=True):
        if self.unique_id in self.configured_unique_ids:
            raise AbortFlow("already_configured")

class ConfigFlow(_BaseFlow):  # noqa: D101
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

class OptionsFlow(_BaseFlow):  # noqa: D101
    _config_entry = None
    @property
    def config_entry(self):
        return self._config_entry
