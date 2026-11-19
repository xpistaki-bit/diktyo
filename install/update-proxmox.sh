#!/usr/bin/env bash
# Updates díktyo in an existing container. Data in /var/lib/diktyo is kept.
# On the Proxmox host as root, straight from GitHub:
#   CTID=130 bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/update-proxmox.sh)"
# or from the unpacked repository:
#   CTID=130 bash install/update-proxmox.sh
# VLANS="10:192.168.10.5/24,20:dhcp" adds missing VLAN interfaces (existing tags are left alone).
set -euo pipefail
: "${CTID:?Please pass CTID=<container id>}"
command -v pct >/dev/null || { echo "This script must run on the Proxmox host (pct not found)."; exit 1; }
REPO="${REPO:-xpistaki-bit/diktyo}"
BRANCH="${BRANCH:-main}"
BRIDGE="${BRIDGE:-vmbr0}"
VLANS="${VLANS:-}"
# Source: the unpacked repository next to this script, or a download from GitHub when run via curl.
SELF="${BASH_SOURCE[0]:-}"
if [ -n "$SELF" ] && [ -f "$SELF" ] && [ -d "$(dirname "$SELF")/../app" ]; then
  SRC="$(cd "$(dirname "$SELF")/.." && pwd)"
else
  SRC="$(mktemp -d /tmp/diktyo-src-XXXXXX)"
  URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
  echo "==> Downloading $URL"
  if command -v curl >/dev/null; then curl -fsSL "$URL" -o "$SRC/src.tar.gz"; else wget -qO "$SRC/src.tar.gz" "$URL"; fi
  tar -xzf "$SRC/src.tar.gz" -C "$SRC" --strip-components=1 && rm -f "$SRC/src.tar.gz"
  [ -d "$SRC/app" ] || { echo "Download incomplete: $URL"; exit 1; }
fi

if [ -n "$VLANS" ]; then
  echo "==> VLAN interfaces"
  IFS=',' read -ra specs <<< "$VLANS"
  for spec in "${specs[@]}"; do
    tag="${spec%%:*}"; ip="${spec#*:}"; [ "$ip" = "$spec" ] && ip=dhcp
    [[ "$tag" =~ ^[0-9]+$ ]] && [ "$tag" -ge 1 ] && [ "$tag" -le 4094 ] || { echo "Invalid VLAN entry '$spec' (expected TAG:IP/CIDR or TAG:dhcp)."; exit 1; }
    cfg="$(pct config "$CTID")"
    if echo "$cfg" | grep -E '^net[0-9]+:' | grep -Eq "tag=${tag}(,|$)"; then echo "    VLAN $tag: interface exists, skipped"; continue; fi
    for n in $(seq 1 31); do echo "$cfg" | grep -q "^net${n}:" || break; done
    echo "    VLAN $tag: net${n} (eth${n}), ip=${ip}"
    pct set "$CTID" "--net${n}" "name=eth${n},bridge=${BRIDGE},tag=${tag},ip=${ip}"
  done
fi

# Zeitzone des Hosts übernehmen (Container laufen sonst in UTC und zeigen eine falsche Uhrzeit)
pct set "$CTID" --timezone host >/dev/null 2>&1 || true
HOST_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)"
pct exec "$CTID" -- sh -c "[ -f /usr/share/zoneinfo/$HOST_TZ ] && ln -sf /usr/share/zoneinfo/$HOST_TZ /etc/localtime && echo $HOST_TZ > /etc/timezone" || true

TMP="$(mktemp /tmp/diktyo-XXXXXX.tar.gz)"
tar -C "$SRC" --exclude=data --exclude=__pycache__ --exclude=.git --exclude=tests -czf "$TMP" .
pct exec "$CTID" -- sh -c 'rm -rf /root/diktyo-paket && mkdir -p /root/diktyo-paket'
pct push "$CTID" "$TMP" /root/diktyo-paket.tar.gz
rm -f "$TMP"
pct exec "$CTID" -- tar -C /root/diktyo-paket -xzf /root/diktyo-paket.tar.gz
pct exec "$CTID" -- env ${DIKTYO_PORT:+DIKTYO_PORT="$DIKTYO_PORT"} DIKTYO_IPV6="${DIKTYO_IPV6:-0}" bash /root/diktyo-paket/install/setup.sh
