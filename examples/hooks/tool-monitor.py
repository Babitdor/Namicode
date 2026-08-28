#!/usr/bin/env python3
"""tool-monitor.py — Prints tool call/result events to a log file.

Install: Copy to ~/.nova/hooks/tool-monitor.py and make executable.
The hook receives a JSON payload on stdin with event details.

Payload example (tool.call):
  {"event": "tool.call", "tool": "shell", "args": "ls -la",
   "session_id": "abc-123"}

Payload example (tool.result):
  {"event": "tool.result", "tool": "shell", "status": "success",
   "preview": "file1.py\\nfile2.py", "session_id": "abc-123"}
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path.home() / ".nova" / "logs" / "tool-hooks.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    event = payload.get("event", "?")
    tool = payload.get("tool", "?")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if event == "tool.call":
        args = payload.get("args", "")[:100]
        line = f"[{timestamp}] CALL  tool={tool} args={args!r}\n"
    elif event == "tool.result":
        status = payload.get("status", "?")
        line = f"[{timestamp}] RESULT tool={tool} status={status}\n"
    else:
        line = f"[{timestamp}] {event} tool={tool}\n"

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()