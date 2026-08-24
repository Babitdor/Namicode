#!/bin/bash
# Generates a summary report from a data file.
# Usage: ./report.sh <data-file> <output-file>

DATA_FILE=$1
OUTPUT_FILE=$2

if [ ! -f $DATA_FILE ]; then
  echo "Error: data file not found: $DATA_FILE"
  exit 1
fi

TMP_FILE=/tmp/report.tmp
sort $DATA_FILE > $TMP_FILE
wc -l $TMP_FILE > $OUTPUT_FILE
echo "Report written to $OUTPUT_FILE"
