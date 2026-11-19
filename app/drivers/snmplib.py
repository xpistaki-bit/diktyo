"""Kleiner SNMPv2c-Client (nur lesen): GET und GETBULK-Walk über UDP, BER-Kodierung ohne Fremdbibliothek."""
import random
import socket

# ------------------------------------------------------------ BER
INT, OCTETS, NULL, OID, SEQ = 0x02, 0x04, 0x05, 0x06, 0x30
IPADDR, COUNTER32, GAUGE32, TIMETICKS, OPAQUE, COUNTER64 = 0x40, 0x41, 0x42, 0x43, 0x44, 0x46
NOSUCHOBJECT, NOSUCHINSTANCE, ENDOFMIB = 0x80, 0x81, 0x82
GET, GETNEXT, RESPONSE, GETBULK = 0xA0, 0xA1, 0xA2, 0xA5


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


def _message(community, pdu_type, oids, req_id, non_rep=0, max_rep=0):
    vbs = b"".join(_tlv(SEQ, _oid(o) + _tlv(NULL, b"")) for o in oids)
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
                                raise SNMPError(f"SNMP-Fehler {err}")
                            return vbs
                except socket.timeout:
                    continue
            raise SNMPError("Keine Antwort (Adresse, Community oder SNMP am Gerät prüfen)")
        finally:
            s.close()

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
