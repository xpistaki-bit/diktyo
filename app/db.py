"""SQLite-Zugriff und versionierte Migrationen (PRAGMA user_version)."""
import contextlib
import datetime
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
    con = connect()
    try:
        con.execute("PRAGMA journal_mode=WAL")
        have = con.execute("PRAGMA user_version").fetchone()[0]
        for n, sql in enumerate(MIGRATIONS[have:], start=have + 1):
            con.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={n};\nCOMMIT;")
    finally:
        con.close()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def get_setting(c, key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(c, key, value):
    c.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, json.dumps(value, ensure_ascii=False)))


def audit(c, action, user_id=None, profile_id=None, detail=None):
    c.execute("INSERT INTO audit_log(ts, user_id, profile_id, action, detail) VALUES(?,?,?,?,?)",
              (now(), user_id, profile_id, action, json.dumps(detail, ensure_ascii=False) if detail is not None else None))
