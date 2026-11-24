"""Shared colours, so the tray icon and the panel agree on what 40% looks like."""
from __future__ import annotations

GREEN = "#3DDC84"
YELLOW = "#FFB020"
RED = "#FF5A5A"
UNKNOWN = "#9AA0A6"


def level_color(percent: int | None) -> str:
    if percent is None:
        return UNKNOWN
    if percent <= 20:
        return RED
    if percent <= 50:
        return YELLOW
    return GREEN
