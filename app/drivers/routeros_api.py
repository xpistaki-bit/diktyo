"""Client für die RouterOS-API (Dienst „api“, Port 8728, bzw. „api-ssl“, Port 8729) – RouterOS 6 und 7.

Das Protokoll: Sätze aus Wörtern mit Längenpräfix; Antworten !re (Datensatz), !done (fertig), !trap (Fehler),
!fatal (Verbindung beendet). Anmeldung nach dem Verfahren ab RouterOS 6.43 (/login mit Name und Passwort), bei älteren
Versionen mit Challenge-Response (MD5). Menüpfade und Feldnamen sind dieselben wie bei der REST-API – die REST-API von
RouterOS 7 ist nur eine Hülle um diese API –, daher liefert request() dieselben Daten wie die REST-Anfragen.
"""
import binascii
import hashlib
import socket
import ssl

# Menüs, die genau einen Datensatz liefern (REST antwortet mit einem Objekt statt einer Liste)
SINGLE = {"system/resource", "system/identity", "system/routerboard", "system/package/update", "system/clock", "system/health"}


class APIError(Exception):
    pass


class NoSuchCommand(APIError):
    pass


def _enc_len(n):
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return (n | 0x8000).to_bytes(2, "big")
    if n < 0x200000:
        return (n | 0xC00000).to_bytes(3, "big")
    if n < 0x10000000:
        return (n | 0xE0000000).to_bytes(4, "big")
    return b"\xF0" + n.to_bytes(4, "big")


class Client:
    def __init__(self, host, port=8728, user="admin", password="", use_ssl=False, timeout=15):
        try:
            raw = socket.create_connection((host, port), timeout=timeout)
        except OSError as ex:
            raise APIError(f"connect:{ex}")
        if use_ssl:
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # RouterOS nutzt meist ein selbst signiertes Zertifikat
            try:
                raw = ctx.wrap_socket(raw, server_hostname=host)
            except (ssl.SSLError, OSError) as ex:
                raw.close()
                raise APIError(f"tls:{ex}")
        self.sock = raw
        self.sock.settimeout(timeout)
        self._login(user, password)

    # -------------------------------------------------- Protokoll
    def _send(self, words):
        data = b"".join(_enc_len(len(w.encode())) + w.encode() for w in words) + b"\x00"
        try:
            self.sock.sendall(data)
        except OSError as ex:
            raise APIError(f"io:{ex}")

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except OSError as ex:
                raise APIError(f"io:{ex}")
            if not chunk:
                raise APIError("io:connection closed")
            buf += chunk
        return buf

    def _read_len(self):
        b = self._recv_exact(1)[0]
        if b < 0x80:
            return b
        if b < 0xC0:
            return ((b & 0x3F) << 8) + self._recv_exact(1)[0]
        if b < 0xE0:
            return ((b & 0x1F) << 16) + int.from_bytes(self._recv_exact(2), "big")
        if b < 0xF0:
            return ((b & 0x0F) << 24) + int.from_bytes(self._recv_exact(3), "big")
        return int.from_bytes(self._recv_exact(4), "big")

    def _read_sentence(self):
        words = []
        while True:
            n = self._read_len()
            if n == 0:
                return words
            words.append(self._recv_exact(n).decode("utf-8", errors="replace"))

    def talk(self, words):
        """-> Liste der Datensätze (!re) als dict; Fehler als APIError."""
        self._send(words)
        out, err = [], None
        while True:
            s = self._read_sentence()
            if not s:
                continue
            kind, attrs = s[0], {}
            for w in s[1:]:
                if w.startswith("="):
                    k, _, v = w[1:].partition("=")
                    attrs[k] = v
            if kind == "!re":
                out.append(attrs)
            elif kind == "!trap":
                err = attrs.get("message", "error")
            elif kind == "!fatal":
                raise APIError("fatal:" + (s[1] if len(s) > 1 else ""))
            elif kind == "!done":
                if err is not None:
                    if "no such command" in err or "unknown parameter" in err:
                        raise NoSuchCommand(err)
                    raise APIError("trap:" + err)
                if "ret" in attrs and not out:
                    out.append({"ret": attrs["ret"]})
                return out

    def _login(self, user, password):
        try:
            r = self.talk(["/login", f"=name={user}", f"=password={password}"])
        except APIError as ex:
            if "invalid user name or password" in str(ex) or "cannot log in" in str(ex):
                raise APIError("auth:" + str(ex))
            raise
        if r and r[0].get("ret"):  # RouterOS vor 6.43: Challenge-Response
            chal = binascii.unhexlify(r[0]["ret"])
            resp = "00" + hashlib.md5(b"\x00" + password.encode() + chal).hexdigest()
            try:
                self.talk(["/login", f"=name={user}", f"=response={resp}"])
            except APIError as ex:
                raise APIError("auth:" + str(ex))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # -------------------------------------------------- wie die REST-API
    def request(self, method, path, json=None):
        path = path.strip("/")
        body = {k: ("true" if v is True else "false" if v is False else str(v)) for k, v in (json or {}).items()}
        if method == "GET":
            rows = self.talk([f"/{path}/print"])
            return (rows[0] if rows else {}) if path in SINGLE else rows
        if method == "PATCH":  # menu/<id> ändern
            menu, _, oid = path.rpartition("/")
            self.talk([f"/{menu}/set", f"=.id={oid}"] + [f"={k}={v}" for k, v in body.items()])
            return {}
        if method == "POST":  # Befehl im Menü
            rows = self.talk([f"/{path}"] + [f"={k}={v}" for k, v in body.items()])
            return rows
        raise APIError(f"method:{method}")
