"""díktyo-Kommandozeile, zum Beispiel für ein Passwort ohne E-Mail-Versand.

LXC:     diktyo reset-password ich@example.com
Docker:  docker compose exec diktyo python -m app.cli reset-password ich@example.com

Ohne Passwort-Argument fragt das Programm das neue Passwort verdeckt ab (zweimal). Passwörter werden nie ausgegeben.
"""
import argparse
import getpass
import sys

from . import users
from .db import db, migrate


def need(c, email):
    u = users.by_email(c, email)
    if not u:
        sys.exit(f'Kein Konto mit der E-Mail-Adresse "{email}"')
    return u


def ask_password():
    """Neues Passwort verdeckt abfragen (zweimal). Ohne Terminal: Abbruch mit Hinweis."""
    if not sys.stdin.isatty():
        sys.exit("Kein Terminal für die Passworteingabe. Mit Terminal starten (docker compose exec ohne -T, pct enter) "
                 "oder das Passwort als Argument angeben.")
    for _ in range(3):
        a, b = getpass.getpass("Neues Passwort: "), getpass.getpass("Wiederholen: ")
        if a != b:
            print("Die Eingaben stimmen nicht überein.")
        elif len(a) < 8:
            print("Das Passwort muss mindestens 8 Zeichen haben.")
        else:
            return a
    sys.exit("Abgebrochen.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="diktyo", description="díktyo – Konten auf der Kommandozeile verwalten")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-users", help="alle Konten anzeigen")
    p = sub.add_parser("reset-password", help="neues Passwort setzen (wird verdeckt abgefragt, wenn keins angegeben)")
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
    p = sub.add_parser("reset-2fa", help="zweiten Faktor eines Kontos ausschalten (z. B. Handy verloren)")
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
                users.set_password(c, u["id"], a.password or ask_password())
                print(f"Passwort für {u['email']} gesetzt.")
                print("Alle Sitzungen dieses Kontos wurden abgemeldet.")
            elif a.cmd == "create-user":
                u = users.create(c, a.email, a.password or ask_password(), is_admin=a.admin)
                print(f"{'Administrator-' if u['is_admin'] else ''}Konto {u['email']} angelegt.")
            elif a.cmd == "set-admin":
                u = need(c, a.email)
                users.set_admin(c, u["id"], a.state == "on")
                print(f"{u['email']} ist {'jetzt' if a.state == 'on' else 'nicht mehr'} Administrator.")
            elif a.cmd == "reset-2fa":
                from . import twofa
                u = need(c, a.email)
                twofa.disable(c, u["id"])
                c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
                print(f"Zweiter Faktor für {u['email']} ausgeschaltet, alle Sitzungen abgemeldet. Anmeldung jetzt nur mit Passwort.")
            elif a.cmd == "delete-user":
                u = need(c, a.email)
                heir = c.execute("SELECT id FROM users WHERE is_admin=1 AND id<>? ORDER BY id LIMIT 1", (u["id"],)).fetchone()
                users.delete(c, u["id"], heir_id=heir["id"] if heir else None)
                print(f"{u['email']} gelöscht.")
    except users.UserError as ex:
        sys.exit(f"Fehler: {ex.msg}")


if __name__ == "__main__":
    main()
