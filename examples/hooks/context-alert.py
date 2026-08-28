#!/usr/bin/env python3
"""context-alert.py — Sends a desktop notification when context usage is high.

Install: Copy to ~/.nova/hooks/context-alert.py and make executable.
Requires: pip install plyer (cross-platform desktop notifications)

Payload example (context.warning):
  {"event": "context.warning", "level": "critical",
   "usage_percentage": 92.5, "session_id": "abc-123"}
"""

import json
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    level = payload.get("level", "warning")
    pct = payload.get("usage_percentage", 0)
    session = payload.get("session_id", "?")[:8]

    try:
        from plyer import notification
        title = "Nova Context Alert" if level == "warning" else "Nova Context CRITICAL"
        message = f"Context usage at {pct:.0f}% (session {session})"
        notification.notify(title=title, message=message, timeout=10)
    except ImportError:
        # Fallback: write to log
        from pathlib import Path
        from datetime import datetime, timezone
        log = Path.home() / ".nova" / "logs" / "context-alerts.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with log.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] level={level} pct={pct:.0f}% session={session}\n")


if __name__ == "__main__":
    main()