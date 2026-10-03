#!/bin/sh
set -e

echo "============ Init heis-o-mat ============"

# Validate essential configuration
if [ -z "${HEISE_USERNAME}" ] || [ -z "${HEISE_PASSWORD}" ]; then
    echo "[WARN] HEISE_USERNAME or HEISE_PASSWORD is not set. Downloads will fail unless configured via .env or environment."
fi

# Make Docker environment variables available to cron with restricted permissions
export -p > /app/env.sh
chmod 600 /app/env.sh

# Sanitize and default CRON_SCHEDULE (strip literal quotes)
CRON_SCHEDULE=$(echo "${CRON_SCHEDULE:-0 10 * * 6}" | tr -d '"'"'")

# Configure cron job
mkdir -p /var/spool/cron/crontabs
echo "${CRON_SCHEDULE} . /app/env.sh && /app/start-downloads.sh > /proc/1/fd/1 2>&1" > /var/spool/cron/crontabs/root
echo "[INIT] Cron job configured: ${CRON_SCHEDULE}"

# Convert value to lowercase for flexible boolean checking
STARTUP_VAL=$(echo "${RUN_ON_STARTUP}" | tr '[:upper:]' '[:lower:]')

# Accepts: true, yes, 1
if [ "$STARTUP_VAL" = "true" ] || [ "$STARTUP_VAL" = "yes" ] || [ "$STARTUP_VAL" = "1" ]; then
    echo "[INIT] Starting initial download in the background..."
    /app/start-downloads.sh > /proc/1/fd/1 2>&1 &
else
    echo "[INIT] Initial download skipped (RUN_ON_STARTUP=${RUN_ON_STARTUP})"
fi

echo "============ Initialization finished. heis-o-mat ready ============"

# Start crond in the foreground
exec crond -f -l 2