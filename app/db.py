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
