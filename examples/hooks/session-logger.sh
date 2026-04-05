#!/bin/bash
# Example hook: Session Logger
# Logs all session events to a file

# Read JSON payload from stdin
read -r payload

# Parse event type
event=$(echo "$payload" | jq -r '.event')

# Create logs directory if it doesn't exist
mkdir -p ~/.nova/logs

# Log to file with timestamp
echo "$(date -Iseconds) [$event] $payload" >> ~/.nova/logs/hooks.log

# Send to webhook for session.end events
if [ "$event" = "session.end" ]; then
    # Extract session ID and duration
    session_id=$(echo "$payload" | jq -r '.session_id')
    duration=$(echo "$payload" | jq -r '.duration')
    message_count=$(echo "$payload" | jq -r '.message_count')
    
    # Log summary
    echo "Session $session_id ended: $message_count messages, ${duration}s duration" >> ~/.nova/logs/sessions.log
    
    # Optional: Send to webhook
    # curl -X POST https://api.example.com/webhook \
    #     -H "Content-Type: application/json" \
    #     -d "$payload"
fi