"""Stub of homeassistant.helpers.config_validation."""
def ensure_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]

def string(value):
    return str(value)


def time_period(value):
    """Minimal stand-in for cv.time_period: HH:MM:SS, seconds, or timedelta."""
    from datetime import timedelta

    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if isinstance(value, str):
        parts = [float(p) for p in value.split(":")]
        while len(parts) < 3:
            parts.append(0.0)
        hours, minutes, seconds = parts[:3]
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    if isinstance(value, dict):
        return timedelta(**value)
    raise ValueError(f"not a time period: {value!r}")
