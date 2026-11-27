# Security policy

díktyo stores credentials for routers, switches and servers and can switch ports, Wi-Fi and internet access. Security
reports are therefore very welcome.

## Supported versions

Only the latest release (the newest version on the `main` branch) receives security fixes. Please update before
reporting – the problem may already be fixed.

| Version | Supported |
|---|---|
| latest release | yes |
| older versions | no |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub: open the [Security tab](https://github.com/xpistaki-bit/diktyo/security) and choose
**Report a vulnerability** (direct link: <https://github.com/xpistaki-bit/diktyo/security/advisories/new>).
Only the maintainer can see the report.

Helpful information:

- díktyo version and installation type (Proxmox LXC or Docker)
- what is affected (for example authentication, sharing between accounts, an integration, the backup)
- steps to reproduce or a proof of concept
- the impact you expect (for example access without login, reading another profile's data, leaking stored credentials)

Please do not include real passwords, API keys or data from your network in the report.

## What to expect

díktyo is a spare-time project, so handling is best effort:

- acknowledgement within about 7 days
- an assessment and, if confirmed, a plan for a fix
- a fix in a new release, then a published security advisory; reporters are credited if they wish

## Scope

In scope: the díktyo application in this repository (web interface, API, background service, installer and update
scripts, backup and restore).

Out of scope: vulnerabilities in third-party devices or services that díktyo talks to (FRITZ!Box, ASUS, UniFi, Proxmox
and others) – please report those to their vendors – and problems that require an attacker who already has
administrator access to díktyo or root access to the host.

## Testing

Please only test against your own installation. Do not access accounts, profiles or networks of other people, and do
not run denial-of-service tests.
