#!/bin/bash
# SNS Poster — cron wrapper script
# Runs the SNS posting pipeline from the local machine.
# Usage: Add to crontab, e.g. every day at 9:00 and 18:00 JST
#   0 9,18 * * * /Users/miyu/dev/business-automation/scripts/run_sns_poster.sh

set -euo pipefail

PROJECT_DIR="/Users/miyu/dev/business-automation"
LOG_FILE="$PROJECT_DIR/data/logs/sns_poster_cron.log"
PYTHON="/Users/miyu/.pyenv/versions/3.9.13/bin/python3"

# Ensure .env is loaded by running from project dir
cd "$PROJECT_DIR"

# Create log dir if missing
mkdir -p "$PROJECT_DIR/data/logs"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') SNS poster cron start ===" >> "$LOG_FILE"

"$PYTHON" scripts/2_sns_poster.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "=== $(date '+%Y-%m-%d %H:%M:%S') SNS poster cron end (exit=$EXIT_CODE) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
