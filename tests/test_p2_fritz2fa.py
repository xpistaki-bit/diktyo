"""Zweiter Faktor beim FRITZ!Box-Konfigurationsexport (TR-064 X_AVM-DE_Auth), gegen eine nachgebildete FRITZ!Box."""
import json
import re

import httpx

from app import configbackup, integrations
from app.db import db, now
from app.drivers import fritzbox
from tests.test_m6 import H, login


class Svc:
    def __init__(self, t, url):
        self.serviceType, self.controlURL = t, url


class Soaper:
    user, password, address, port = "diktyo", "pw", "http://192.0.2.1", 49000


class FC:
    modelname = "FRITZ!Box 6591 Cable"
    soaper = Soaper()
    services = {"DeviceConfig1": Svc("urn:dslforum-org:service:DeviceConfig:1", "/upnp/control/deviceconfig"),
                "X_AVM-DE_Auth1": Svc("urn:dslforum-org:service:X_AVM-DE_Auth:1", "/upnp/control/x_auth")}


def soap_ok(act, **out):
    body = "".join(f"<{k}>{v}</{k}>" for k, v in out.items())
    return httpx.Response(200, text=f'<s:Envelope xmlns:s="x"><s:Body><u:{act}Response>{body}</u:{act}Response></s:Body></s:Envelope>')


def soap_err(code, desc):
    return httpx.Response(500, text=f"<s:Envelope><s:Body><s:Fault><detail><UPnPError><errorCode>{code}</errorCode>"
                                    f"<errorDescription>{desc}</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>")


class Box:
    """Merkt sich den Ablauf: Export ohne Token -> 866; start -> Token; nach 'Taste' authenticated; Export mit Token -> URL."""
    TOKEN = "2C0A2110-30BA-444e-8B83-566BC3F19C80"

    def __init__(self):
        self.pressed, self.calls = False, []

    def post(self, url, content=None, headers=None, **kw):
        act = headers["SOAPAction"].split("#")[1]
        token = re.search(r'<avm:token xmlns:avm="avm.de" s:mustUnderstand="1">([^<]+)</avm:token>', content.decode())
        token = token.group(1) if token else None
        self.calls.append((act, token))
        if act == "X_AVM-DE_GetConfigFile":
            if token != self.TOKEN or not self.pressed:
                return soap_err(866, "second factor authentication required")
            assert "<NewX_AVM-DE_Password>pw</NewX_AVM-DE_Password>" in content.decode()
            return soap_ok(act, **{"NewX_AVM-DE_ConfigFileUrl": "/tmp/export.cfg"})
        if act == "SetConfig":
            if "<NewAction>start</NewAction>" in content.decode():
                return soap_ok(act, NewToken=self.TOKEN, NewState="waitingforauth", NewMethods="button,dtmf;*11234")
            return soap_ok(act, NewState="stopped")
        if act == "GetState":
            assert token == self.TOKEN
            return soap_ok(act, NewState="authenticated" if self.pressed else "waitingforauth")
        raise AssertionError(act)


def test_fritz_second_factor_flow(monkeypatch):
    box = Box()
    monkeypatch.setattr(fritzbox, "_connect", lambda conf: FC())
    monkeypatch.setattr(fritzbox.httpx, "post", box.post)
    monkeypatch.setattr(fritzbox, "_fetch", lambda fc, url: "**** FRITZ!Box CONFIGURATION EXPORT\nx=1\n")
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "FB-2FA"}, headers=H).json()["profile"]["id"]
    with db() as c:
        iid = c.execute("INSERT INTO integrations(profile_id, driver, name, host, username, secret, options, created) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, "fritzbox", "FRITZ!Box", "192.0.2.1", "diktyo", integrations.security.encrypt(json.dumps({"password": "pw"})),
                         "{}", now())).lastrowid
    P = f"/api/profiles/{pid}/integrations/{iid}"
    # 1. Zeitplan: kann nicht bestätigen -> verständlicher Hinweis, kein Start an der Box
    r = configbackup.run(iid)
    assert r["status"] == "error" and r["second_factor"] and "von Hand" in r["message"]
    assert not any(a == "SetConfig" for a, _ in box.calls)
    # 2. per Knopf: Bestätigung wird gestartet, Hinweise für Taste und Telefon
    r = cl.post(f"{P}/config-backup", headers=H).json()
    assert r == {"status": "second_factor", "state": "waitingforauth", "button": True, "dtmf": "*11234"}
    assert cl.get(f"{P}/second-factor").json()["state"] == "waitingforauth"
    box.pressed = True
    assert cl.get(f"{P}/second-factor").json()["state"] == "authenticated"
    # 3. erneut sichern: Token im SOAP-Header, Export klappt, Token wird verbraucht
    r = cl.post(f"{P}/config-backup", headers=H).json()
    assert r["status"] == "new" and r["filename"].startswith("FRITZBox_6591_Cable_")
    assert box.calls[-1] == ("X_AVM-DE_GetConfigFile", Box.TOKEN)
    with db() as c:
        st = json.loads(c.execute("SELECT state FROM integrations WHERE id=?", (iid,)).fetchone()["state"])
    assert "sf_token" not in st and st["cfg_result"]["status"] == "new"
    # 4. Abbrechen stoppt den Vorgang an der Box
    box.pressed = False
    cl.post(f"{P}/config-backup", headers=H)
    assert cl.delete(f"{P}/second-factor", headers=H).json()["state"] == "stopped"
    assert box.calls[-1] == ("SetConfig", Box.TOKEN)


def test_fritz_second_factor_blocked(monkeypatch):
    monkeypatch.setattr(fritzbox, "_connect", lambda conf: FC())
    monkeypatch.setattr(fritzbox.httpx, "post", lambda *a, **k: soap_err(867, "second factor authentication blocked"))
    try:
        fritzbox.backup(dict(host="h", password="pw"), {})
        raise AssertionError
    except fritzbox.DriverError as ex:
        assert "60 Minuten" in str(ex)
