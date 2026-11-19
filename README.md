# díktyo – network documentation for home networks

díktyo (Greek δίκτυο, "network") documents a home network: devices with IP, MAC, location and notes, IP address
management with subnets and VLANs, and a graphical topology that shows how everything is connected. It is meant
to be a slim, self-hosted alternative to NetBox for private users. It runs as a single service with an SQLite
file, either in a Proxmox LXC or in a Docker container, and is managed in the browser. The interface is available
in German and English.

> **Status: v0.14 – MVP (M0–M6) complete, phase 2 in progress.** German step-by-step guide:
> [docs/ANLEITUNG.de.md](docs/ANLEITUNG.de.md). Plan, add-ons and improvements: [docs/ROADMAP.de.md](docs/ROADMAP.de.md).

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
| Services | web app `diktyo`, background service (network scan) `diktyo-worker`: `systemctl status diktyo diktyo-worker` |
| Logs | `journalctl -u diktyo -u diktyo-worker` |
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
`DIKTYO_PORT` in `docker-compose.yml`. All data lives in the named volume `diktyo-data`. Web app and background
service (network scan) run in the same container; nmap's operating-system detection is not available in Docker.

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

## Devices and network

Each profile has the tabs **Devices**, **IPAM**, **Locations**, **Output** and **Sharing**.

- **Devices:** name, type, catalog model, manufacturer/model, location, hostname, MAC, one or more IP addresses
  (static, DHCP, reserved), notes and tags. The table can be searched, filtered by type and location, and sorted
  by any column.
- **Ports:** a catalog model creates the ports of a device (for example 24 × RJ45 + 4 × SFP+ for a Zyxel
  XGS1935-28). The port groups can be changed per device: count, kind, speed, label, PoE.
- **Connection:** every device has one uplink: *LAN* (optionally to a specific port of a switch or router, and
  from a specific own port), *Wi-Fi* or *mesh backhaul* to an access point or mesh node, or *virtual* for a VM or
  container running on a host. An occupied port cannot be used twice, and loops are rejected. The device dialog
  shows the port assignment and all devices connected to it.
- **IPAM:** subnets with gateway, DNS, DHCP range and VLAN; usage per subnet; assigned and free addresses (free for
  static use vs. inside the DHCP pool). Notes point out duplicate IPs or MACs, static IPs inside the DHCP range,
  addresses outside every subnet and overlapping subnets.
- **Locations:** a tree such as house › ground floor › office.

## Topology

The tab **Topology** draws the network as a tree from left to right, built from the connections of the devices:
router → switch (with the port names on the lines) → access points, servers and so on. Line styles show the
medium: solid LAN, dashed Wi-Fi, dotted mesh backhaul, fine virtual (VMs and containers on their host). Devices
without a connection are listed separately.

- Wi-Fi clients of an access point or mesh node (from 4) and VMs of a host (from 5) are combined into one box, for
  example "12 Wi-Fi devices · 9 online"; a click expands it.
- Drag to move, mouse wheel or −/+ to zoom, "Fit" to see everything. A click on a device shows its details at the
  side, a double click opens the detail view.
- **Detail view** of a switch or router: the front panel with all ports (odd numbers on top, even at the bottom,
  SFP ports set apart) and the connected devices around it; the uplink is marked. A click on a port shows the
  device behind it with name, IP and MAC, and with SNMP also link speed, traffic, learned MAC addresses and the
  LLDP neighbour. Wi-Fi, mesh and virtual devices are listed at the side and can be collapsed.
- **Quick ping** checks all devices (or those of the detail view) at once; the online status is refreshed every
  30 seconds while the view is open.
- The PDF can contain the topology as a graphic (section "Topology graphic").

- **Move devices** with the mouse; positions are stored per profile (also used for the PDF), "Reset layout" restores
  the automatic arrangement.
- **Full screen** enlarges the topology to the whole window below the header; Esc returns to normal size.
- **Internet:** a globe in front of the WAN router. With the FRITZ!Box (or UniFi) integration it shows whether the
  internet connection is up (animated green line or red) and the current traffic down/up on the line.

## History

The **History** tab shows what changed when and why: devices added or removed, name, type, status, model, location, IP
addresses, MAC and connection (e.g. switch port 3 → 5), each with its source (by hand with the account, network scan,
FRITZ!Box, SNMP, MikroTik, service scan …), plus online/offline, actions, new configuration versions, quarantine and
open ports appearing or disappearing. A "since yesterday" summary, filters, search and CSV export; the device dialog
shows the last 30 days. Roaming between Wi-Fi/mesh access points is not recorded. Kept for a year and included in backups.

## Network scan and identification

The tab **Network scan** finds the devices in the network; new ones land in the **Inbox** with a guess of what
they are, for example "Amazon Echo (Alexa) · 78 %" with the reasons (manufacturer of the MAC address, open ports,
mDNS services, UPnP model, title of the web interface, DNS name). Accept them into the device list (directly or
after editing), or ignore them; ignored devices are recognised in later scans and not reported again. Known devices
are matched by MAC address (otherwise by IP); the scan only fills in empty fields and never overwrites manual
entries. A changed DHCP address is updated, static addresses stay untouched.

| Mode | What happens |
|---|---|
| Passive | reads the ARP table, asks mDNS/Bonjour and UPnP, resolves DNS names; no pings, no port probes |
| Light | adds ping and about 20 common TCP ports per address, reads the title of web interfaces |
| Full (default) | adds about 60 ports, NetBIOS names and service detection with nmap; takes a few minutes for a /24 |

- **Networks:** without a selection, the IPv4 subnets from IPAM are scanned, otherwise the networks of the
  container's own interfaces (one per VLAN, see installation). Networks that are not in IPAM yet are created, so a
  first scan can initialise an empty profile. At most /20 per network.
- **Exclusions:** addresses or networks that are never probed actively, for example sensitive older cameras.
- **Schedule:** manually, hourly, every 6/12 hours, daily or weekly. Every scan updates online/offline and the
  status history of the devices (shown in the device dialog).
- **Identification rules** live in the catalog (tab "Detection rules") as data: conditions on manufacturer,
  hostname, mDNS, UPnP, web interface, open ports and random MAC addresses, each with a weight. Administrators can
  add and edit rules or import/export them as CSV. A catalog model is suggested when the model name appears in the
  UPnP data or the web interface (for example "ExpertWiFi_EBM68" → ASUS ExpertWiFi EBM68 with its ports).
- **Manufacturer list:** the IEEE OUI lists are downloaded at runtime (not shipped in the repository) and renewed
  every 30 days; Settings → Detection shows the state.
- **Fingerbank** (optional, external): with a free API key (Settings → Detection) and switched on per profile,
  MAC address and hostname of unknown devices are sent to fingerbank.org for a better guess.
- **Networks behind a router:** a scan sees MAC addresses, mDNS and UPnP only in the networks the container is
  directly connected to. Other networks (for example the FRITZ!Box network when díktyo runs behind an ASUS router in
  router mode) are reached by ping/TCP, without MAC addresses; the FRITZ!Box integration fills this gap.
- **Privileges:** discovery needs no root rights (ping and TCP connections fill the kernel's ARP table). Only the
  operating-system detection of nmap needs `CAP_NET_RAW`; in the LXC the background service gets it, in Docker it
  stays off.

## Integrations and monitoring

The tab **Integrations** connects devices that díktyo queries directly (read-only), every 30 s to 15 min:

- **FRITZ!Box (TR-064).** Without a password díktyo reads the host list (MAC, IP, name, LAN/Wi-Fi, active) and the
  WAN traffic. This also covers devices in networks behind another router, which a scan only sees without MAC
  addresses. With a FRITZ!Box user the mesh topology is added (which device is on which LAN port or Wi-Fi, which
  sets the connections automatically) plus Wi-Fi networks. Create the user under System → FRITZ!Box Users with the
  permission "FRITZ!Box settings"; "Allow access for applications" must be on (Home Network → Network → Network
  Settings). New devices land in the inbox; known ones are updated and shown online/offline.
- **Switch (SNMP v2c or v3** with SHA/SHA-256/MD5 authentication and AES-128 encryption), for example the Zyxel XGS1935: port status and speed, traffic per port (from the 64-bit
  counters), MAC addresses learned per port and LLDP neighbours. Devices whose MAC address appears alone on a port
  are connected to that port automatically; on a port with many addresses the switch, access point or router behind
  it is chosen. Enable SNMP on the switch (Zyxel: Management → Access Control → SNMP) and set a community.
- **ASUS router with AiMesh** (for example ExpertWiFi EBM68): clients with name, IP, MAC, Wi-Fi band and the mesh
  node they are connected to, plus the mesh nodes with their backhaul (mesh or LAN). Sign in with the router's admin
  account (web interface, usually HTTPS port 8443). ASUS allows only one admin session at a time; díktyo keeps its
  session open, and the default interval is 5 minutes.
- **Proxmox VE** (API token, read-only): nodes, VMs and containers with status, MAC, bridge, VLAN tag and IP
  addresses (via the QEMU guest agent for VMs and the interface list for containers); they are attached to their host
  as "virtual". The token setup is shown in the dialog and in [docs/architecture.md](docs/architecture.md).
- **Home Assistant:** names and areas of HA devices are taken over by MAC address; via MQTT díktyo reports online
  sensors, counters, WAN traffic and events (device offline/online, new device). A blueprint for phone notifications
  is in [docs/home-assistant](docs/home-assistant/README.md).
- **TP-Link Omada** (Open API of the software controller, OC200/OC300 or gateway with controller; app in "Client"
  mode with Client ID, Client Secret and Omada ID): gateways, switches and access points with their uplink device and
  port, and the clients with the access point or switch port they are connected to.
- **Ubiquiti UniFi** (local Network Integration API with an API key, UniFi Network 9.0 or newer; consoles and
  self-hosted controllers): gateway, switches and access points with port status (shown on the front panel), the
  connected clients with their access point or switch, and the gateway's WAN traffic.
- **MikroTik RouterOS 7** (REST API, user with read + rest-api; write/reboot/test for actions): ports with link,
  speed, traffic and PoE, clients from DHCP/ARP with the port or Wi-Fi they use (bridge hosts, registration table),
  MNDP/LLDP neighbours and WAN traffic; configuration backup via SSH `/export`; actions port off/on, PoE restart,
  Wi-Fi on/off, Wake-on-LAN, restart.
- Omada, UniFi and MikroTik were built from the vendors' API documentation and tested against simulated controllers, not yet
  against real hardware – feedback welcome.
- Connections set by an integration never replace connections entered by hand.
- **Online monitoring:** all confirmed devices with an IP address are pinged every 30 s, 1 min or 5 min (per
  profile); devices that drop pings are checked through a known open port. The device dialog shows the last
  changes.
- **Measurements** (WAN traffic, port traffic) are kept 2 days by default, up to 14 (Settings → Detection), and
  shown as charts over 2 h, 24 h, 2 days or 7 days.

- **Service scan (nmap) on demand** in the device dialog: open TCP ports with service, product and version, web page
  titles and TLS certificates with expiry date (quick 100 / standard 1000 / all ports).
- **SNMP diagnosis** in the switch dialog: network path (including the NAT address the switch sees when díktyo is in
  another network), reachability, whether the SNMP service answers at all, and the sign-in.
- **FRITZ!Box second factor:** if FRITZ!OS asks for a confirmation for the configuration export, díktyo shows how to
  confirm (button on the box, phone code, or the code from an authenticator app via the web interface) and continues;
  scheduled backups show a note instead.

Integrations and monitoring run in the background service next to the scans. Credentials are stored encrypted and
go into backups only with the backup passphrase.

## Actions

Profile owners can switch things through the integrations (device dialog, topology side panel, front panel port):
Wi-Fi on/off and restart (FRITZ!Box), block/allow internet access and Wake-on-LAN for devices in the FRITZ!Box
network, switch port off/on and PoE restart (SNMP with write access), start/shut down/restart VMs and containers
(Proxmox token with `VM.PowerMgmt`). Every action shows a preview and asks for confirmation; Wi-Fi, internet block and
switch ports can switch back automatically (15 min, 1 h, 2 h, tomorrow 6:00). The configuration is backed up first if
the last backup is older than an hour. **Schedules** run actions on weekdays and times (with a time window for
reversible actions, e.g. internet blocked Mon–Fri 22:00–06:30, switching only at the transitions). **Quarantine** blocks
internet access (FRITZ!Box) for every new device until it is accepted in the inbox. díktyo refuses to disable the switch port it or the router uses to reach the
switch, does not block infrastructure from the internet and does not shut down its own VM. All actions are logged.

## Device configuration backups

Integrations that can read a device's configuration back it up weekly or daily (setting in the integration) or on
demand ("Back up configuration"): the FRITZ!Box export (needs the FRITZ!Box user), the settings file of ASUS routers,
and the running configuration of switches via SSH (`show running-config`, SSH user and password in the switch
integration). Unchanged configurations are not stored twice; the last 30 versions per device are kept, encrypted on
disk. The device dialog lists them for download and shows the changes between two text configurations. With a backup
passphrase, the newest configuration of each device is included in díktyo backups (encrypted with the passphrase).

## Catalog

The starter catalog contains about 80 devices from AVM (FRITZ!Box, Repeater, Powerline), Zyxel, ASUS (ExpertWiFi,
ZenWiFi, RT), TP-Link Omada, Netgear, devolo, Ubiquiti UniFi, Synology and generic switches/routers. Port counts
follow the manufacturers' product descriptions but are **not individually verified** against data sheets; an
administrator can mark an entry as verified. The starter catalog is generated by `tools/seed.py`.

Administrators can add their own entries, edit existing ones (they then count as custom and are no longer changed
by updates) and import a CSV (separator `;` or `,`, German or English column names). Ports are written as
`count:kind:speed:label:poe`, groups separated by commas, for example `24:rj45:1G, 4:sfp+:10G` or
`1:rj45:2.5G:WAN, 3:rj45:1G:LAN`. "CSV template" downloads an example.

### Catalog entry from system info

"From system info" takes pasted output of `dmidecode -t system`, `lspci`, `hostnamectl` or PowerShell
(`Get-CimInstance Win32_ComputerSystem`), detects manufacturer, model, type and network ports (speed from the NIC
model), optionally looks up a short description on Wikipedia (only manufacturer and model are sent) and opens the
prefilled catalog dialog for review. Serial number and UUID are never stored in the catalog or sent anywhere.

**AI research (optional):** with a Claude API key (Settings → AI research) díktyo researches data sheets via the
Claude API with web search and fills in type, ports, Wi-Fi and key data ("Complete with AI" in the catalog dialog, or
directly from system info). The suggestion shows its sources, a confidence rating and the approximate cost; only
manufacturer, model and detected key data are sent. Default model Claude Opus 5.5, selectable.

## Output

**Output** creates a PDF in a light print layout. Choose the sections: topology graphic, device list, IP plan per subnet, VLAN
overview, port assignment per switch, Wi-Fi overview (clients per access point/mesh node) and notes. The device
list and the IP addresses are also available as CSV.

## Backup

Targets are configured under **Settings → Backup**, as in PanelAtlas. Each backup is a ZIP file with all accounts,
profiles, devices, catalog entries and settings (`export.json`), plus a PDF and two CSV files per profile.

- **Folder / NAS:** a path in the container, for example a directory mounted from Proxmox
  (`pct set <CTID> -mp0 /mnt/pve/nas/diktyo,mp=/mnt/sicherung`) or the `/backup` volume in Docker. The user
  `diktyo` needs write access.
- **WebDAV:** for example Nextcloud: `https://cloud.example.com/remote.php/dav/files/NAME/diktyo`, user and app
  password.
- **rclone** (Google Drive, OneDrive, Dropbox, S3 and others): run `runuser -u diktyo -- rclone config` once in the
  LXC and enter the remote in the app, for example `gdrive:diktyo`.
- **Automatic:** every 12 hours, daily or weekly, only when something has changed.
- **Backup passphrase:** stored credentials (SMTP password, WebDAV passwords, later device credentials) are put
  into the backup encrypted with this passphrase. Without a passphrase they are left out. Password hashes of the
  accounts are always included, so treat backup files as confidential.

**Restore:** on a new, empty installation the first-run screen offers "Restore from a backup": upload the ZIP and
enter the passphrase; accounts, profiles and settings are taken over and you sign in with your existing account.
**Import profiles from backup** (Settings → Backup) adds the profiles of a backup to a running installation; you
become the owner, and members whose e-mail address exists keep their role.

## Security

- Passwords are stored as scrypt hashes. Stored secrets (SMTP, backup targets, later device credentials) are
  encrypted with a key in `/var/lib/diktyo/secret.key`. The key is never included in backups.
- The app speaks plain HTTP and is meant for the local network. Put a reverse proxy with TLS in front if needed.

## Technology

Python 3.11+, FastAPI, SQLite with versioned migrations, PDF via CairoSVG and pypdf. No build step: the interface is plain HTML and
JavaScript. Translations live in `app/static/i18n.js` (interface) and in `ERR_EN` in `app/main.py` (server
messages). The version number lives in `app/version.py`. Tests: `pip install pytest && pytest`.

## License

MIT, see [LICENSE](LICENSE).
