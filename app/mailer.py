"""E-Mail-Versand (SMTP) für das Zurücksetzen von Passwörtern."""
import smtplib
import ssl
from email.message import EmailMessage

from . import security
from .db import get_setting

TEXTS = {
    "de": dict(
        subject="díktyo: Passwort zurücksetzen",
        body="Jemand (hoffentlich du) möchte das Passwort für dein díktyo-Konto zurücksetzen.\n\n"
             "Öffne innerhalb einer Stunde diesen Link, um ein neues Passwort zu wählen:\n{link}\n\n"
             "Wenn du das nicht angefordert hast, kannst du diese E-Mail ignorieren.\n",
        test_subject="díktyo: Testnachricht",
        test_body="Der E-Mail-Versand von díktyo funktioniert.\n"),
    "en": dict(
        subject="díktyo: reset your password",
        body="Someone (hopefully you) asked to reset the password for your díktyo account.\n\n"
             "Open this link within one hour to choose a new password:\n{link}\n\n"
             "If you did not request this, you can ignore this e-mail.\n",
        test_subject="díktyo: test message",
        test_body="Sending e-mail from díktyo works.\n"),
}


def smtp_config(c):
    return get_setting(c, "smtp", {}) or {}


def enabled(c):
    return bool(smtp_config(c).get("host"))


def send(cfg, to, subject, text):
    if not cfg.get("host"):
        raise RuntimeError("E-Mail-Versand ist nicht eingerichtet")
    msg = EmailMessage()
    msg["From"] = cfg.get("sender") or cfg.get("user") or "diktyo@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    port = int(cfg.get("port") or 587)
    mode = cfg.get("security") or "starttls"
    password = security.decrypt(cfg["password"]) if cfg.get("password") else ""
    ctx = ssl.create_default_context()
    if mode == "ssl":
        s = smtplib.SMTP_SSL(cfg["host"], port, timeout=20, context=ctx)
    else:
        s = smtplib.SMTP(cfg["host"], port, timeout=20)
    with s:
        if mode == "starttls":
            s.starttls(context=ctx)
        if cfg.get("user"):
            s.login(cfg["user"], password)
        s.send_message(msg)


def send_reset(cfg, to, link, lang="de"):
    t = TEXTS.get(lang, TEXTS["de"])
    send(cfg, to, t["subject"], t["body"].format(link=link))


def send_test(cfg, to, lang="de"):
    t = TEXTS.get(lang, TEXTS["de"])
    send(cfg, to, t["test_subject"], t["test_body"])
