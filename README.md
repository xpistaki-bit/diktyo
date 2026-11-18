# díktyo – network documentation for home networks

díktyo (Greek δίκτυο, "network") documents a home network: devices with IP, MAC, location and notes, IP address
management with subnets and VLANs, and a graphical topology that shows how everything is connected. It is meant
to be a slim, self-hosted alternative to NetBox for private users. It runs as a single service with an SQLite
file, either in a Proxmox LXC or in a Docker container, and is managed in the browser. The interface is available
in German and English.

> **Status: early development (v0.1, milestone M0).** Accounts, profiles and sharing work. Devices, IPAM, network
> scan, topology and integrations follow – see [docs/architecture.md](docs/architecture.md) for the plan.

## Installation

Both ways serve the web interface on port **8090**. The first account created in the browser becomes
administrator.

### Option 1: Proxmox LXC (recommended)

Run this on the Proxmox host as root:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/install-proxmox.sh)"
```

The script creates an unprivileged Debian container (13, otherwise 12), installs the app and prints the address.

Defaults: next free container ID, storage picked automatically (`local-lvm` or `local-zfs` if present), bridge
`vmbr0`, DHCP, 8 GB disk, 1024 MB RAM, 2 cores. Override them with variables:

```bash
CTID=130 IP=192.168.178.50/24 GW=192.168.178.1 VLANS="10:192.168.10.5/24,20:dhcp" \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/install-proxmox.sh)"
```

| Variable | Meaning | Default |
|---|---|---|
| `CTID` | container ID | next free ID |
| `NAME` | hostname | `diktyo` |
| `STORAGE` | storage for the container disk | automatic |
| `TPL_STORAGE` | storage for the Debian template | automatic |
| `BRIDGE` | network bridge | `vmbr0` |
| `IP`, `GW` | static address (CIDR) and gateway of `eth0` | DHCP |
| `VLANS` | extra interfaces, one per VLAN: `TAG:IP/CIDR` or `TAG:dhcp`, comma-separated | none |
| `DISK`, `RAM`, `CORES` | disk in GB, memory in MB, CPU cores | 8, 1024, 2 |
| `DIKTYO_PORT` | port of the web interface | 8090 |
| `DIKTYO_IPV6=1` | let apt use IPv6 (IPv4 is forced by default) | off |

**One interface per VLAN.** díktyo scans each network from inside it, so it sees MAC addresses and broadcast
services there. Every entry in `VLANS` adds `ethN` with that VLAN tag on the same bridge and **no gateway**, so
traffic to other networks keeps leaving through `eth0`. Requirements: the bridge is VLAN-aware
(`bridge-vlan-aware yes`) on **every** cluster node the container may run on, and the switch ports of the Proxmox
nodes carry the VLANs as tagged (trunk).

**Update** (data is kept; `VLANS=...` adds missing VLAN interfaces):

```bash
CTID=130 bash -c "$(curl -fsSL https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/install/update-proxmox.sh)"
```

On any other Debian or Ubuntu machine (VM, bare metal), run `bash install/setup.sh` as root.

| What | Where |
|---|---|
| Program | `/opt/diktyo` |
| Data (database, key) | `/var/lib/diktyo` |
| Service | `systemctl status diktyo`, logs: `journalctl -u diktyo` |
| Command line | `diktyo --help` (inside the container) |
| Shell in the container | on the host: `pct enter <CTID>` |

### Option 2: Docker

Requirements: Docker Engine with the Compose plugin, on a Linux host in the network to be documented.

```bash
git clone https://github.com/xpistaki-bit/diktyo.git
cd diktyo
docker compose up -d --build
```

The container uses the **host network** so that the network scan sees the LAN directly; the port is set with
`DIKTYO_PORT` in `docker-compose.yml`. All data lives in the named volume `diktyo-data`.

| Task | Command |
|---|---|
| Update | `git pull && docker compose up -d --build` |
| Logs | `docker compose logs -f` |
| Command line | `docker compose exec diktyo python -m app.cli --help` |

Do not install Docker directly on a Proxmox host; use the LXC instead, or a VM.

## Accounts and profiles

- **Sign-in** with e-mail address and password. The first account becomes administrator; further accounts are
  created by an administrator (Settings → Accounts), or by the people themselves if self-registration is allowed.
- **Profiles** are networks or sites, for example home, parents or holiday house. The owner can share a profile
  with other accounts as *View*, *Edit* or *Owner*. Administrators can open every profile.
- **Forgot password:** with SMTP configured (Settings → Sending e-mail) a reset link is sent. Without it, an
  administrator generates a new password in the account list, or on the server:

  ```bash
  diktyo reset-password me@example.com                                    # LXC
  docker compose exec diktyo python -m app.cli reset-password me@example.com   # Docker
  ```

## Security

- Passwords are stored as scrypt hashes. Stored secrets (SMTP now, device credentials later) are encrypted with a
  key in `/var/lib/diktyo/secret.key`. The key is never included in backups.
- The app speaks plain HTTP and is meant for the local network. Put a reverse proxy with TLS in front if needed.

## Technology

Python 3.11+, FastAPI, SQLite with versioned migrations. No build step: the interface is plain HTML and
JavaScript. Translations live in `app/static/i18n.js` (interface) and in `ERR_EN` in `app/main.py` (server
messages). The version number lives in `app/version.py`. Tests: `pip install pytest && pytest`.

## License

MIT, see [LICENSE](LICENSE).
