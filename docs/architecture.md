# Architecture and roadmap

This document records the design decisions for díktyo. The project follows the structure of PanelAtlas
(`app/`, `install/`, `tools/`, `docs/`): one Python service, one SQLite file, no front-end build step.

## Processes

| Process | Runs as | Task |
|---|---|---|
| `diktyo` (web) | user `diktyo`, no special rights | API and web interface (FastAPI/Uvicorn) |
| `diktyo-worker` (from M2) | raw-socket capability only | schedule, network scan, drivers, metrics |

Both share the SQLite database (WAL mode) and a job table. Live status reaches the browser through Server-Sent
Events.

## Data model

| Area | Tables |
|---|---|
| Accounts | `users`, `sessions`, `password_resets` |
| Profiles | `profiles` (network/site), `profile_members` (owner/edit/view), `locations` (house → floor → room) |
| Catalog | `device_models` (manufacturer, model, type, ports, graphic template, detection fingerprints, driver, verified, custom) |
| Inventory | `devices` (confirmed/discovered/ignored), `interfaces` (port no., kind, MAC, speed, PoE), `links` (medium LAN/WLAN/mesh backhaul/virtual, source manual/LLDP/FDB/API) |
| IPAM | `vlans`, `subnets`, `ip_addresses`, `port_vlans` |
| Discovery | `scans`, `observations` (raw facts per source), `identifications` (guess, confidence, reasons) |
| Integrations | `integrations` (driver, host, encrypted credentials, options, interval), `config_backups` |
| Monitoring | `status_events` (state changes only), `series`, `metrics` (retention 2 days by default, up to 14) |
| Other | `settings`, `audit_log`, `media` |

Rule: scans and APIs only write `observations`. A merge step matches them to `devices` by MAC address.
**Manual entries always win** and are never overwritten by a scan. Between sources: API before SNMP before scan.

Migrations are plain SQL in `app/db.py`, applied in order and tracked with `PRAGMA user_version`.

## Drivers

One file per driver in `app/drivers/`. Each driver declares its capabilities (hosts, topology, interfaces,
traffic, live status, config read, config backup, write actions), a credential schema (the UI builds the form
from it), a connection test and a poll function that returns normalised observations and metrics. Write actions
(from phase 2) are named actions with parameters, a preview, a confirmation and an automatic config backup
before they run.

Planned for the MVP: `scanner` (ARP, ICMP, mDNS, SSDP, NetBIOS, reverse DNS, nmap), `fritzbox_tr064`, `snmp`
(profile for Zyxel XGS1935), `asuswrt` (EBM68/AiMesh), `proxmox`, `homeassistant`, plus `oui` and `fingerbank`
as identification helpers. Detection rules live as data in the catalog and are extensible by CSV.

## Secrets and backups

- Secrets are encrypted with Fernet; the key is `secret.key` in the data directory and is never backed up.
- Backups follow PanelAtlas (`backup.py`): a ZIP with `export.json`, media and documents (PDF/CSV per profile),
  sent to a folder/NAS, WebDAV or rclone, optionally daily when something changed. Credentials go into the
  backup re-encrypted with a backup passphrase, so a restore on a new machine works.

## Licensing of data

The IEEE OUI list and other third-party fingerprint data are downloaded at runtime and cached locally, not
shipped in the repository. `nmap` is installed from the distribution packages.

## Milestones

| # | Content | Status |
|---|---|---|
| M0 | repository, installers (incl. VLAN interfaces), Docker, accounts, profiles and sharing, DE/EN, HUD theme | done |
| M1 | inventory, IPAM, catalog seed + CSV, table view, PDF with selectable content, backup + restore | done |
| M2 | worker, scanner, identification with reasons, inbox, scheduled scans, OUI and Fingerbank | done |
| M3 | FRITZ!Box TR-064, SNMP/Zyxel, metrics, status history, configurable interval | done |
| M4 | topology: overall tree + detail view with switch front panel, clickable ports, collapsible WLAN, quick ping, live status | done |
| M5 | ASUS AiMesh, Proxmox, Home Assistant (MQTT discovery, blueprint, areas) | done |
| M6 | config backups for FRITZ!Box, Zyxel and ASUS; polish, documentation | done |

Phase 2:

| # | Content | Status |
|---|---|---|
| P2.1 | topology full screen, internet node with WAN status and live traffic | done (0.7.1) |
| P2.2 | integrations TP-Link Omada (Open API) and Ubiquiti UniFi (Network Integration API) | done (0.8.0), not yet tested on real hardware |
| P2.3 | write actions (named actions with preview, confirmation and automatic config backup first) | done (0.11.0): FRITZ!Box, SNMP switch, Proxmox |
| P2.4 | more integrations: Netgear, devolo, Docker API | open |
| P2.5 | nmap service detection on demand | done (0.9.0) |
| P2.6 | topology: move nodes, positions stored per profile | done (0.9.0) |
| P2.7 | FRITZ!Box second factor (TR-064 X_AVM-DE_Auth) for the config export; SNMP diagnosis | done (0.9.0) |
| P2.8 | passive DHCP fingerprinting | open |
| P2.9 | FRITZ!Box authenticator code (web interface), free node placement, catalog entry from system info | done (0.9.1) |
| P2.10 | AI research for the catalog (Claude API with web search, optional, own key) | done (0.10.0) |
| P2.11 | MikroTik RouterOS 7 integration (REST API, SSH export, actions) | done (0.12.0), not yet tested on real hardware |
| P2.12 | schedules for actions, quarantine for new devices | done (0.13.0) |
| P3.1 | change history (device snapshots with source, timeline, summary, CSV) | done (0.14.0) |
| P2.13 | response time and availability per device, firmware hints | done (0.15.0) |
| P2.14 | OPNsense and Docker integrations | done (0.16.0), not yet tested on real hardware |
| P2.15 | overview page, throughput in the topology | done (0.17.0) |
| P2.15a | ASUS traffic monitor (netdev) and traffic analyzer per client, ASUS diagnose | done (0.17.1) |
| P3.3 | sign-in with TOTP second factor, recovery codes, session management | done (0.20.0) |
| P3.4 | notifications by e-mail and ntfy (bundled, per-profile event selection, new events) | done (0.21.0) |
| P3.2 | speed tests: internet (Cloudflare, scheduled, history, slow-line hint) and iperf3 to a device | done (0.19.0) |
| P2.16 | live traffic per client (Omada, UniFi stat/sta, MikroTik registrations/Kid Control, OPNsense top talkers, Proxmox guests) in topology, device dialog and overview; illustrated getting-started guide | done (0.18.0), client rates not yet tested on real hardware |
 Phase 3: change history between scans, cable and patch-panel documentation,
Prometheus endpoint, REST API with tokens.

## Planned setup of the data sources

### Proxmox VE 9 (read-only API token)

Run once on any cluster node:

```bash
pveum role add DiktyoRead -privs "VM.Audit,VM.GuestAgent.Audit,Sys.Audit,Datastore.Audit,SDN.Audit"
pveum user add diktyo@pve --comment "díktyo read-only"
pveum acl modify / --users diktyo@pve --roles DiktyoRead
pveum user token add diktyo@pve diktyo --privsep 1
pveum acl modify / --tokens 'diktyo@pve!diktyo' --roles DiktyoRead
```

The token secret is shown once. In díktyo: URL `https://<node>:8006` (second node as fallback), token ID
`diktyo@pve!diktyo`, secret, and confirm the certificate fingerprint. VM addresses need the QEMU guest agent in
the VM. Proxmox VE 8 uses `VM.Monitor` instead of `VM.GuestAgent.Audit`.

### Home Assistant

- díktyo → HA: MQTT with HA discovery via the Mosquitto add-on (own MQTT user `diktyo`). Connectivity sensors per
  selected device, WAN in/out, number of unknown devices, events for "device offline" and "new unknown device";
  a blueprint turns the events into push notifications.
- HA → díktyo: long-lived access token (HA → profile → security). Device and entity registry, device trackers and
  areas; HA names become suggestions, areas become díktyo locations.
