#!/bin/bash
set -e

echo "============ Init heis-o-mat ============"

# Docker-Umgebungsvariablen für Cron verfügbar machen
printenv | grep -v "no_proxy" > /etc/environment

# Cronjob konfigurieren
mkdir -p /var/spool/cron/crontabs
echo "${CRON_SCHEDULE} /app/start-downloads.sh > /proc/1/fd/1 2>&1" > /var/spool/cron/crontabs/root
echo "[INIT] Cronjob konfiguriert: ${CRON_SCHEDULE}"

# Wert in Kleinbuchstaben umwandeln für flexible Boolean-Prüfung
STARTUP_VAL=$(echo "${RUN_ON_STARTUP}" | tr '[:upper:]' '[:lower:]')

# Akzeptiert: true, yes, 1
if [ "$STARTUP_VAL" = "true" ] || [ "$STARTUP_VAL" = "yes" ] || [ "$STARTUP_VAL" = "1" ]; then
    echo "[INIT] Starte initialen Download im Hintergrund..."
    /app/start-downloads.sh &
else
    echo "[INIT] Initialer Download übersprungen (RUN_ON_STARTUP=${RUN_ON_STARTUP})"
fi

echo "============ Initialization finished. heis-o-mat ready ============"

# Crond im Vordergrund starten
exec crond -f -l 2