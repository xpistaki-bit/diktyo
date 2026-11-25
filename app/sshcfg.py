"""Konfiguration eines Netzwerkgeräts per SSH lesen (paramiko). Host-Schlüssel: beim ersten Mal merken, danach prüfen.

Anmeldung wahlweise mit Passwort (fällt bei Bedarf auf keyboard-interactive zurück), mit díktyos eigenem Schlüssel
(RSA 4096, einmal je Installation erzeugt, der private Teil liegt verschlüsselt in den Einstellungen) oder mit einem
eigenen privaten Schlüssel (RSA, ECDSA, Ed25519). Ältere Geräte, die RSA-Schlüssel nur mit ssh-rsa (SHA-1) annehmen,
werden mit einem zweiten Versuch bedient.
"""
import io
import re
import time

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MORE = re.compile(r"-+ ?more ?-+|--more--|<--- more --->|press any key", re.I)


class SSHError(Exception):
    pass


def _clean(text, command):
    text = ANSI.sub("", text).replace("\r", "")
    text = MORE.sub("", text)
    lines = text.split("\n")
    # Echo des Befehls und abschließende Eingabeaufforderung entfernen
    if lines and command in lines[0]:
        lines = lines[1:]
    while lines and (not lines[-1].strip() or re.fullmatch(r"\S+[#>$]\s*", lines[-1].strip())):
        lines.pop()
    return "\n".join(lines).strip() + "\n"


def load_key(text, passphrase=None):
    """Privaten Schlüssel (OpenSSH- oder PEM-Format) lesen -> paramiko-Schlüssel."""
    import paramiko
    text = (text or "").strip()
    if not text:
        raise SSHError("Kein privater Schlüssel angegeben")
    if "PUBLIC KEY" in text or text.startswith(("ssh-rsa ", "ssh-ed25519 ", "ecdsa-")):
        raise SSHError("Das ist ein öffentlicher Schlüssel (.pub) – hier gehört der private Schlüssel hin, der öffentliche kommt auf das Gerät")
    last = None
    for cls in (paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key):
        try:
            return cls.from_private_key(io.StringIO(text + "\n"), password=passphrase or None)
        except paramiko.PasswordRequiredException:
            raise SSHError("Der private Schlüssel ist mit einer Passphrase geschützt – Passphrase angeben")
        except (paramiko.SSHException, ValueError) as ex:
            last = ex
    raise SSHError(f"Privater Schlüssel nicht lesbar ({last})")


def own_key(c):
    """díktyos eigener SSH-Schlüssel (wird beim ersten Aufruf erzeugt). -> (paramiko-Schlüssel, öffentlicher Schlüssel als Zeile)"""
    import paramiko
    from . import security
    from .db import get_setting, set_setting
    st = get_setting(c, "ssh_key") or {}
    if st.get("private"):
        key = paramiko.RSAKey.from_private_key(io.StringIO(security.decrypt(st["private"])))
    else:
        key = paramiko.RSAKey.generate(4096)  # RSA: von Switches wie Zyxel unterstützt, Ed25519 oft nicht
        buf = io.StringIO()
        key.write_private_key(buf)
        set_setting(c, "ssh_key", dict(private=security.encrypt(buf.getvalue()), created=time.time()))
    return key, f"{key.get_name()} {key.get_base64()} diktyo"


def fingerprint(key):
    return f"{key.get_name()} {key.fingerprint}" if hasattr(key, "fingerprint") else f"{key.get_name()} {key.get_base64()[:32]}"


def _policy(paramiko, known):
    """Host-Schlüssel beim Verbindungsaufbau prüfen – vor dem Senden von Passwort oder Schlüssel. Ohne bekannten Schlüssel
    (erste Verbindung) wird er angenommen und danach gespeichert; weicht er später ab, bricht die Verbindung ab."""
    class Policy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fp = fingerprint(key)
            if known and fp != known:
                raise paramiko.SSHException(f"hostkey-changed:{fp}")
    return Policy()


def run(host, port, user, password, command, known=None, timeout=15, pkey=None, mode="auto"):
    """-> (Ausgabe, Fingerabdruck des Host-Schlüssels). pkey statt password für die Anmeldung mit Schlüssel.
    mode: auto (Einzelbefehl, sonst interaktive Sitzung) | exec | shell"""
    try:
        import paramiko
    except ImportError:
        raise SSHError("paramiko ist nicht installiert")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(_policy(paramiko, known))
    kw = dict(port=port, username=user, look_for_keys=False, allow_agent=False, timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
    try:
        if pkey is not None:
            try:
                c.connect(host, pkey=pkey, **kw)
            except paramiko.AuthenticationException:
                if pkey.get_name() != "ssh-rsa":
                    raise
                c.close()
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(_policy(paramiko, known))
                # ältere Firmware: RSA-Signatur nur als ssh-rsa (SHA-1)
                c.connect(host, pkey=pkey, disabled_algorithms={"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}, **kw)
        else:
            c.connect(host, password=password, **kw)
    except paramiko.AuthenticationException:
        raise SSHError("SSH-Anmeldung abgelehnt (" + ("ist der öffentliche Schlüssel auf dem Gerät hinterlegt und passt der Benutzer?" if pkey is not None
                                                       else "Benutzer oder Passwort prüfen") + ")")
    except (paramiko.SSHException, OSError) as ex:
        if str(ex).startswith("hostkey-changed:"):
            raise SSHError(f"Host-Schlüssel des Geräts hat sich geändert ({str(ex).split(':', 1)[1]}); Backup aus Sicherheitsgründen abgebrochen. "
                           f"Wurde das Gerät ausgetauscht, die Integration einmal neu speichern.")
        raise SSHError(f"SSH-Verbindung fehlgeschlagen: {ex}")
    try:
        fp = fingerprint(c.get_transport().get_remote_server_key())
        if known and known != fp:  # doppelt gesichert; die eigentliche Prüfung geschieht vor der Anmeldung (_policy)
            raise SSHError(f"Host-Schlüssel des Geräts hat sich geändert ({fp}); Backup aus Sicherheitsgründen abgebrochen. "
                           f"Wurde das Gerät ausgetauscht, die Integration einmal neu speichern.")
        out = ""
        if mode != "shell":
            try:  # zuerst als einzelner Befehl
                _, stdout, _ = c.exec_command(command, timeout=timeout)
                out = stdout.read().decode("utf-8", "replace")
            except Exception:
                out = ""
        if mode != "exec" and len(out.strip()) < 20:  # viele Switches kennen nur eine interaktive Shell
            try:
                ch = c.invoke_shell(width=250, height=1000)
            except paramiko.SSHException as ex:
                raise SSHError(f"Gerät hat keine Konfiguration geliefert (Befehl prüfen): {ex}")
            ch.settimeout(2)
            buf, last = "", time.time()

            def read():
                nonlocal buf, last
                try:
                    while ch.recv_ready():
                        buf += ch.recv(65535).decode("utf-8", "replace")
                        last = time.time()
                except Exception:
                    pass

            time.sleep(1)
            read()
            buf = ""
            ch.send(command + "\n")
            end = time.time() + 60
            while time.time() < end:
                time.sleep(0.3)
                before = len(buf)
                read()
                if MORE.search(buf[before - 20 if before > 20 else 0:]):
                    ch.send(" ")
                    continue
                if time.time() - last > 2.5 and buf.strip():
                    break
            ch.close()
            out = buf
        out = _clean(out, command)
        if len(out.strip()) < 20:
            raise SSHError("Gerät hat keine Konfiguration geliefert (Befehl prüfen)")
        return out, fp
    finally:
        c.close()
