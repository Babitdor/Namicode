#!/usr/bin/env python3
"""error-alert.py — Logs errors and optionally sends a notification.

Install: Copy to ~/.nova/hooks/error-alert.py and make executable.

Payload example (error):
  {"event": "error", "error": "Rate limit exceeded", "type": "RateLimitError",
   "session_id": "abc-123"}
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path.home() / ".nova" / "logs" / "error-hooks.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    error_msg = payload.get("error", "Unknown error")[:200]
    error_type = payload.get("type", "Unknown")
    session = payload.get("session_id", "?")[:8]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] type={error_type} error={error_msg!r} session={session}\n")

    # Optional: send desktop notification via plyer
    try:
        from plyer import notification
        notification.notify(
            title=f"Nova Error: {error_type}",
            message=error_msg[:100],
            timeout=10,
        )
    except ImportError:
        pass


if __name__ == "__main__":
    main()