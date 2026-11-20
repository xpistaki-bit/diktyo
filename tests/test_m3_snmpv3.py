"""SNMPv3: Schlüssel nach RFC 3414, Austausch mit einem simulierten v3-Agenten (Discovery, SHA/AES, Fehler), Speichern über die API."""
import hmac
import socket
import threading
import time

from fastapi.testclient import TestClient

from app import integrations, main, users
from app.db import db
from app.drivers import snmp, snmplib as s

H = {"X-Requested-With": "diktyo"}
ENGINE = bytes.fromhex("80001f8804746573746167656e74")
TREE = {snmp.SYS["descr"]: b"XGS1935-28", snmp.SYS["name"]: b"XGS1935", snmp.SYS["object_id"]: b"x", snmp.SYS["uptime"]: (s.TIMETICKS, 500),
        snmp.SYS["location"]: b"", f"{snmp.IF_TYPE}.1": 6, f"{snmp.IF_OPER}.1": 1, f"{snmp.IF_NAME}.1": b"Port1"}


def _val(v):
    if isinstance(v, tuple):
        return s._tlv(v[0], v[1].to_bytes(max(1, (v[1].bit_length() + 7) // 8), "big"))
    return s._int(v) if isinstance(v, int) else s._tlv(s.OCTETS, v)


def _k(o):
    return [int(x) for x in o.split(".")]


class AgentV3(threading.Thread):
    def __init__(self, user="monitor", auth="auth-pass-1", priv="priv-pass-2"):
        super().__init__(daemon=True)
        self.user = user
        self.srv = s.ClientV3("127.0.0.1", user, "SHA", auth, "AES", priv)
        self.srv.engine_id, self.srv.boots, self.srv.time, self.srv.t0 = ENGINE, 7, 100, time.time()
        self.srv.k_auth = s.localize_key(auth, ENGINE, "SHA")
        self.srv.k_priv = s.localize_key(priv, ENGINE, "SHA")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]

    def _report(self, msg_id, oid):
        glob = s._tlv(s.SEQ, s._int(msg_id) + s._int(65507) + s._tlv(s.OCTETS, b"\0") + s._int(3))
        usm = s._tlv(s.SEQ, s._tlv(s.OCTETS, ENGINE) + s._int(self.srv.boots) + s._int(self.srv._etime()) + s._tlv(s.OCTETS, b"")
                     + s._tlv(s.OCTETS, b"") + s._tlv(s.OCTETS, b""))
        pdu = s._tlv(0xA8, s._int(0) + s._int(0) + s._int(0) + s._tlv(s.SEQ, s._tlv(s.SEQ, s._oid(oid) + s._tlv(s.COUNTER32, b"\1"))))
        return s._tlv(s.SEQ, s._int(3) + glob + s._tlv(s.OCTETS, usm) + s._tlv(s.SEQ, s._tlv(s.OCTETS, ENGINE) + s._tlv(s.OCTETS, b"") + pdu))

    def run(self):
        while True:
            data, addr = self.sock.recvfrom(65535)
            # USM-Parameter lesen
            _, msg, _ = s._read(data, 0)
            i = 0
            _, _, i = s._read(msg, i)
            _, glob, i = s._read(msg, i)
            _, mid, _ = s._read(glob, 0)
            mid = int.from_bytes(mid, "big")
            _, usm_raw, _ = s._read(msg, i)
            _, usm, _ = s._read(usm_raw, 0)
            k = 0
            _, eid, k = s._read(usm, k)
            for _n in range(2):
                _, _, k = s._read(usm, k)
            _, user, k = s._read(usm, k)
            _, authp, k = s._read(usm, k)
            if not eid:  # Discovery
                self.sock.sendto(self._report(mid, s.UNKNOWN_ENGINE), addr)
                continue
            if bytes(user).decode() != self.user:
                self.sock.sendto(self._report(mid, "1.3.6.1.6.3.15.1.1.3.0"), addr)
                continue
            zeroed = data.replace(bytes(authp), b"\0" * len(authp), 1)
            if hmac.new(self.srv.k_auth, zeroed, s.AUTH["SHA"][0]).digest()[:12] != bytes(authp):
                self.sock.sendto(self._report(mid, "1.3.6.1.6.3.15.1.1.5.0"), addr)
                continue
            r = self.srv._open(data)
            keys = sorted(TREE, key=_k)
            out = []
            if r["ptype"] == s.GET:
                for o, _t, _v in r["vbs"]:
                    out.append(s._tlv(s.SEQ, s._oid(o) + (_val(TREE[o]) if o in TREE else s._tlv(s.NOSUCHOBJECT, b""))))
            else:
                nxt = [x for x in keys if _k(x) > _k(r["vbs"][0][0])][:10]
                out = [s._tlv(s.SEQ, s._oid(x) + _val(TREE[x])) for x in nxt] or [s._tlv(s.SEQ, s._oid(r["vbs"][0][0]) + s._tlv(s.ENDOFMIB, b""))]
            pdu = s._tlv(s.RESPONSE, s._int(r["rid"]) + s._int(0) + s._int(0) + s._tlv(s.SEQ, b"".join(out)))
            self.sock.sendto(self.srv._build(pdu, r["msg_id"]), addr)


def test_key_localization_rfc3414():
    e = bytes.fromhex("000000000000000000000002")
    assert s.localize_key("maplesyrup", e, "MD5").hex() == "526f5eed9fcce26f8964c2930787d82b"
    assert s.localize_key("maplesyrup", e, "SHA").hex() == "6695febc9288e36282235fc7151f128497b38f3f"


def test_v3_exchange_and_errors():
    a = AgentV3()
    a.start()
    conf = dict(host="127.0.0.1", port=a.port, version="v3", username="monitor", auth_proto="SHA", auth_pass="auth-pass-1",
                priv_proto="AES", priv_pass="priv-pass-2")
    assert snmp.test(conf) == {"name": "XGS1935", "descr": "XGS1935-28"}
    res, _, _ = snmp.poll(conf, {})
    assert res["ports"][0]["name"] == "Port1" and res["ports"][0]["oper"] == "up"
    for bad, msg in ((dict(auth_pass="falsch-1234"), "Authentifizierung fehlgeschlagen"), (dict(username="nobody"), "Benutzer am Gerät unbekannt")):
        try:
            snmp.test({**conf, **bad})
            raise AssertionError("muss scheitern")
        except snmp.DriverError as ex:
            assert msg in str(ex), ex
    try:
        snmp.test({**conf, "username": ""})
        raise AssertionError
    except snmp.DriverError as ex:
        assert "Benutzer" in str(ex)


def test_v3_settings_via_api():
    with db() as c:
        if not users.by_email(c, "v3@x.de"):
            users.create(c, "v3@x.de", "passwort123", is_admin=True)
    cl = TestClient(main.app)
    cl.post("/api/auth/login", json={"email": "v3@x.de", "password": "passwort123"}, headers=H)
    pid = cl.post("/api/profiles", json={"name": "v3"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    i = cl.post(f"{P}/integrations", json={"driver": "snmp", "host": "192.168.178.2", "version": "v3", "username": "monitor", "auth_proto": "SHA",
                                           "auth_pass": "a-geheim", "priv_proto": "AES", "priv_pass": "p-geheim"}, headers=H).json()
    assert i["options"] == {"version": "v3", "auth_proto": "SHA", "priv_proto": "AES", "cfg_schedule": "weekly", "ssh_auth": "password", "ssh_mode": "auto"} and set(i["secrets"]) == {"auth_pass", "priv_pass"}
    assert "a-geheim" not in str(i)
    # Platzhalter behält die gespeicherten Passwörter, ein neues ersetzt nur das eine
    cl.put(f"{P}/integrations/{i['id']}", json={"host": "192.168.178.2", "version": "v3", "username": "monitor", "auth_pass": "••••••",
                                                 "priv_pass": "p-neu", "auth_proto": "SHA-256", "priv_proto": "AES"}, headers=H)
    with db() as c:
        row = c.execute("SELECT * FROM integrations WHERE id=?", (i["id"],)).fetchone()
        conf = integrations.conf_of(row)
    assert conf["auth_pass"] == "a-geheim" and conf["priv_pass"] == "p-neu" and conf["auth_proto"] == "SHA-256" and conf["username"] == "monitor"
    # ältere Einträge mit einfachem Passwort werden weiter gelesen
    with db() as c:
        c.execute("UPDATE integrations SET secret=? WHERE id=?", (integrations.security.encrypt("nur-text"), i["id"]))
        assert integrations.conf_of(c.execute("SELECT * FROM integrations WHERE id=?", (i["id"],)).fetchone())["password"] == "nur-text"


def test_snmp_diagnose():
    """Diagnose unterscheidet: Dienst antwortet + Anmeldung falsch / alles ok / Dienst antwortet gar nicht."""
    a = AgentV3()
    a.start()
    conf = dict(host="127.0.0.1", port=a.port, version="v3", username="monitor", auth_proto="SHA", auth_pass="auth-pass-1",
                priv_proto="AES", priv_pass="priv-pass-2")
    ok = snmp.diagnose(conf)
    titles = [x["title"] for x in ok["steps"]]
    assert "SNMP-Dienst antwortet" in titles and ok["steps"][-1]["ok"] is True and ok["summary"] == "SNMP funktioniert."
    bad = snmp.diagnose({**conf, "auth_pass": "falsch-1234"})
    assert bad["steps"][-1]["ok"] is False and "Anmeldung passt nicht" in bad["summary"]
    # niemand antwortet (freier Port) – Absender über Router, Hinweis auf den Router aus dem Bestand
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]
    sock.close()
    none = snmp.diagnose({**conf, "port": free}, ("192.168.178.3", "ASUS EBM68"))
    dead = next(x for x in none["steps"] if x["title"] == "SNMP-Dienst antwortet nicht")
    route = next(x for x in none["steps"] if x["title"].startswith("Netzweg"))
    assert "192.168.178.3 (ASUS EBM68)" in route["detail"] and "192.168.178.3" in dead["detail"] and "192.168.178.3" in none["summary"]
