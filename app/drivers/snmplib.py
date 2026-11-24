"""Kleiner SNMPv2c-Client (nur lesen): GET und GETBULK-Walk über UDP, BER-Kodierung ohne Fremdbibliothek."""
import random
import socket

# ------------------------------------------------------------ BER
INT, OCTETS, NULL, OID, SEQ = 0x02, 0x04, 0x05, 0x06, 0x30
IPADDR, COUNTER32, GAUGE32, TIMETICKS, OPAQUE, COUNTER64 = 0x40, 0x41, 0x42, 0x43, 0x44, 0x46
NOSUCHOBJECT, NOSUCHINSTANCE, ENDOFMIB = 0x80, 0x81, 0x82
GET, GETNEXT, RESPONSE, GETBULK, SET = 0xA0, 0xA1, 0xA2, 0xA5, 0xA3
SET_ERRORS = {4: "Wert nicht schreibbar (readOnly)", 6: "Kein Schreibzugriff (noAccess) – SNMP-Benutzer bzw. Community braucht Schreibrechte",
              7: "falscher Datentyp", 10: "ungültiger Wert", 16: "Kein Schreibzugriff (authorizationError) – SNMP-Benutzer bzw. Community braucht Schreibrechte",
              17: "Objekt nicht schreibbar (notWritable)", 2: "Objekt unbekannt (noSuchName)", 11: "Objekt nicht vorhanden (noCreation)"}


class SNMPError(Exception):
    pass


def _len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag, body):
    return bytes([tag]) + _len(len(body)) + body


def _int(v):
    return _tlv(INT, v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big", signed=True))


def _oid(s):
    parts = [int(x) for x in s.strip(".").split(".")]
    body = bytes([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        enc = [p & 0x7F]
        p >>= 7
        while p:
            enc.insert(0, 0x80 | (p & 0x7F))
            p >>= 7
        body += bytes(enc)
    return _tlv(OID, body)


def _read(data, i):
    tag = data[i]
    n = data[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(data[i:i + k], "big")
        i += k
    return tag, data[i:i + n], i + n


def _decode_oid(b):
    out = [b[0] // 40, b[0] % 40]
    v = 0
    for x in b[1:]:
        v = (v << 7) | (x & 0x7F)
        if not x & 0x80:
            out.append(v)
            v = 0
    return ".".join(map(str, out))


def _value(tag, b):
    if tag == INT:
        return int.from_bytes(b, "big", signed=True)
    if tag in (COUNTER32, GAUGE32, TIMETICKS, COUNTER64):
        return int.from_bytes(b, "big") if b else 0
    if tag == OCTETS or tag == OPAQUE:
        return bytes(b)
    if tag == OID:
        return _decode_oid(b)
    if tag == IPADDR:
        return ".".join(str(x) for x in b)
    if tag in (NULL, NOSUCHOBJECT, NOSUCHINSTANCE, ENDOFMIB):
        return None
    return bytes(b)


def _varbinds(oids, values=None):
    """Varbinds; values (gleich lang wie oids) für SET als INTEGER, sonst NULL."""
    return b"".join(_tlv(SEQ, _oid(o) + (_int(values[n]) if values else _tlv(NULL, b""))) for n, o in enumerate(oids))


def _message(community, pdu_type, oids, req_id, non_rep=0, max_rep=0, values=None):
    vbs = _varbinds(oids, values)
    pdu = _tlv(pdu_type, _int(req_id) + _int(non_rep) + _int(max_rep) + _tlv(SEQ, vbs))
    return _tlv(SEQ, _int(1) + _tlv(OCTETS, community.encode()) + pdu)


def _parse(data):
    _, msg, _ = _read(data, 0)
    i = 0
    _, _, i = _read(msg, i)  # Version
    _, _, i = _read(msg, i)  # Community
    tag, pdu, _ = _read(msg, i)
    j = 0
    _, rid, j = _read(pdu, j)
    _, err, j = _read(pdu, j)
    _, _, j = _read(pdu, j)
    _, vbl, _ = _read(pdu, j)
    out, k = [], 0
    while k < len(vbl):
        _, vb, k = _read(vbl, k)
        _, ob, m = _read(vb, 0)
        vtag, vval, _ = _read(vb, m)
        out.append((_decode_oid(ob), vtag, _value(vtag, vval)))
    return int.from_bytes(rid, "big", signed=True), int.from_bytes(err, "big", signed=True), out


# ------------------------------------------------------------ Client
class Client:
    def __init__(self, host, community="public", port=161, timeout=2.0, retries=1):
        self.host, self.community, self.port, self.timeout, self.retries = host, community, port, timeout, retries

    def _request(self, pdu_type, oids, **kw):
        rid = random.randint(1, 2 ** 31 - 1)
        msg = _message(self.community, pdu_type, oids, rid, **kw)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(self.timeout)
        try:
            for _ in range(self.retries + 1):
                s.sendto(msg, (self.host, self.port))
                try:
                    while True:
                        data, _ = s.recvfrom(65535)
                        r_id, err, vbs = _parse(data)
                        if r_id == rid:
                            if err:
                                raise SNMPError(SET_ERRORS.get(err, f"SNMP-Fehler {err}") if pdu_type == SET else f"SNMP-Fehler {err}")
                            return vbs
                except socket.timeout:
                    continue
            raise SNMPError("Keine Antwort (Adresse, Community oder SNMP am Gerät prüfen)")
        finally:
            s.close()

    def set_int(self, oid, value):
        """Einen INTEGER-Wert schreiben (z. B. ifAdminStatus)."""
        return self._request(SET, [oid], values=[value])

    def get(self, *oids):
        return {o: v for o, t, v in self._request(GET, list(oids)) if t not in (NOSUCHOBJECT, NOSUCHINSTANCE, ENDOFMIB)}

    def walk(self, base, max_rep=25, limit=20000):
        """GETBULK-Walk unter einem Teilbaum -> {oid: wert}"""
        out, cur, base_p = {}, base, base.strip(".") + "."
        while len(out) < limit:
            vbs = self._request(GETBULK, [cur], non_rep=0, max_rep=max_rep)
            done = False
            for o, t, v in vbs:
                if t == ENDOFMIB or not o.startswith(base_p):
                    done = True
                    break
                out[o] = v
                cur = o
            if done or not vbs:
                break
        return out


def text(v):
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8").strip("\x00").strip()
        except UnicodeDecodeError:
            return v.hex()
    return "" if v is None else str(v)


def mac(v):
    if isinstance(v, bytes) and len(v) == 6:
        return ":".join(f"{x:02X}" for x in v)
    return ""


# ------------------------------------------------------------ SNMPv3 (USM, RFC 3414 / 3826 / 7860)
import hashlib  # noqa: E402
import hmac  # noqa: E402
import os  # noqa: E402

AUTH = {  # Name -> (Hash, Länge des Prüfcodes)
    "MD5": (hashlib.md5, 12), "SHA": (hashlib.sha1, 12), "SHA-256": (hashlib.sha256, 24),
}
REPORTS = {
    "1.3.6.1.6.3.15.1.1.1.0": "Sicherheitsstufe wird vom Gerät nicht unterstützt (z. B. ohne Verschlüsselung angefragt)",
    "1.3.6.1.6.3.15.1.1.3.0": "Benutzer am Gerät unbekannt",
    "1.3.6.1.6.3.15.1.1.5.0": "Authentifizierung fehlgeschlagen (Passwort oder Verfahren falsch)",
    "1.3.6.1.6.3.15.1.1.6.0": "Entschlüsselung fehlgeschlagen (Privacy-Passwort oder Verfahren falsch)",
}
NOT_IN_TIME = "1.3.6.1.6.3.15.1.1.2.0"
UNKNOWN_ENGINE = "1.3.6.1.6.3.15.1.1.4.0"


def localize_key(password, engine_id, proto="SHA"):
    """Passwort -> lokalisierter Schlüssel (RFC 3414 A.2)."""
    hf = AUTH[proto][0]
    pw = password.encode()
    if not pw:
        raise SNMPError("Passwort fehlt")
    h = hf()
    count, i = 0, 0
    buf = (pw * (64 // len(pw) + 2))
    while count < 1048576:
        chunk = buf[i:i + 64]
        if len(chunk) < 64:
            i = 0
            chunk = buf[:64]
        h.update(chunk)
        i = (i + 64) % len(pw)
        count += 64
    ku = h.digest()
    return hf(ku + engine_id + ku).digest()


def _aes_cfb(key, iv, data, encrypt):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    try:  # ab cryptography 45 unter „decrepit“, im alten Pfad entfällt CFB mit Version 49
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.modes import CFB
    c = Cipher(algorithms.AES(key), CFB(iv))
    op = c.encryptor() if encrypt else c.decryptor()
    return op.update(data) + op.finalize()


class ClientV3(Client):
    """SNMPv3 mit Benutzer, Authentifizierung (MD5/SHA/SHA-256) und optional AES-128-Verschlüsselung."""

    def __init__(self, host, user, auth_proto="SHA", auth_pass="", priv_proto="AES", priv_pass="", port=161, timeout=2.0, retries=1):
        super().__init__(host, "", port, timeout, retries)
        if auth_proto and auth_proto not in AUTH:
            raise SNMPError(f"Unbekanntes Authentifizierungsverfahren: {auth_proto}")
        self.user, self.auth_proto, self.auth_pass = user, auth_proto if auth_pass else "", auth_pass
        self.priv_proto, self.priv_pass = (priv_proto if priv_pass and priv_proto else ""), priv_pass
        if self.priv_proto and self.priv_proto != "AES":
            raise SNMPError("Unterstützt wird die Verschlüsselung AES (AES-128)")
        if self.priv_proto and not self.auth_proto:
            raise SNMPError("Verschlüsselung setzt Authentifizierung voraus")
        self.engine_id, self.boots, self.time, self.t0 = b"", 0, 0, 0
        self.k_auth = self.k_priv = None

    # --- Aufbau
    def _flags(self, reportable=True):
        return (0x01 if self.auth_proto else 0) | (0x02 if self.priv_proto else 0) | (0x04 if reportable else 0)

    def _usm(self, auth_params, priv_params, engine_id=None, boots=None, etime=None, user=None):
        e = self.engine_id if engine_id is None else engine_id
        return _tlv(SEQ, _tlv(OCTETS, e) + _int(self.boots if boots is None else boots) + _int(self._etime() if etime is None else etime)
                    + _tlv(OCTETS, (self.user if user is None else user).encode()) + _tlv(OCTETS, auth_params) + _tlv(OCTETS, priv_params))

    def _etime(self):
        import time as _t
        return self.time + int(_t.time() - self.t0) if self.t0 else 0

    def _build(self, pdu, msg_id, discovery=False):
        scoped = _tlv(SEQ, _tlv(OCTETS, self.engine_id) + _tlv(OCTETS, b"") + pdu)
        if discovery:
            glob = _tlv(SEQ, _int(msg_id) + _int(65507) + _tlv(OCTETS, bytes([0x04])) + _int(3))
            usm = _tlv(SEQ, _tlv(OCTETS, b"") + _int(0) + _int(0) + _tlv(OCTETS, b"") + _tlv(OCTETS, b"") + _tlv(OCTETS, b""))
            return _tlv(SEQ, _int(3) + glob + _tlv(OCTETS, usm) + _tlv(SEQ, _tlv(OCTETS, b"") + _tlv(OCTETS, b"") + pdu))
        glob = _tlv(SEQ, _int(msg_id) + _int(65507) + _tlv(OCTETS, bytes([self._flags()])) + _int(3))
        priv_params, data = b"", scoped
        boots, etime = self.boots, self._etime()
        if self.priv_proto:
            salt = os.urandom(8)
            iv = boots.to_bytes(4, "big") + etime.to_bytes(4, "big") + salt
            data, priv_params = _tlv(OCTETS, _aes_cfb(self.k_priv[:16], iv, scoped, True)), salt
        alen = AUTH[self.auth_proto][1] if self.auth_proto else 0
        msg = _tlv(SEQ, _int(3) + glob + _tlv(OCTETS, self._usm(b"\0" * alen, priv_params, boots=boots, etime=etime)) + data)
        if self.auth_proto:
            mac = hmac.new(self.k_auth, msg, AUTH[self.auth_proto][0]).digest()[:alen]
            marker = _tlv(OCTETS, self.user.encode()) + _tlv(OCTETS, b"\0" * alen)  # Benutzer + Platzhalter des Prüfcodes
            pos = msg.index(marker) + len(marker) - alen
            msg = msg[:pos] + mac + msg[pos + alen:]
        return msg

    # --- Zerlegen
    def _open(self, data):
        _, msg, _ = _read(data, 0)
        i = 0
        _, _, i = _read(msg, i)                # Version
        _, glob, i = _read(msg, i)             # msgGlobalData
        j = 0
        _, mid, j = _read(glob, j)
        _, _, j = _read(glob, j)
        _, flags, j = _read(glob, j)
        _, usm_raw, i = _read(msg, i)
        _, usm, _ = _read(usm_raw, 0)
        k = 0
        _, eid, k = _read(usm, k)
        _, boots, k = _read(usm, k)
        _, etime, k = _read(usm, k)
        _, _, k = _read(usm, k)
        _, _, k = _read(usm, k)
        _, privp, k = _read(usm, k)
        tag, body, _ = _read(msg, i)
        boots, etime = int.from_bytes(boots, "big"), int.from_bytes(etime, "big")
        if tag == OCTETS:                      # verschlüsselt
            if not self.k_priv:
                raise SNMPError("Antwort ist verschlüsselt, aber kein Privacy-Passwort angegeben")
            iv = boots.to_bytes(4, "big") + etime.to_bytes(4, "big") + bytes(privp)
            plain = _aes_cfb(self.k_priv[:16], iv, bytes(body), False)
            _, body, _ = _read(plain, 0)
        m = 0
        _, _, m = _read(body, m)               # contextEngineID
        _, _, m = _read(body, m)               # contextName
        ptype, pdu, _ = _read(body, m)
        n = 0
        _, rid, n = _read(pdu, n)
        _, err, n = _read(pdu, n)
        _, _, n = _read(pdu, n)
        _, vbl, _ = _read(pdu, n)
        vbs, q = [], 0
        while q < len(vbl):
            _, vb, q = _read(vbl, q)
            _, ob, r = _read(vb, 0)
            vtag, vval, _ = _read(vb, r)
            vbs.append((_decode_oid(ob), vtag, _value(vtag, vval)))
        return dict(msg_id=int.from_bytes(mid, "big"), engine_id=bytes(eid), boots=boots, time=etime, ptype=ptype,
                    rid=int.from_bytes(rid, "big", signed=True), err=int.from_bytes(err, "big", signed=True), vbs=vbs)

    def _send(self, msg, match):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(self.timeout)
        try:
            for _ in range(self.retries + 1):
                s.sendto(msg, (self.host, self.port))
                try:
                    while True:
                        data, _ = s.recvfrom(65535)
                        r = self._open(data)
                        if r["msg_id"] == match:
                            return r
                except socket.timeout:
                    continue
            raise SNMPError("Keine Antwort (Adresse, Benutzer oder SNMP am Gerät prüfen)")
        finally:
            s.close()

    def _discover(self):
        import time as _t
        mid = random.randint(1, 2 ** 31 - 1)
        pdu = _tlv(GET, _int(mid) + _int(0) + _int(0) + _tlv(SEQ, b""))
        r = self._send(self._build(pdu, mid, discovery=True), mid)
        if not r["engine_id"]:
            raise SNMPError("Gerät hat keine Engine-ID gemeldet")
        self.engine_id, self.boots, self.time, self.t0 = r["engine_id"], r["boots"], r["time"], _t.time()
        if self.auth_proto:
            self.k_auth = localize_key(self.auth_pass, self.engine_id, self.auth_proto)
        if self.priv_proto:
            # AES-128 nutzt den mit dem Authentifizierungs-Hash lokalisierten Privacy-Schlüssel (die ersten 16 Byte)
            self.k_priv = localize_key(self.priv_pass, self.engine_id, self.auth_proto)

    def _request(self, pdu_type, oids, non_rep=0, max_rep=0, _retry=True, values=None):
        import time as _t
        if not self.engine_id:
            self._discover()
        rid = mid = random.randint(1, 2 ** 31 - 1)
        vbs = _varbinds(oids, values)
        pdu = _tlv(pdu_type, _int(rid) + _int(non_rep) + _int(max_rep) + _tlv(SEQ, vbs))
        r = self._send(self._build(pdu, mid), mid)
        if r["ptype"] == 0xA8:  # Report
            oid = r["vbs"][0][0] if r["vbs"] else ""
            if oid in (NOT_IN_TIME, UNKNOWN_ENGINE) and _retry:
                self.boots, self.time, self.t0 = r["boots"], r["time"], _t.time()
                if oid == UNKNOWN_ENGINE:
                    self.engine_id = b""
                return self._request(pdu_type, oids, non_rep, max_rep, _retry=False, values=values)
            raise SNMPError(REPORTS.get(oid, f"SNMP-Report {oid}"))
        if r["err"]:
            raise SNMPError(SET_ERRORS.get(r["err"], f"SNMP-Fehler {r['err']}") if pdu_type == SET else f"SNMP-Fehler {r['err']}")
        return r["vbs"]
