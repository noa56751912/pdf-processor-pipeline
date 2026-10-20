"""Parse durations written either as "HH:MM" or as decimal hours."""
from __future__ import annotations


def parse_hours(token: str) -> float | None:
    """Return *token* as hours: "00:30" -> 0.5, "0.50" -> 0.5, "" -> None."""
    token = (token or "").strip()
    if not token:
        return None
    if ":" in token:
        hours, _, minutes = token.partition(":")
        try:
            return int(hours) + int(minutes) / 60
        except ValueError:
            return None
    try:
        return float(token)
    except ValueError:
        return None
