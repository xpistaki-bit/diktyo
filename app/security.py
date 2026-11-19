"""Passwörter (scrypt wie PanelAtlas), Tokens, Verschlüsselung gespeicherter Zugangsdaten."""
import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from .db import DATA

KEY_PATH = DATA / "secret.key"
MASK = "••••••"  # Platzhalter, mit dem gespeicherte Geheimnisse an die Oberfläche gehen


def hash_pw(pw):
    salt = secrets.token_bytes(16)
    return salt.hex() + ":" + hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()


def check_pw(pw, stored):
    try:
        salt, h = stored.split(":")
        return hmac.compare_digest(hashlib.scrypt(str(pw).encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex(), h)
    except Exception:
        return False


DUMMY_HASH = hash_pw(secrets.token_hex(8))  # für gleich lange Antwortzeiten bei unbekannten Konten


def sha256(s):
    return hashlib.sha256(str(s).encode()).hexdigest()


def new_token():
    """-> (token für den Browser/Link, Hash für die Datenbank)"""
    tok = secrets.token_urlsafe(32)
    return tok, sha256(tok)


def generate_password():
    return secrets.token_urlsafe(12)


# ------------------------------------------------------------ Verschlüsselung
# Der Schlüssel liegt neben der Datenbank, wird aber nie mitgesichert. Backups verschlüsseln
# Zugangsdaten zusätzlich mit einer eigenen Backup-Passphrase (folgt mit dem Backup in M1).
_fernet = None


def _key():
    if not KEY_PATH.exists():
        try:
            fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        except FileExistsError:
            pass
    return KEY_PATH.read_bytes().strip()


def encrypt(text):
    global _fernet
    _fernet = _fernet or Fernet(_key())
    return _fernet.encrypt(str(text).encode()).decode()


def decrypt(token):
    global _fernet
    _fernet = _fernet or Fernet(_key())
    try:
        return _fernet.decrypt(str(token).encode()).decode()
    except InvalidToken:
        raise ValueError("Gespeichertes Geheimnis lässt sich nicht entschlüsseln (secret.key geändert?)")


def encrypt_bytes(data):
    global _fernet
    _fernet = _fernet or Fernet(_key())
    return _fernet.encrypt(bytes(data))


def decrypt_bytes(token):
    global _fernet
    _fernet = _fernet or Fernet(_key())
    try:
        return _fernet.decrypt(bytes(token))
    except InvalidToken:
        raise ValueError("Datei lässt sich nicht entschlüsseln (secret.key geändert?)")
