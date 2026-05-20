#!/usr/bin/env bash
# session-logger.sh — Logs Nova session start/end events to a file.
#
# Install: Copy to ~/.nova/hooks/session-logger.sh and make executable.
# The hook receives a JSON payload on stdin with event details.
#
# Payload example (session.start):
#   {"event": "session.start", "session_id": "abc-123", "thread_id": "...",
#    "assistant_id": "nova-agent", "model": "gpt-4o", "sandbox": "none",
#    "continued": false}

LOG_FILE="$HOME/.nova/logs/session-hooks.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Read payload from stdin
PAYLOAD=$(cat)

# Extract event name and session ID
EVENT=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('event','?'))" 2>/dev/null || echo "?")
SESSION_ID=$(echo "$PAYLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','?')[:8])" 2>/dev/null || echo "?")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "[$TIMESTAMP] event=$EVENT session=$SESSION_ID" >> "$LOG_FILE"