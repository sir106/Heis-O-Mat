#!/bin/bash
set -e

echo "============ Init heis-o-mat ============"

# Docker-Umgebungsvariablen für Cron verfügbar machen
printenv | grep -v "no_proxy" > /etc/environment

# Cronjob konfigurieren
mkdir -p /var/spool/cron/crontabs
echo "${CRON_SCHEDULE} /app/start-downloads.sh > /proc/1/fd/1 2>&1" > /var/spool/cron/crontabs/root
echo "[INIT] Cronjob konfiguriert: ${CRON_SCHEDULE}"

# Optionaler Erststart auf Wunsch
if [ "${RUN_ON_STARTUP}" = "true" ]; then
    echo "[INIT] Starte initialen Download im Hintergrund..."
    /app/start-downloads.sh &
else
    echo "[INIT] Initialer Download übersprungen (RUN_ON_STARTUP=${RUN_ON_STARTUP})"
fi

echo "============ Initialization finished. heis-o-mat ready ============"

# Crond im Vordergrund starten
exec crond -f -l 2