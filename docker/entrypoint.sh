#!/bin/bash
set -e

echo "============ Init heis-o-mat ============"

# Make Docker environment variables available to cron
export -p > /app/env.sh

# Configure cron job
mkdir -p /var/spool/cron/crontabs
echo "${CRON_SCHEDULE} . /app/env.sh && /app/start-downloads.sh > /proc/1/fd/1 2>&1" > /var/spool/cron/crontabs/root
echo "[INIT] Cron job configured: ${CRON_SCHEDULE}"

# Convert value to lowercase for flexible boolean checking
STARTUP_VAL=$(echo "${RUN_ON_STARTUP}" | tr '[:upper:]' '[:lower:]')

# Accepts: true, yes, 1
if [ "$STARTUP_VAL" = "true" ] || [ "$STARTUP_VAL" = "yes" ] || [ "$STARTUP_VAL" = "1" ]; then
    echo "[INIT] Starting initial download in the background..."
    /app/start-downloads.sh &
else
    echo "[INIT] Initial download skipped (RUN_ON_STARTUP=${RUN_ON_STARTUP})"
fi

echo "============ Initialization finished. heis-o-mat ready ============"

# Start crond in the foreground
exec crond -f -l 2