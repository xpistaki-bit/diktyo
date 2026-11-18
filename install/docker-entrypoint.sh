#!/bin/sh
# Startet im Docker-Container den Hintergrunddienst (Netzscan) und die Web-App.
set -e
(
  while true; do
    python -m app.worker || true
    echo "diktyo-worker beendet, Neustart in 5 s"
    sleep 5
  done
) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${DIKTYO_PORT:-8090}"
