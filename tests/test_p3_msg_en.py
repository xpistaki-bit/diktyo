"""Englische Meldungen: jede Meldung im Code hat eine englische Fassung, Muster mit eingesetzten Teilen, Fehlerantworten
in der Sprache des Browsers, Tabelle für die Oberfläche."""
import ast
import pathlib
import re

from app import msg_en
from tests.test_m6 import H, login

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
GERMAN = re.compile(r"[äöüßÄÖÜ]|\b(nicht|und|oder|ist|wird|bitte|prüfen|angeben|erreichbar|abgelehnt|gefunden|einschalten|ausschalten|"
                    r"abschalten|starten|sperren|freigeben|Gerät|keine?|für|mit|über|neu|schon|fehlt|gibt|wählen|eintragen)\b")
CALLS = {"HTTPException", "DriverError", "OIDCError", "CablingError", "VlanError", "LabelError", "NetplanError", "WatchError", "LayoutError",
         "NotifyError", "BackupError", "UserError", "SSHError", "TwoFAError", "AIError", "_act"}


def _pattern(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _messages():
    out = {}
    for f in APP.rglob("*.py"):
        if f.name == "msg_en.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            args = []
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                args = node.exc.args
            elif isinstance(node, ast.Call) and (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) in CALLS:
                args = node.args
            for a in args:
                s = _pattern(a)
                if s and len(s) > 3 and GERMAN.search(s):
                    out.setdefault(s, f.name)
    return out


def test_every_message_has_english():
    missing = []
    for s, f in _messages().items():
        sample = s.replace("{}", "X1")
        if GERMAN.search(msg_en.en(sample).replace("díktyo", "")):
            missing.append(f"{f}: {s}")
    # bekannte Fälle mit angehängtem Zusatz: beide konkreten Fassungen stehen in der Tabelle
    missing = [m for m in missing if not m.endswith("Minuten weg.{}") and "liegt nicht im Netz von {} ({}){}" not in m]
    assert not missing, "Ohne englische Fassung:\n" + "\n".join(missing)


def test_patterns_and_words():
    assert msg_en.en("WLAN „Buero“ (2,4 GHz) einschalten") == "Switch on Wi-Fi “Buero” (2.4 GHz)"
    assert msg_en.en("Port ether4 abgeschaltet") == "Port ether4 disabled"
    assert msg_en.en("Ungültige MAC-Adresse: zz") == "Invalid MAC address: zz"
    assert msg_en.en("Anbieter: Anbieter nicht erreichbar: timeout") == "Provider: Provider not reachable: timeout"
    assert msg_en.en("Profil nicht gefunden") == "Profile not found"
    assert msg_en.en("unbekannter Text bleibt") == "unbekannter Text bleibt"
    t = msg_en.table()
    assert t["exact"]["Profil nicht gefunden"] == "Profile not found" and any(de == "Port {} {}" for de, _ in t["patterns"])


def test_error_language():
    cl = login()
    pid = cl.post("/api/profiles", json={"name": "Sprache"}, headers=H).json()["profile"]["id"]
    r = cl.put(f"/api/profiles/{pid}/vlanplan/ports", json={"mode": "plan", "ports": [1]}, headers={**H, "X-Lang": "en"})
    assert r.status_code == 400 and r.json()["error"] == "There is no plan yet"
    r = cl.put(f"/api/profiles/{pid}/vlanplan/ports", json={"mode": "plan", "ports": [1]}, headers={**H, "X-Lang": "de"})
    assert r.json()["error"] == "Es gibt noch keinen Plan"
    assert cl.get("/api/i18n/messages").json()["exact"]["Kabelweg nicht gefunden"] == "Cable run not found"
