"""SQLite-Zugriff und versionierte Migrationen (PRAGMA user_version)."""
import contextlib
import datetime
import fcntl
import json
import os
import pathlib
import sqlite3

DATA = pathlib.Path(os.environ.get("DIKTYO_DATA", pathlib.Path(__file__).resolve().parent.parent / "data"))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / "diktyo.db"

# Jede Migration läuft genau einmal. Neue Migrationen nur hinten anhängen, bestehende nie ändern.
MIGRATIONS = [
    # 1: Konten, Sitzungen, Profile mit Mitgliedern, Einstellungen, Protokoll
    """
    CREATE TABLE users(
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        pw_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        lang TEXT,
        created TEXT NOT NULL,
        last_login TEXT);
    CREATE TABLE sessions(
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created REAL NOT NULL,
        expires REAL NOT NULL);
    CREATE TABLE password_resets(
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires REAL NOT NULL,
        used INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE profiles(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        settings TEXT NOT NULL DEFAULT '{}',
        created TEXT NOT NULL,
        updated TEXT NOT NULL);
    CREATE TABLE profile_members(
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('owner', 'edit', 'view')),
        PRIMARY KEY(profile_id, user_id));
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE audit_log(
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        user_id INTEGER,
        profile_id INTEGER,
        action TEXT NOT NULL,
        detail TEXT);
    """,
    # 2: Bestand und IPAM
    """
    CREATE TABLE locations(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        parent_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
        name TEXT NOT NULL,
        sort INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE device_models(
        id INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        manufacturer TEXT NOT NULL,
        model TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}',
        custom INTEGER NOT NULL DEFAULT 0,
        UNIQUE(manufacturer, model));
    CREATE TABLE devices(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'other',
        model_id INTEGER REFERENCES device_models(id) ON DELETE SET NULL,
        manufacturer TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'confirmed',
        hostname TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        data TEXT NOT NULL DEFAULT '{}',
        created TEXT NOT NULL,
        updated TEXT NOT NULL);
    CREATE INDEX devices_profile ON devices(profile_id);
    -- role 'nic': eigene Netzwerkschnittstelle des Geräts (trägt MAC/IP), role 'port': Anschluss an Switch/Router
    CREATE TABLE interfaces(
        id INTEGER PRIMARY KEY,
        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('nic', 'port')),
        name TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'rj45',
        port_no INTEGER,
        speed TEXT NOT NULL DEFAULT '',
        poe INTEGER NOT NULL DEFAULT 0,
        mac TEXT NOT NULL DEFAULT '');
    CREATE INDEX interfaces_device ON interfaces(device_id);
    CREATE INDEX interfaces_mac ON interfaces(mac);
    -- a = Gerät, das angeschlossen ist; b = Gegenstelle (Switch-Port, Access Point, Host)
    CREATE TABLE links(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        a_if INTEGER NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
        b_if INTEGER NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
        medium TEXT NOT NULL DEFAULT 'lan',
        uplink INTEGER NOT NULL DEFAULT 1,
        source TEXT NOT NULL DEFAULT 'manual',
        note TEXT NOT NULL DEFAULT '');
    CREATE INDEX links_a ON links(a_if);
    CREATE INDEX links_b ON links(b_if);
    CREATE TABLE vlans(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        vid INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        UNIQUE(profile_id, vid));
    CREATE TABLE subnets(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        vlan_id INTEGER REFERENCES vlans(id) ON DELETE SET NULL,
        cidr TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        gateway TEXT NOT NULL DEFAULT '',
        dns TEXT NOT NULL DEFAULT '',
        dhcp_start TEXT NOT NULL DEFAULT '',
        dhcp_end TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '');
    CREATE TABLE ip_addresses(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
        interface_id INTEGER REFERENCES interfaces(id) ON DELETE SET NULL,
        address TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'static',
        note TEXT NOT NULL DEFAULT '');
    CREATE INDEX ip_profile ON ip_addresses(profile_id);
    CREATE TABLE port_vlans(
        interface_id INTEGER NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
        vlan_id INTEGER NOT NULL REFERENCES vlans(id) ON DELETE CASCADE,
        tagged INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(interface_id, vlan_id));
    """,
    # 3: Netzscan, Erkennung, Aufträge für den Hintergrunddienst
    """
    ALTER TABLE devices ADD COLUMN online INTEGER;
    ALTER TABLE devices ADD COLUMN last_seen TEXT;
    CREATE TABLE jobs(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'done', 'error')),
        progress INTEGER NOT NULL DEFAULT 0,
        message TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '{}',
        user_id INTEGER,
        created TEXT NOT NULL,
        started TEXT,
        finished TEXT);
    CREATE INDEX jobs_status ON jobs(status);
    CREATE TABLE observations(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        ip TEXT NOT NULL DEFAULT '',
        mac TEXT NOT NULL DEFAULT '',
        data TEXT NOT NULL DEFAULT '{}',
        seen TEXT NOT NULL);
    CREATE INDEX observations_profile ON observations(profile_id, seen);
    CREATE INDEX observations_device ON observations(device_id);
    CREATE TABLE status_events(
        id INTEGER PRIMARY KEY,
        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        ts TEXT NOT NULL,
        online INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'scan');
    CREATE INDEX status_events_device ON status_events(device_id, ts);
    CREATE TABLE ident_rules(
        id INTEGER PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        label_en TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT 'other',
        cond TEXT NOT NULL DEFAULT '{}',
        weight INTEGER NOT NULL DEFAULT 50,
        custom INTEGER NOT NULL DEFAULT 0);
    """,
    # 4: Herkunft von IP-Adressen; Integrationen (FRITZ!Box, SNMP) und Messwerte
    """
    ALTER TABLE ip_addresses ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
    CREATE TABLE integrations(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        driver TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        host TEXT NOT NULL,
        port INTEGER,
        username TEXT NOT NULL DEFAULT '',
        secret TEXT NOT NULL DEFAULT '',
        options TEXT NOT NULL DEFAULT '{}',
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        interval_s INTEGER NOT NULL DEFAULT 60,
        enabled INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL DEFAULT '{}',
        last_poll TEXT,
        last_ok TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL);
    CREATE TABLE series(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        unit TEXT NOT NULL DEFAULT '',
        UNIQUE(profile_id, key));
    CREATE TABLE metrics(
        series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
        ts INTEGER NOT NULL,
        value REAL NOT NULL);
    CREATE INDEX metrics_series_ts ON metrics(series_id, ts);
    UPDATE ip_addresses SET source='scan' WHERE device_id IN (SELECT id FROM devices WHERE status<>'confirmed')
        OR id IN (SELECT a.id FROM ip_addresses a JOIN observations o ON o.device_id = a.device_id AND o.ip = a.address);
    """,
    # 5: Ereignisse (Gerät offline/online, neues Gerät) für Benachrichtigungen, z. B. an Home Assistant
    """
    CREATE TABLE events(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        data TEXT NOT NULL DEFAULT '{}',
        delivered TEXT NOT NULL DEFAULT '');
    CREATE INDEX events_profile ON events(profile_id, id);
    """,
    # 6: Konfigurations-Backups von Geräten (Datei verschlüsselt unter DATA/configs)
    """
    CREATE TABLE config_backups(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        integration_id INTEGER REFERENCES integrations(id) ON DELETE SET NULL,
        created TEXT NOT NULL,
        kind TEXT NOT NULL,
        filename TEXT NOT NULL,
        size INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        is_text INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '');
    CREATE INDEX config_backups_device ON config_backups(device_id, id);
    """,
    # 7: von Hand verschobene Knoten der Topologie (je Profil, Schlüssel = Knoten-ID wie "d12", "g3:wlan", "internet")
    """
    CREATE TABLE topo_positions(
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        node TEXT NOT NULL,
        x REAL NOT NULL,
        y REAL NOT NULL,
        PRIMARY KEY(profile_id, node));
    """,
    # 8: Schaltaktionen (WLAN, Internetzugang, Switch-Port, PoE, VM) mit optionalem automatischen Zurückschalten
    """
    CREATE TABLE actions(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        integration_id INTEGER REFERENCES integrations(id) ON DELETE SET NULL,
        user_id INTEGER,
        kind TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        label TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL,
        undo_at TEXT,
        undone TEXT,
        undo_result TEXT);
    CREATE INDEX actions_profile ON actions(profile_id, id);
    """,
    # 9: Zeitpläne für Aktionen und Quarantäne für neue Geräte
    """
    CREATE TABLE schedules(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
        integration_id INTEGER REFERENCES integrations(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}',
        label TEXT NOT NULL DEFAULT '',
        port INTEGER NOT NULL DEFAULT 0,
        days TEXT NOT NULL,
        start TEXT NOT NULL,
        end_time TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        created TEXT NOT NULL,
        created_by INTEGER,
        last_check TEXT,
        last_run TEXT,
        last_result TEXT);
    CREATE TABLE quarantine(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        integration_id INTEGER REFERENCES integrations(id) ON DELETE SET NULL,
        ip TEXT NOT NULL,
        mac TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        since TEXT NOT NULL,
        released TEXT,
        message TEXT NOT NULL DEFAULT '');
    CREATE INDEX quarantine_profile ON quarantine(profile_id, status);
    """,
    # 10: Änderungsverlauf (Schnappschüsse je Gerät ohne Fremdschlüssel, damit Löschungen erkennbar bleiben)
    """
    CREATE TABLE changes(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        field TEXT NOT NULL DEFAULT '',
        old TEXT NOT NULL DEFAULT '',
        new TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        user_id INTEGER,
        detail TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX changes_profile ON changes(profile_id, ts);
    CREATE INDEX changes_device ON changes(device_id, ts);
    CREATE TABLE device_snapshots(
        device_id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        data TEXT NOT NULL);
    """,
    # Verbindungen: wann die Quelle sie zuletzt bestätigt hat (Vorrang genauerer Quellen); wer ein Gerät zuletzt online sah
    """
    ALTER TABLE links ADD COLUMN confirmed REAL NOT NULL DEFAULT 0;
    CREATE TABLE device_seen(
        device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        ts REAL NOT NULL,
        PRIMARY KEY(device_id, source));
    """,
    # Geschwindigkeitsmessungen (Internet-Speedtest, iperf3) – dauerhaft, unabhängig von den kurzlebigen Messwerten
    """
    CREATE TABLE speedtests(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
        ts TEXT NOT NULL,
        down_bps REAL, up_bps REAL, ping_ms REAL, jitter_ms REAL,
        server TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '{}',
        scheduled INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX speedtests_profile ON speedtests(profile_id, kind, ts);
    """,
    # Zweiter Faktor (TOTP) und Sitzungsverwaltung
    """
    ALTER TABLE users ADD COLUMN totp_secret TEXT NOT NULL DEFAULT '';
    ALTER TABLE users ADD COLUMN totp_pending TEXT NOT NULL DEFAULT '';
    ALTER TABLE users ADD COLUMN totp_last INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN recovery TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE sessions ADD COLUMN ip TEXT NOT NULL DEFAULT '';
    ALTER TABLE sessions ADD COLUMN user_agent TEXT NOT NULL DEFAULT '';
    ALTER TABLE sessions ADD COLUMN last_seen REAL NOT NULL DEFAULT 0;
    CREATE TABLE login_tickets(
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires REAL NOT NULL,
        tries INTEGER NOT NULL DEFAULT 0);
    """,
    # Benachrichtigungen (E-Mail, ntfy): bis zu welchem Ereignis schon verschickt
    """
    CREATE TABLE notify_state(
        profile_id INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
        last_id INTEGER NOT NULL DEFAULT 0,
        last_sent REAL NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '');
    """,
    # Wachliste: beobachtete Geräte, Alarm bis zum Quittieren (ack_* = letzte schon gesehene Änderung/Statuswechsel)
    """
    CREATE TABLE watch(
        device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        created TEXT NOT NULL,
        ack TEXT NOT NULL,
        ack_change INTEGER NOT NULL DEFAULT 0,
        ack_status INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '');
    CREATE INDEX watch_profile ON watch(profile_id);
    """,
    # Kabel und Patchpanels: Patchfelder/Dosen und Kabelwege (Switch-Port – Patchfeld – Dose – Gerät, mit Kabelnummern)
    """
    CREATE TABLE patch_panels(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'panel' CHECK(kind IN ('panel', 'outlet')),
        name TEXT NOT NULL,
        location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
        ports INTEGER NOT NULL DEFAULT 24,
        note TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL);
    CREATE INDEX patch_panels_profile ON patch_panels(profile_id);
    CREATE TABLE cable_runs(
        id INTEGER PRIMARY KEY,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        switch_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        switch_port INTEGER,
        panel_id INTEGER REFERENCES patch_panels(id) ON DELETE SET NULL,
        panel_port INTEGER,
        outlet_id INTEGER REFERENCES patch_panels(id) ON DELETE SET NULL,
        outlet_port INTEGER,
        device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
        cable_a TEXT NOT NULL DEFAULT '',
        cable_b TEXT NOT NULL DEFAULT '',
        cable_c TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        updated TEXT NOT NULL);
    CREATE INDEX cable_runs_profile ON cable_runs(profile_id);
    """,
    # VLAN-Plan: Farbe und „nur geplant“ je VLAN, Herkunft der produktiven Zuordnung, geplante Zuordnung
    """
    ALTER TABLE vlans ADD COLUMN color TEXT NOT NULL DEFAULT '';
    ALTER TABLE vlans ADD COLUMN planned INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE port_vlans ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
    CREATE TABLE port_vlans_plan(
        interface_id INTEGER NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
        vlan_id INTEGER NOT NULL REFERENCES vlans(id) ON DELETE CASCADE,
        tagged INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(interface_id, vlan_id));
    """,
]


def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextlib.contextmanager
def db():
    con = connect()
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def migrate():
    # Web-App und Hintergrunddienst starten gleichzeitig: nur einer darf migrieren.
    with open(DATA / ".migrate.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _migrate()


def _migrate():
    con = connect()
    try:
        con.execute("PRAGMA journal_mode=WAL")
        have = con.execute("PRAGMA user_version").fetchone()[0]
        for n, sql in enumerate(MIGRATIONS[have:], start=have + 1):
            con.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={n};\nCOMMIT;")
    finally:
        con.close()


def now():
    """Ortszeit mit Zeitzonen-Angabe, damit der Browser sie richtig umrechnet (der Container läuft oft in UTC)."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_ts(s):
    d = datetime.datetime.fromisoformat(s)
    return d if d.tzinfo else d.astimezone()


def get_setting(c, key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(c, key, value):
    c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, json.dumps(value, ensure_ascii=False)))


def audit(c, action, user_id=None, profile_id=None, detail=None):
    c.execute("INSERT INTO audit_log(ts, user_id, profile_id, action, detail) VALUES(?,?,?,?,?)",
              (now(), user_id, profile_id, action, json.dumps(detail, ensure_ascii=False) if detail is not None else None))
