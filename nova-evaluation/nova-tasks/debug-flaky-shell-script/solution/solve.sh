#!/bin/bash
# Reference solution for nova/debug-flaky-shell-script.
set -e
cd /app

cat > report.sh <<'EOF'
#!/bin/bash
# Generates a summary report from a data file.
# Usage: ./report.sh <data-file> <output-file>

DATA_FILE="$1"
OUTPUT_FILE="$2"

if [ ! -f "$DATA_FILE" ]; then
  echo "Error: data file not found: $DATA_FILE" >&2
  exit 1
fi

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

if ! sort "$DATA_FILE" > "$TMP_FILE"; then
  echo "Error: sort failed" >&2
  exit 1
fi

wc -l "$TMP_FILE" > "$OUTPUT_FILE"
echo "Report written to $OUTPUT_FILE"
EOF
chmod +x report.sh

python -m pytest tests/ -q
