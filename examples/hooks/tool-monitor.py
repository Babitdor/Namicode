#!/usr/bin/env python3
"""Example hook: Tool Monitor

Monitors tool execution and logs performance metrics.
"""

import sys
import json
from datetime import datetime
from pathlib import Path

# Create logs directory
log_dir = Path.home() / ".nova" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

def main():
    # Read JSON payload from stdin
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        return
    
    event = payload.get('event')
    
    if event == 'tool.call':
        tool_name = payload.get('tool')
        args = payload.get('args', {})
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        
        # Log tool call
        log_entry = {
            "timestamp": timestamp,
            "event": "tool_call",
            "tool": tool_name,
            "args": args
        }
        
        with open(log_dir / "tool_calls.jsonl", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        print(f"[{timestamp}] Tool called: {tool_name}")
        
    elif event == 'tool.result':
        tool_name = payload.get('tool')
        result = payload.get('result', {})
        duration = payload.get('duration', 0)
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        
        # Log tool result
        log_entry = {
            "timestamp": timestamp,
            "event": "tool_result",
            "tool": tool_name,
            "duration": duration,
            "success": "error" not in result
        }
        
        with open(log_dir / "tool_calls.jsonl", "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        print(f"[{timestamp}] Tool completed: {tool_name} ({duration:.2f}s)")
        
        # Alert on slow operations
        if duration > 5.0:
            with open(log_dir / "slow_operations.log", "a") as f:
                f.write(f"{timestamp} - {tool_name} took {duration:.2f}s\n")

if __name__ == '__main__':
    main()