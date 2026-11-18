#!/usr/bin/env bash
# Creates a Debian LXC on a Proxmox VE host and installs díktyo in it.
# Run as root on the Proxmox host, either straight from GitHub:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/install-proxmox.sh)"
# or from the unpacked repository:
#   bash install/install-proxmox.sh
# Adjustable through environment variables, for example:
#   CTID=130 IP=192.168.178.50/24 GW=192.168.178.1 VLANS="10:192.168.10.5/24,20:dhcp" bash install/install-proxmox.sh
set -euo pipefail
command -v pct >/dev/null || { echo "This script must run on the Proxmox host (pct not found)."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Please run as root."; exit 1; }

REPO="${REPO:-xpistaki-bit/diktyo}"
BRANCH="${BRANCH:-main}"
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
CTID="${CTID:-$(pvesh get /cluster/nextid)}"
NAME="${NAME:-diktyo}"
STORAGE="${STORAGE:-}"
TPL_STORAGE="${TPL_STORAGE:-}"
BRIDGE="${BRIDGE:-vmbr0}"
DISK="${DISK:-8}"
RAM="${RAM:-1024}"
CORES="${CORES:-2}"
IP="${IP:-dhcp}"
GW="${GW:-}"
VLANS="${VLANS:-}"
PORT="${DIKTYO_PORT:-8090}"

if pct status "$CTID" >/dev/null 2>&1; then echo "Container $CTID already exists. Please pass CTID=..."; exit 1; fi

# Pick the storage automatically: prefer local-lvm / local-zfs, otherwise the first active suitable one
pick_storage() {  # $1 = content type (rootdir | vztmpl)
  local list; list="$(pvesm status -content "$1" 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')"
  for s in local-lvm local-zfs local; do echo "$list" | grep -qx "$s" && { echo "$s"; return; }; done
  echo "$list" | head -1
}
[ -n "$STORAGE" ] || STORAGE="$(pick_storage rootdir)"
[ -n "$TPL_STORAGE" ] || TPL_STORAGE="$(pick_storage vztmpl)"
[ -n "$STORAGE" ] || { echo "No storage for containers found (pvesm status -content rootdir)."; exit 1; }
[ -n "$TPL_STORAGE" ] || { echo "No storage for templates found (pvesm status -content vztmpl)."; exit 1; }
if ! pvesm status -content rootdir | awk 'NR>1 {print $1}' | grep -qx "$STORAGE"; then
  echo "Storage '$STORAGE' cannot hold containers. Available:"; pvesm status -content rootdir; exit 1
fi
echo "==> Storage: container on '$STORAGE', template on '$TPL_STORAGE'"

# VLAN interfaces: VLANS="10:192.168.10.5/24,20:dhcp" -> eth1 tag 10 static, eth2 tag 20 DHCP.
# They get no gateway, so traffic to other networks keeps using eth0 (no asymmetric routing).
check_vlans() {
  [ -n "$VLANS" ] || return 0
  local spec tag
  IFS=',' read -ra specs <<< "$VLANS"
  for spec in "${specs[@]}"; do
    tag="${spec%%:*}"
    [[ "$tag" =~ ^[0-9]+$ ]] && [ "$tag" -ge 1 ] && [ "$tag" -le 4094 ] || { echo "Invalid VLAN entry '$spec' (expected TAG:IP/CIDR or TAG:dhcp)."; exit 1; }
  done
  if ! awk -v b="$BRIDGE" '$1=="iface"{on=($2==b)} on && $1=="bridge-vlan-aware" && $2=="yes"{f=1} END{exit !f}' /etc/network/interfaces 2>/dev/null; then
    echo "WARNING: bridge '$BRIDGE' does not look VLAN-aware on this node (bridge-vlan-aware yes)."
    echo "         Tagged interfaces will not reach their VLAN until it is enabled on every node the container may run on."
  fi
}
add_vlan_nics() {  # $1 = CTID
  [ -n "$VLANS" ] || return 0
  local spec tag ip n cfg
  IFS=',' read -ra specs <<< "$VLANS"
  for spec in "${specs[@]}"; do
    tag="${spec%%:*}"; ip="${spec#*:}"; [ "$ip" = "$spec" ] && ip=dhcp
    cfg="$(pct config "$1")"
    if echo "$cfg" | grep -E '^net[0-9]+:' | grep -Eq "tag=${tag}(,|$)"; then echo "    VLAN $tag: interface exists, skipped"; continue; fi
    for n in $(seq 1 31); do echo "$cfg" | grep -q "^net${n}:" || break; done
    echo "    VLAN $tag: net${n} (eth${n}), ip=${ip}"
    pct set "$1" "--net${n}" "name=eth${n},bridge=${BRIDGE},tag=${tag},ip=${ip}"
  done
}
check_vlans

# The template list contains several architectures (amd64, arm64); only the host's one can run.
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
echo "==> Looking for a Debian template (13, otherwise 12) for $ARCH"
pveam update >/dev/null
TPL=""
for v in 13 12; do
  TPL="$(pveam available --section system | awk -v v="^debian-${v}-standard_" -v a="_${ARCH}\\\\.tar" '$2 ~ v && $2 ~ a {print $2}' | sort -V | tail -1)"
  [ -n "$TPL" ] && break
done
[ -n "$TPL" ] || { echo "No Debian 13/12 template for $ARCH found."; exit 1; }
pveam list "$TPL_STORAGE" | grep -q "$TPL" || pveam download "$TPL_STORAGE" "$TPL"

NET="name=eth0,bridge=${BRIDGE},ip=${IP}"
[ -n "$GW" ] && NET="${NET},gw=${GW}"

echo "==> Creating container $CTID ($NAME)"
pct create "$CTID" "${TPL_STORAGE}:vztmpl/${TPL}" --hostname "$NAME" --cores "$CORES" --memory "$RAM" --swap 512 \
  --rootfs "${STORAGE}:${DISK}" --net0 "$NET" --unprivileged 1 --features nesting=1 --onboot 1 \
  --description "díktyo network documentation, port ${PORT}"
add_vlan_nics "$CTID"
if ! pct start "$CTID"; then
  echo "Container $CTID was created but does not start. Details: pct start $CTID --debug"
  echo "Remove it with: pct destroy $CTID"
  exit 1
fi

echo "==> Waiting for the network"
for i in $(seq 1 40); do
  pct exec "$CTID" -- sh -c 'getent hosts deb.debian.org >/dev/null 2>&1' && break
  sleep 2
  [ "$i" = 40 ] && { echo "The container has no network (check DNS/DHCP)."; exit 1; }
done

echo "==> Transferring and installing the app"
TMP="$(mktemp /tmp/diktyo-XXXXXX.tar.gz)"
tar -C "$SRC" --exclude=data --exclude=__pycache__ --exclude=.git --exclude=tests -czf "$TMP" .
pct exec "$CTID" -- sh -c 'rm -rf /root/diktyo-paket && mkdir -p /root/diktyo-paket'
pct push "$CTID" "$TMP" /root/diktyo-paket.tar.gz
rm -f "$TMP"
pct exec "$CTID" -- tar -C /root/diktyo-paket -xzf /root/diktyo-paket.tar.gz
pct exec "$CTID" -- env DIKTYO_PORT="$PORT" DIKTYO_IPV6="${DIKTYO_IPV6:-0}" bash /root/diktyo-paket/install/setup.sh

echo
echo "Container $CTID is running. To update later, run on the Proxmox host:"
echo "  CTID=$CTID bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/${REPO}/${BRANCH}/install/update-proxmox.sh)\""
echo "Add VLAN interfaces later with VLANS=\"TAG:IP/CIDR,...\" on the update command."
echo "Shell in the container without a password:  pct enter $CTID"
