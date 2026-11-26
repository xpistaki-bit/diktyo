"""ASUS: Einstellungsdatei (CFG) entschlüsseln (HDR1/HDR2), maskiert vergleichen, unverändert trotz neuer Zufallsbytes;
Gastnetze lesen und schalten, Neustart (applyapp.cgi, Sitzung erneuern), kein Schalten bei „Gastnetz Pro“ (SDN)."""
import json
import random

import httpx

from app import actions, configbackup, integrations
from app.db import db, now
from app.drivers import asuswrt
from tests.test_m6 import H, login

NV = {"productid": "EBM68", "lan_ipaddr": "192.168.50.1", "http_passwd": "geheim-admin", "wl0_ssid": "Zuhause", "wl0_wpa_psk": "wlan-schluessel-1",
      "wl0.1_ssid": "Gast", "wl0.1_bss_enabled": "0", "time_zone": "MEZ-1DST"}


def enc_hdr2(d, rnd=None):
    """Wie nvram save der Firmware: Werte „k=v\\0…“, 0 -> 0xFD..0xFF, sonst 0xFF − b + r."""
    rnd = random.randint(0, 29) if rnd is None else rnd
    body = b"".join(f"{k}={v}".encode() + b"\0" for k, v in d.items())
    body += b"\0" * ((4 - len(body) % 4) % 4)
    out = bytes((0xFD + random.randint(0, 2)) if b == 0 else ((0xFF - b + rnd) & 0xFF) for b in body)
    return b"HDR2" + len(out).to_bytes(3, "little") + bytes([rnd]) + out


def enc_hdr1(d):
    body = b"".join(f"{k}={v}".encode() + b"\0" for k, v in d.items())
    return b"HDR1" + len(body).to_bytes(4, "little") + body


def test_decode_mask_canonical():
    for rnd in (0, 7, 29):
        assert asuswrt.decode_cfg(enc_hdr2(NV, rnd)) == NV
    assert asuswrt.decode_cfg(enc_hdr1(NV)) == NV
    assert asuswrt.decode_cfg(b"<html>login</html>") is None and asuswrt.decode_cfg(b"HDR2\x05\x00\x00\x01xx") is None
    txt = asuswrt.config_text(enc_hdr2(NV))
    lines = txt.splitlines()
    assert lines == sorted(lines) and "wl0_ssid=Zuhause" in lines and "time_zone=MEZ-1DST" in lines
    assert "geheim-admin" not in txt and "wlan-schluessel-1" not in txt
    assert any(x.startswith("http_passwd=•••••• (#") for x in lines) and any(x.startswith("wl0_wpa_psk=•••••• (#") for x in lines)
    # gleiche Einstellungen, andere Zufallsbytes -> gleicher Vergleichswert
    a, b = enc_hdr2(NV, 3), enc_hdr2(NV, 21)
    assert a != b and asuswrt.canonical(a) == asuswrt.canonical(b)


def test_backup_unchanged_diff_and_text(monkeypatch):
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "ASUS-CFG"}, headers=H).json()["profile"]["id"]
    P = f"/api/profiles/{pid}"
    did = cl.post(f"{P}/devices", json=dict(name="EBM68", type="mesh"), headers=H).json()["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, device_id, created) VALUES(?, 'asuswrt', 'ASUS', '192.0.2.1', ?, ?)",
                        (pid, did, now())).lastrowid
    cur = dict(NV)
    monkeypatch.setattr(asuswrt, "backup", lambda conf, state: ("Settings_EBM68.CFG", enc_hdr2(cur), False))
    assert configbackup.run(iid, interactive=True)["status"] == "new"
    assert configbackup.run(iid, interactive=True)["status"] == "unchanged"  # neue Zufallsbytes, gleicher Inhalt
    cur.update({"wl0_wpa_psk": "neuer-schluessel", "time_zone": "UTC0"})
    assert configbackup.run(iid, interactive=True)["status"] == "new"
    cfgs = cl.get(f"{P}/configs?device_id={did}").json()["configs"]
    assert cfgs[0]["readable"] and not cfgs[0]["is_text"] and cfgs[0]["prev_id"] == cfgs[1]["id"]
    d = cl.get(f"{P}/configs/{cfgs[0]['id']}/diff?other={cfgs[0]['prev_id']}").json()
    body = "\n".join(d["lines"])
    assert "-time_zone=MEZ-1DST" in body and "+time_zone=UTC0" in body and d["changed"] == 4
    assert "neuer-schluessel" not in body and "wlan-schluessel-1" not in body and "+wl0_wpa_psk=•••••• (#" in body
    r = cl.get(f"{P}/configs/{cfgs[0]['id']}/download?text=1")
    assert r.status_code == 200 and "Settings_EBM68" in r.headers["content-disposition"] and ".txt" in r.headers["content-disposition"]
    assert "time_zone=UTC0" in r.text and "geheim-admin" not in r.text
    raw = cl.get(f"{P}/configs/{cfgs[0]['id']}/download")
    assert raw.content[:4] == b"HDR2"  # Original bleibt zum Wiederherstellen


R = {"logins": 0, "applied": [], "expire_next": False, "sdn": ""}


def handler(req):
    p = req.url.path
    if p == "/login.cgi":
        R["logins"] += 1
        return httpx.Response(200, json={"asus_token": f"TOK{R['logins']}"})
    tok = req.headers.get("cookie", "")
    if p == "/appGet.cgi":
        data = {"productid": "EBM68", "firmver": "3.0.0.6", "buildno": "102", "lan_ipaddr": "192.168.50.1", "label_mac": "AA:00:00:00:00:01",
                "get_clientlist": {"maclist": []}, "get_cfg_clientlist": [],
                "wl0.1_ssid": "Gast", "wl0.1_bss_enabled": "0", "wl1.1_ssid": "Gast-5G", "wl1.1_bss_enabled": "1", "wl0.2_ssid": "", "wl0.2_bss_enabled": "0",
                "sdn_rl": R["sdn"]}
        return httpx.Response(200, text=json.dumps(data))
    if p == "/applyapp.cgi":
        if R["expire_next"]:
            R["expire_next"] = False
            return httpx.Response(200, text="<script>top.location.href='/Main_Login.asp';</script>")
        R["applied"].append((tok, dict(httpx.QueryParams(req.content.decode()))))
        return httpx.Response(200, text='{"modify":"1","run_service":"restart_wireless"}')
    return httpx.Response(404, text="")


def mock(monkeypatch):
    real = asuswrt._client
    monkeypatch.setattr(asuswrt, "_client", lambda conf: httpx.Client(base_url=real(conf).base_url, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(asuswrt, "traffic_analyzer", lambda conf, token, now=None: None)


def test_guest_and_reboot_actions(monkeypatch):
    mock(monkeypatch)
    R.update(logins=0, applied=[], sdn="<1>Default>1>0")
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "ASUS-Aktionen"}, headers=H).json()["profile"]["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, port, created) VALUES(?, 'asuswrt', 'ASUS', '192.0.2.1', 8443, ?)",
                        (pid, now())).lastrowid
    s = integrations.poll(iid)
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
        assert st["result"]["guest"] == [dict(unit=0, idx=1, band="2,4 GHz", ssid="Gast", enabled=False),
                                         dict(unit=1, idx=1, band="5 GHz", ssid="Gast-5G", enabled=True)] and st["result"]["sdn"] is False
        acts = {a["label"]: a for a in actions.available(c, pid, s["device_id"])}
    assert set(acts) >= {"Gastnetz „Gast“ (2,4 GHz) einschalten", "Gastnetz „Gast-5G“ (5 GHz) ausschalten", "ASUS-Router neu starten"}
    assert acts["Gastnetz „Gast-5G“ (5 GHz) ausschalten"]["danger"] and acts["Gastnetz „Gast-5G“ (5 GHz) ausschalten"]["undo"]
    R["expire_next"] = True  # Sitzung abgelaufen: díktyo meldet sich einmal neu an
    before = R["logins"]
    r = actions.run(pid, 1, s["device_id"], acts["Gastnetz „Gast“ (2,4 GHz) einschalten"]["key"])
    assert r["status"] == "done" and R["logins"] == before + 1
    assert R["applied"][-1][1] == {"wl0.1_bss_enabled": "1", "action_mode": "apply", "rc_service": "restart_wireless"}
    actions.run(pid, 1, s["device_id"], acts["ASUS-Router neu starten"]["key"])
    assert R["applied"][-1][1] == {"action_mode": "apply", "rc_service": "reboot"}
    try:
        asuswrt.action(dict(host="192.0.2.1"), {}, "guest", dict(unit=9, idx=1, on=True))
        raise AssertionError
    except asuswrt.DriverError:
        pass
    # „Gastnetz Pro“ (SDN): Gastnetze werden angezeigt, aber nicht geschaltet
    R["sdn"] = "<1>Default>1>0<2>Gast>1>52"
    integrations.poll(iid)
    with db() as c:
        labels = [a["label"] for a in actions.available(c, pid, s["device_id"])]
    assert "ASUS-Router neu starten" in labels and not any(x.startswith("Gastnetz") for x in labels)
