"""Konfiguration eines Netzwerkgeräts per SSH lesen (paramiko). Host-Schlüssel: beim ersten Mal merken, danach prüfen."""
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


def run(host, port, user, password, command, known=None, timeout=15):
    """-> (Ausgabe, Fingerabdruck des Host-Schlüssels)"""
    try:
        import paramiko
    except ImportError:
        raise SSHError("paramiko ist nicht installiert")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, port=port, username=user, password=password, look_for_keys=False, allow_agent=False, timeout=timeout,
                  banner_timeout=timeout, auth_timeout=timeout)
    except paramiko.AuthenticationException:
        raise SSHError("SSH-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)")
    except (paramiko.SSHException, OSError) as ex:
        raise SSHError(f"SSH-Verbindung fehlgeschlagen: {ex}")
    try:
        key = c.get_transport().get_remote_server_key()
        fp = f"{key.get_name()} {key.fingerprint}" if hasattr(key, "fingerprint") else f"{key.get_name()} {key.get_base64()[:32]}"
        if known and known != fp:
            raise SSHError(f"Host-Schlüssel des Geräts hat sich geändert ({fp}); Backup aus Sicherheitsgründen abgebrochen. "
                           f"Wurde das Gerät ausgetauscht, die Integration einmal neu speichern.")
        out = ""
        try:  # zuerst als einzelner Befehl
            _, stdout, _ = c.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace")
        except Exception:
            out = ""
        if len(out.strip()) < 20:  # viele Switches kennen nur eine interaktive Shell
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
