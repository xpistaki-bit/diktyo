#!/usr/bin/env bash
# Update aus der Weboberfläche: läuft als root, gestartet von diktyo-update.path, sobald die Oberfläche (Benutzer diktyo)
# die Anfrage /var/lib/diktyo/update/request.json anlegt. Aus der Anfrage wird nichts übernommen – Quelle (Repository,
# Zweig) steht fest in /opt/diktyo/update.conf (root). Ablauf: Datenbank sichern, Stand von GitHub laden, setup.sh.
# Statusmeldungen schreibt das Skript als Benutzer diktyo (nie als root in das Verzeichnis des Dienstes).
set -uo pipefail
DATA=/var/lib/diktyo
DIR="$DATA/update"
LOG=/var/log/diktyo-update.log
REPO=xpistaki-bit/diktyo
BRANCH=main
[ -f /opt/diktyo/update.conf ] && . /opt/diktyo/update.conf
[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "invalid REPO" >&2; exit 1; }
[[ "$BRANCH" =~ ^[A-Za-z0-9_./-]+$ ]] || { echo "invalid BRANCH" >&2; exit 1; }

rm -f "$DIR/request.json"   # sonst startet die Pfad-Einheit sofort wieder

status() {  # status <state> <message>  (Meldung ohne Anführungszeichen)
  local msg="${2//\"/}"
  printf '{"state":"%s","message":"%s","ts":%s}\n' "$1" "$msg" "$(date +%s)" \
    | runuser -u diktyo -- sh -c "cat > '$DIR/status.tmp' && mv -f '$DIR/status.tmp' '$DIR/status.json'"
}
fail() { status error "$1"; echo "FEHLER: $1" >> "$LOG"; exit 1; }

: > "$LOG"; chmod 644 "$LOG"
exec >> "$LOG" 2>&1
echo "==> $(date -Is) Update angefordert ($REPO, $BRANCH)"

status running "Sichere die Datenbank"
STAMP="$(date +%Y%m%d-%H%M%S)"
runuser -u diktyo -- env DIKTYO_DATA="$DATA" /opt/diktyo/venv/bin/python - "$DATA/diktyo.db" "$DATA/before-update-$STAMP.db" <<'PY' || fail "Datenbank-Sicherung fehlgeschlagen"
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY
# nur die letzten drei Sicherungen behalten – als diktyo, damit Dateinamen im Datenverzeichnis nie root-Rechte bekommen
runuser -u diktyo -- sh -c 'cd /var/lib/diktyo && ls -1t before-update-*.db 2>/dev/null | tail -n +4 | while IFS= read -r f; do rm -f -- "./$f"; done'

status running "Lade den neuen Stand von GitHub"
SRC="$(mktemp -d /root/diktyo-update-XXXXXX)"
trap 'rm -rf "$SRC"' EXIT
URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
echo "==> $URL"
curl -fsSL --retry 3 --max-time 300 "$URL" -o "$SRC/src.tar.gz" || fail "Download von GitHub fehlgeschlagen"
tar -xzf "$SRC/src.tar.gz" -C "$SRC" --strip-components=1 || fail "Archiv unvollständig"
[ -f "$SRC/app/version.py" ] && [ -f "$SRC/install/setup.sh" ] || fail "Archiv unvollständig"
NEW="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$SRC/app/version.py")"
echo "==> neue Version: $NEW"

status running "Installiere Version $NEW"
bash "$SRC/install/setup.sh" || fail "Installation fehlgeschlagen - Protokoll ansehen"
status done "Version $NEW installiert"
echo "==> $(date -Is) fertig"
