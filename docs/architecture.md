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
| P2.4 | more integrations: Netgear, devolo, Docker API | done (Docker 0.16, Netgear/devolo 0.38) |
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
| P3.5 | actions via UniFi/Omada (restart, PoE), Shelly/Tasmota integration (power, switching, firmware) | done (0.22.0), not yet tested on real hardware |
| P3.6 | Pi-hole / AdGuard Home integration (host names, per-device query stats, blocking toggle) | done (0.23.0) |
| P3.7 | overview redesign (HUD, full width): KPI tiles, WAN bar chart, speed gauges, ports with the device behind them, response-time sparklines, infrastructure cards; shared HUD components in `static/hud.js` with HTML axis labels; integrations in a grid | done (0.25.0) |
| P3.8 | customizable overview: per-profile layout in `profiles.settings.dashboard` (`dashlayout.py`: order, width, hidden, pinned charts validated against the profile's series), pin buttons on integration cards and in the device dialog | done (0.26.0) |
| P3.9 | watchlist (`watch.py`, table `watch`): alarm state per watched device from `changes` (ips, mac, name, uplink; not source `user`) and `status_events` after the acknowledged ids; `watch_change` event from `changes.sync` for notifications, offline of watched devices always notified | done (0.27.0) |
| P3.10 | QR labels (`labels.py`): PDF via SVG + CairoSVG, QR from segno as one path, sheet/roll formats, skip for partly used sheets; deep link `#/p/<pid>/geraete/<did>` opens the device dialog, kept across login | done (0.28.0) |
| P3.11 | cabling (`cabling.py`, tables `patch_panels`, `cable_runs`): runs switch port (device + port_no) → panel port → outlet → device with cable numbers a/b/c, one run per port, check against links on the switch port; tab, device dialog, PDF section, backup (also `watch`) | done (0.29.0) |
| P3.12 | VLAN plan (`vlanplan.py`): productive `port_vlans` (source snmp from Q-BRIDGE-MIB via `drivers/snmp.read_vlans`, or manual) and plan `port_vlans_plan` (full copy, plan meta in `profiles.settings.vlan_plan`), planned VLANs (`vlans.planned`), diff/change list, checks (address vs. subnet, uplink carries VLANs), adopt/finish/discard; never writes to switches | done (0.30.0) |
| P3.13 | network ports only: `catalog.is_network` (kind usb or labels like HDMI/Thunderbolt/MagSafe/card reader are not network), `expand_ports` numbers network ports only; one-off `network_ports_once` in `db.migrate` (under the lock) renumbers existing ports and cable runs | done (0.30.1) |
| P3.14 | Prometheus endpoint (`prometheus.py`, `routes_prometheus.py`): `/api/profiles/<id>/prometheus`, bearer token per profile (hash in `profiles.settings.prometheus`, failed attempts rate-limited), text format 0.0.4 with current values (latest metric per series within 15 min, device state, speed test, integrations, watchlist, VLAN plan), Grafana dashboard JSON | done (0.31.0) |
| P3.15 | OIDC sign-in (`oidc.py`, `routes_oidc.py`): authorization code + PKCE S256, single-use state hashed in `oidc_states` and bound to the browser (cookie `dk_oidc`), nonce, ID token verified via JWKS (RS/PS/ES/HS) with iss/aud/exp, userinfo fallback; accounts linked via `users.oidc_sub` (`issuer|sub`), by verified e-mail or from the user's settings; optional auto-create, required group, admin group; settings `oidc` (secret encrypted, in backups) | done (0.32.0) |
| P3.16 | network map export (`netplan.py`): topology layout incl. pinned positions (`export.topology_layout`, groups optionally expanded) as standalone SVG, PNG (CairoSVG ×2), draw.io mxGraph XML (UserObject with ip/mac/type/model/location), poster PDF A4–A0 with title block, auto orientation, optional A4 tiling with overlap and marks | done (0.33.0) |
| P3.17 | MikroTik over the RouterOS API (`drivers/routeros_api.py`: length-prefixed sentences, login incl. pre-6.43 challenge, same menu paths as REST via `request()`), REST optional, no SSH backup; server messages in English (`msg_en.py`: exact texts, patterns with recursively translated parts; used for error responses, notifications and via `/api/i18n/messages` in the UI's `t()`/`ts()`), test that every message in the code has an English version | done (0.33.1) |
| P3.18 | self-update (`selfupdate.py`, `install/self-update.sh`): version check against `app/version.py` on GitHub (worker, at most every 12 h) with version commits as notes; the web app writes `/var/lib/diktyo/update/request.json`, `diktyo-update.path` starts the fixed root script (DB backup via sqlite backup as diktyo, tarball from the branch in root-owned `/opt/diktyo/update.conf`, `setup.sh`), status written as user diktyo; MikroTik over SNMP (`drivers/mikrotik_snmp.py`: IF/IP/BRIDGE/IP-FORWARD/HOST-RESOURCES + MIKROTIK-MIB into the same raw shape as the API, read only) | done (0.34.0) |
| P3.19 | code-scanning fixes (CodeQL): SSH host-key policy in `sshcfg._policy` rejects a changed key before authentication (no `AutoAddPolicy`), linear regexes in `users.EMAIL_RE` and `sysinfo`, `ssl.TLSVersion.TLSv1_2` minimum for api-ssl, `configbackup.path` confined to the data dir, unexpected exceptions logged instead of returned; MD5 in the FRITZ!Box and pre-6.43 RouterOS challenges stays (protocol requirement) | done (0.34.1) |
| P3.20 | cable labels (`cablelabels.py`): every cable number of a cable run (`cable_a/b/c`) becomes a label with its two ends (station before → next present station, as in the run table); optional one label per end naming the far end; number shrinks to fit (never cut), arrow drawn as a path; shared sheet layout `labels.sheets`; formats incl. Avery 3666/L7651 and 12 mm tape; `GET /export/cable-labels[.pdf]` | done (0.35.0) |
| P3.21 | floor plans and racks (`locplan.py`, `routes_locplan.py`, `static/locplan.js`): `locations.kind` area/rack with `rack_units`, `location_images` (BLOB, type by magic bytes, no SVG, served with nosniff), `plan_items` (device/panel/room, relative 0…1 coordinates; a device without location takes the plan's location), `rack_items` (device/panel/other, lowest U + height, overlap check, one rack per device/panel, mounting sets the location); view at `#/p/<pid>/standorte/<lid>`; PDF section `plans` (rack elevation and plan with embedded image as SVG); backup exports images base64 | done (0.36.0) |
| P3.22 | topology groups (`topogroups.py`, routes `/topology/groups`, `/topology/settings`): `topo_groups` (name, colour) and `topo_group_members` (one group per device); `profiles.settings.topology` = group_by medium/custom/location/tag/vlan plus thresholds `min_wlan`, `min_virtual`, `min_group` (0 = never); `topology.build` groups leaf children per parent by the chosen key (`c<id>`, `l<id>`, `t<sha1>`, `v<vid>`), the rest falls back to Wi-Fi/virtual; group node id `g<parent>:<key>` (expand, saved position); VLAN of a device from the untagged port VLAN, Proxmox tag or subnet; exports use `export.group_label`; backup remaps group and location ids in node positions | done (0.37.0) |
| P3.23 | vendor profiles for SNMP (`drivers/snmpprofiles.py`: detection by sysObjectID enterprise number or description, option `profile`; ENTITY-MIB chassis model/serial/firmware/hardware for all vendors, Netgear agentInventoryGroup and boxServicesTempSensorTemperature under 4526.10/4526.11, hrProcessorLoad; hints for enabling SNMP and write access) and devolo Powerline (`drivers/devolo.py`: unicast mDNS query with QU bit for `_dvl-plcnetapi`/`_dvl-deviceapi`, HTTP digest user `devolo` with SHA-256 fallback, own protobuf decoder for GetNetworkOverview, WifiConnectedStationsGet, UpdateFirmwareCheck once a day); `apply_devolo` creates adapters as type powerline, links them with the new medium `powerline` to the adapter at the router, LAN-side and Wi-Fi devices to their adapter | done (0.38.0) |
| P3.24 | code scanning round 2: `backup.run` reports fixed texts via `failure_text` (exception text only in the service log, WebDAV status without raise, rclone result without raise), `cli` asks passwords with getpass and never prints them, `sysinfo._fields` splits at the first `:`/`=` and checks the key with a single-quantifier regex | done (0.38.1) |
| P3.25 | VLANs from more integrations: `controller.vid_list`/`vlan_result` build the SNMP-style result; `mikrotik.vlans` (interface/bridge, bridge/vlan, bridge/port, interface/vlan), `opnsense.vlans` (interfaces/vlan_settings/search_item), `unifi.port_vlans` (classic API rest/networkconf, rest/portconf, stat/device port_overrides; retried after a day if refused), `omada.vlans` (switches/{mac}/networks-detail); `vlanplan.apply_switch(..., source)` stores the driver as `port_vlans.source`, SNMP rows take precedence, `snmp_devices` returns {device: source} | done (0.39.0) |
| P3.26 | OpenWrt (`drivers/openwrt.py`): ubus JSON-RPC at `/ubus` (session login, re-login on -32002, HTTPS then HTTP), reads system board/info, network.device status (front ports lanN/wanN, ethN only without DSA), network.interface dump (WAN), luci-rpc getDHCPLeases/getHostHints, network.wireless status, iwinfo assoclist, uci get network (bridge-vlan → VLAN plan); result in the router format of MikroTik/OPNsense (`apply_mikrotik`, role router/ap/switch); actions wlan (uci set/commit + network reload, section name validated) and reboot; backup via /cgi-bin/cgi-backup, repacked deterministically (sorted, mtime 0) so unchanged configs are detected | done (0.40.0) |
| P3.27 | navigation cleanup: `#/konto[/pid]` (`viewAccount`: password, 2FA/sessions, OIDC link, profiles with `renderSharing`), `#/einstellungen[/pid]` (`profileSettings`: notify + quarantine of the chosen profile; admin system tiles, each `.panel` starts with `h3`), profile tab `aktionen` (`tabActions`: schedules, recent actions), old tab `freigabe` redirects to `#/konto/<pid>`; history: `DELETE /history` (owner, kinds change/status/action/quarantine, `older_than_days`; keeps the latest status event per device, pending undos, active quarantine; audited) and `history.csv` with kinds/q filter | done (0.41.0) |
| P3.28 | ASUS actions and readable config: `asuswrt.guests` (appGet nvram wlU.I_ssid/_bss_enabled, `sdn_rl` → SDN), `asuswrt.action` guest/reboot via `applyapp.cgi` (session reuse, one re-login on Main_Login redirect); `decode_cfg` (HDR1 plain, HDR2/N55U/AC55U: 3-byte length, random byte r, b → (0xFF + r − b) & 0xFF, bytes > 0xFC are separators), `config_text` (sorted, secrets masked with a 4-hex SHA-256 tag), `canonical` for de-duplication; `configbackup.readable/text_of` let drivers provide `config_text`, diff and `download?text=1` use it; kind `guest` is reversible and schedulable | done (0.42.0) |
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
