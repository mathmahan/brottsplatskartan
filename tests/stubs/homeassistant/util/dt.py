"""Minimal stand-in for homeassistant.util.dt, enough for api.py."""
from datetime import datetime, timezone

UTC = timezone.utc

def parse_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

def utcnow():
    return datetime.now(UTC)

def utc_from_timestamp(ts):
    return datetime.fromtimestamp(ts, UTC)
