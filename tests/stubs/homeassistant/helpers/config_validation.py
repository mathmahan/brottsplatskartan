"""Stub of homeassistant.helpers.config_validation."""
def ensure_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]

def string(value):
    return str(value)
