"""Time and date tools.

This module provides tools for getting current time information.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from langchain.tools import tool


@tool
def get_current_time() -> dict[str, Any]:
    """Get the current time and date information.

    Returns current time in multiple formats useful for the agent to understand
    temporal context when assisting users.

    Returns:
        Dictionary with:
        - utc_time: Current UTC time in ISO format
        - local_time: Current local time in ISO format
        - timezone: System timezone name
        - date: Current date (YYYY-MM-DD)
        - day_of_week: Day of week name (Monday, Tuesday, etc.)
        - unix_timestamp: Unix timestamp (seconds since epoch)
        - time_12h: Time in 12-hour format (e.g., "2:30 PM")
        - time_24h: Time in 24-hour format (e.g., "14:30")

    Example:
        >>> get_current_time()
        {
            'utc_time': '2025-01-15T14:30:45.123456',
            'local_time': '2025-01-15T15:30:45.123456',
            'timezone': 'Europe/Berlin',
            'date': '2025-01-15',
            'day_of_week': 'Wednesday',
            'unix_timestamp': 1736949045,
            'time_12h': '3:30 PM',
            'time_24h': '15:30'
        }
    """
    now = datetime.now(UTC)
    utc_now = datetime.now(UTC)

    # Format 12-hour time (strip leading zero for cross-platform compatibility)
    hour = now.hour % 12 or 12  # Convert 0 to 12 for 12-hour format
    am_pm = "AM" if now.hour < 12 else "PM"
    time_12h = f"{hour}:{now.minute:02d} {am_pm}"

    return {
        "utc_time": utc_now.isoformat(),
        "local_time": now.isoformat(),
        "timezone": (time.tzname[0] if time.tzname else "Unknown"),
        "date": now.strftime("%Y-%m-%d"),
        "day_of_week": now.strftime("%A"),
        "unix_timestamp": int(now.timestamp()),
        "time_12h": time_12h,
        "time_24h": now.strftime("%H:%M"),
    }
