"""díktyo-Kommandozeile, zum Beispiel für ein Passwort ohne E-Mail-Versand.

LXC:     diktyo reset-password ich@example.com
Docker:  docker compose exec diktyo python -m app.cli reset-password ich@example.com
"""
import argparse
import sys

from . import security, users
from .db import db, migrate


def need(c, email):
    u = users.by_email(c, email)
    if not u:
        sys.exit(f'Kein Konto mit der E-Mail-Adresse "{email}"')
    return u


def main(argv=None):
    ap = argparse.ArgumentParser(prog="diktyo", description="díktyo – Konten auf der Kommandozeile verwalten")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-users", help="alle Konten anzeigen")
    p = sub.add_parser("reset-password", help="neues Passwort setzen (zufällig, wenn keins angegeben)")
    p.add_argument("email")
    p.add_argument("password", nargs="?")
    p = sub.add_parser("create-user", help="Konto anlegen")
    p.add_argument("email")
    p.add_argument("password", nargs="?")
    p.add_argument("--admin", action="store_true")
    p = sub.add_parser("set-admin", help="Administratorrecht geben oder entziehen")
    p.add_argument("email")
    p.add_argument("state", choices=["on", "off"])
    p = sub.add_parser("delete-user", help="Konto löschen (Profile gehen an einen Administrator über)")
    p.add_argument("email")
    a = ap.parse_args(argv)

    migrate()
    try:
        with db() as c:
            if a.cmd == "list-users":
                rows = c.execute("SELECT * FROM users ORDER BY email").fetchall()
                if not rows:
                    print("Noch keine Konten. Das erste Konto, das in der Weboberfläche angelegt wird, wird Administrator.")
                for r in rows:
                    print(f"{'[admin] ' if r['is_admin'] else '        '}{r['email']}   (letzte Anmeldung: {r['last_login'] or 'nie'})")
            elif a.cmd == "reset-password":
                u = need(c, a.email)
                pw = a.password or security.generate_password()
                users.set_password(c, u["id"], pw)
                print(f"Neues Passwort für {u['email']}: {pw}\nAlle Sitzungen dieses Kontos wurden abgemeldet.")
            elif a.cmd == "create-user":
                pw = a.password or security.generate_password()
                u = users.create(c, a.email, pw, is_admin=a.admin)
                print(f"{'Administrator-' if u['is_admin'] else ''}Konto {u['email']} angelegt, Passwort: {pw}")
            elif a.cmd == "set-admin":
                u = need(c, a.email)
                users.set_admin(c, u["id"], a.state == "on")
                print(f"{u['email']} ist {'jetzt' if a.state == 'on' else 'nicht mehr'} Administrator.")
            elif a.cmd == "delete-user":
                u = need(c, a.email)
                heir = c.execute("SELECT id FROM users WHERE is_admin=1 AND id<>? ORDER BY id LIMIT 1", (u["id"],)).fetchone()
                users.delete(c, u["id"], heir_id=heir["id"] if heir else None)
                print(f"{u['email']} gelöscht.")
    except users.UserError as ex:
        sys.exit(f"Fehler: {ex.msg}")


if __name__ == "__main__":
    main()
