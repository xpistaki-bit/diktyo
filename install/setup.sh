#!/usr/bin/env bash
# Installs or updates díktyo on Debian/Ubuntu (for example inside a Proxmox LXC).
# Run as root from the unpacked repository:  bash install/setup.sh
# Data lives in /var/lib/diktyo and is kept on updates.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" = 0 ] || { echo "Please run as root."; exit 1; }
# Keep the port of an existing installation unless DIKTYO_PORT is given explicitly.
OLD_PORT="$(sed -n 's/.*--port \([0-9]*\).*/\1/p' /etc/systemd/system/diktyo.service 2>/dev/null || true)"
PORT="${DIKTYO_PORT:-${OLD_PORT:-8090}}"

export DEBIAN_FRONTEND=noninteractive
# apt: retries and timeouts, so a hanging mirror does not block for minutes.
# IPv4 is forced (broken IPv6 is the most common cause of hanging downloads); disable with DIKTYO_IPV6=1.
APT_OPTS=(-o Acquire::Retries=3 -o Acquire::http::Timeout=25 -o Acquire::https::Timeout=25 -o Dpkg::Use-Pty=0)
[ "${DIKTYO_IPV6:-0}" = 1 ] || APT_OPTS+=(-o Acquire::ForceIPv4=true)
echo "==> [1/4] Updating package lists"
apt-get "${APT_OPTS[@]}" update
echo "==> [2/4] Installing system packages"
apt-get "${APT_OPTS[@]}" install -y --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates curl rclone libcairo2 fonts-dejavu-core iputils-ping iproute2 nmap
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11 or newer is required."; exit 1; }

id diktyo >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/diktyo --shell /usr/sbin/nologin diktyo
mkdir -p /opt/diktyo /var/lib/diktyo
rm -rf /opt/diktyo/app
cp -r "$SRC/app" "$SRC/requirements.txt" /opt/diktyo/
find /opt/diktyo/app -name __pycache__ -type d -prune -exec rm -rf {} +
echo "==> [3/4] Installing Python packages"
[ -d /opt/diktyo/venv ] || python3 -m venv /opt/diktyo/venv
/opt/diktyo/venv/bin/pip install --disable-pip-version-check --progress-bar off --timeout 30 --retries 3 -r /opt/diktyo/requirements.txt
chown -R diktyo:diktyo /var/lib/diktyo
chmod 750 /var/lib/diktyo

# Command line tool, e.g. "diktyo reset-password me@example.com"
cat > /usr/local/bin/diktyo <<'CLI'
#!/bin/sh
cd /opt/diktyo && exec runuser -u diktyo -- env DIKTYO_DATA=/var/lib/diktyo /opt/diktyo/venv/bin/python -m app.cli "$@"
CLI
chmod 755 /usr/local/bin/diktyo

echo "==> [4/4] Setting up and starting the service"
cat > /etc/systemd/system/diktyo.service <<UNIT
[Unit]
Description=díktyo network documentation
After=network-online.target
Wants=network-online.target

[Service]
User=diktyo
Group=diktyo
WorkingDirectory=/opt/diktyo
Environment=DIKTYO_DATA=/var/lib/diktyo
ExecStart=/opt/diktyo/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
# Hintergrunddienst (Netzscan). Nur er bekommt CAP_NET_RAW/CAP_NET_ADMIN, damit nmap das Betriebssystem erkennen kann.
cat > /etc/systemd/system/diktyo-worker.service <<UNIT
[Unit]
Description=díktyo background service (network scan)
After=network-online.target diktyo.service
Wants=network-online.target

[Service]
User=diktyo
Group=diktyo
WorkingDirectory=/opt/diktyo
Environment=DIKTYO_DATA=/var/lib/diktyo
ExecStart=/opt/diktyo/venv/bin/python -m app.worker
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
NoNewPrivileges=true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q diktyo diktyo-worker
systemctl restart diktyo diktyo-worker
for i in $(seq 1 15); do
  curl -fs "http://127.0.0.1:${PORT}/api/state" >/dev/null 2>&1 && break
  sleep 1
  [ "$i" = 15 ] && { journalctl -u diktyo -n 30 --no-pager; echo "The service does not start."; exit 1; }
done
# If the container does not allow the capabilities, run the background service without them (no OS detection).
sleep 2
if ! systemctl is-active -q diktyo-worker; then
  echo "    Background service does not start with CAP_NET_RAW/CAP_NET_ADMIN, starting it without (no OS detection)."
  sed -i '/^AmbientCapabilities=/d;/^CapabilityBoundingSet=/d' /etc/systemd/system/diktyo-worker.service
  systemctl daemon-reload
  systemctl restart diktyo-worker
  sleep 2
  systemctl is-active -q diktyo-worker || { journalctl -u diktyo-worker -n 30 --no-pager; echo "The background service does not start."; exit 1; }
fi
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Done. Web interface: http://${IP:-<container-ip>}:${PORT}"
echo "The first account you create there becomes administrator."
echo "Data: /var/lib/diktyo   Services: systemctl status diktyo diktyo-worker   Logs: journalctl -u diktyo -u diktyo-worker   CLI: diktyo --help"
