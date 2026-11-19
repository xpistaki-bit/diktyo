#!/usr/bin/env bash
# Erzeugt die Bilder der Einstiegsanleitung (docs/img/start/*.webp) aus einem Demo-Netz (nur 192.0.2.x).
# Voraussetzung: .venv mit requirements.txt, playwright und pillow; Browser über "playwright install chromium"
# oder CHROME=/pfad/zu/chrome.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
OUT=docs/img/start
WORK=$(mktemp -d)
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$WORK"' EXIT
mkdir -p "$OUT"
for L in de en; do
  mkdir -p "$WORK/$L/demo" "$WORK/$L/empty"
  DEMO_LANG=$L DIKTYO_DATA="$WORK/$L/demo" PYTHONPATH=$PWD $PY tools/docs/demo_seed.py >/dev/null
  DIKTYO_DATA="$WORK/$L/demo" .venv/bin/uvicorn app.main:app --port 8191 --log-level warning & A=$!
  DIKTYO_DATA="$WORK/$L/empty" .venv/bin/uvicorn app.main:app --port 8192 --log-level warning & B=$!
  sleep 3
  $PY tools/docs/guide_shots.py $L http://localhost:8191 http://localhost:8192 "$WORK"
  kill $A $B; wait $A $B 2>/dev/null || true
done
$PY - "$WORK" "$OUT" <<'PY'
import glob, os, sys
from PIL import Image
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.png"))):
    Image.open(f).convert("RGB").save(os.path.join(sys.argv[2], os.path.basename(f)[:-4] + ".webp"), quality=88, method=6)
PY
echo "Bilder in $OUT"
