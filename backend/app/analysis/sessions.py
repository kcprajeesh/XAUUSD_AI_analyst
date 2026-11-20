"""Configurable wall-clock session labels using IANA timezone rules."""
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class SessionDefinition:
    name: str
    timezone: str
    start: time
    end: time

DEFAULT_SESSIONS = (
    SessionDefinition("asian", "Asia/Qatar", time(8), time(15)),
    SessionDefinition("london", "Europe/London", time(8), time(17)),
    SessionDefinition("new_york", "America/New_York", time(8), time(17)),
)

def classify_sessions(instant: datetime, definitions: tuple[SessionDefinition, ...] = DEFAULT_SESSIONS) -> tuple[str, ...]:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("session classification requires an aware timestamp")
    active = []
    for item in definitions:
        local = instant.astimezone(ZoneInfo(item.timezone))
        inside = item.start <= local.timetz().replace(tzinfo=None) < item.end if item.start <= item.end else (
            local.timetz().replace(tzinfo=None) >= item.start or local.timetz().replace(tzinfo=None) < item.end)
        if inside:
            active.append(item.name)
    if "london" in active and "new_york" in active:
        active.append("london_new_york_overlap")
    return tuple(active)
