"""SNMP-Profile je Hersteller: Erkennung über die sysObjectID (Enterprise-Nummer), Zusatzangaben und Hinweise.

Jedes Profil liest zusätzlich zu den Standard-MIBs:
- ENTITY-MIB (alle Hersteller): Modell, Seriennummer, Firmware/Software und Hardware-Revision des Gehäuses;
- herstellereigene Werte, wo die ENTITY-MIB leer bleibt (Netgear: Inventar und Temperatur aus der FASTPATH-basierten
  NETGEAR-SWITCHING-/BOXSERVICES-MIB, Teilbäume 4526.10 und 4526.11).
Dazu kommen Hinweise, wo man SNMP am Gerät freischaltet und Schreibrechte vergibt (für Diagnose und Fehlermeldungen).
"""
from . import snmplib

ENT = "1.3.6.1.2.1.47.1.1.1.1"   # entPhysicalEntry
ENT_CLASS, ENT_HW, ENT_FW, ENT_SW, ENT_SERIAL, ENT_MFG, ENT_MODEL = (f"{ENT}.{n}" for n in (5, 8, 9, 10, 11, 12, 13))
HR_CPU = "1.3.6.1.2.1.25.3.3.1.2"  # hrProcessorLoad
CHASSIS = 3

# Netgear (Enterprise 4526): agentInventoryGroup und boxServicesTempSensorTemperature – je nach Serie unter .10 oder .11
NG_BASES = ("1.3.6.1.4.1.4526.10", "1.3.6.1.4.1.4526.11")
NG_INV = {"model": "1.1.1.3.0", "serial": "1.1.1.4.0", "software": "1.1.1.13.0"}
NG_TEMP = "43.1.8.1.5"

PROFILES = {
    "netgear": dict(name="Netgear", enterprise="4526",
                    enable=("Netgear: im Web-Menü unter System → SNMP (M-Serie: System → Management → SNMP) eine Community bzw. einen "
                            "SNMPv3-Benutzer anlegen und díktyos Adresse als erlaubten Client eintragen. Die Plus-Switches (GS105E, GS108E, "
                            "GS305E, GS308E …) haben kein SNMP – sie lassen sich nur von Hand dokumentieren."),
                    write="Netgear: unter System → SNMP → Community Configuration eine Community mit Zugriff „Read-Write“ anlegen."),
    "zyxel": dict(name="Zyxel", enterprise="890",
                  enable=("Zyxel: unter Management → Access Control → Service Access SNMP erlauben und díktyos Adresse unter "
                          "Remote Management/Trusted Hosts eintragen, dann Save."),
                  write=("Zyxel: unter Management → Access Control → SNMP den Benutzer einer Gruppe mit Schreibrechten (z. B. „admin“) "
                         "zuordnen bzw. eine Community mit read-write anlegen, dann Save.")),
    "tplink": dict(name="TP-Link", enterprise="11863",
                   enable="TP-Link: unter Maintenance → SNMP → Global Config SNMP einschalten und eine Community bzw. einen Benutzer anlegen.",
                   write="TP-Link: der Community unter SNMP → Community Config die Zugriffsart „read-write“ geben."),
    "generic": dict(name="Generisch", enterprise="", enable="", write=""),
}
CHOICES = [["auto", "automatisch (nach Hersteller)"]] + [[k, p["name"]] for k, p in PROFILES.items()]


def enterprise(object_id):
    """sysObjectID -> Enterprise-Nummer als Text ("" wenn keine)."""
    oid = snmplib.text(object_id) if not isinstance(object_id, str) else object_id
    parts = (oid or "").lstrip(".").split(".")
    return parts[6] if parts[:6] == ["1", "3", "6", "1", "4", "1"] and len(parts) > 6 else ""


def detect(object_id, descr="", choice="auto"):
    """Profilschlüssel: ausdrücklich gewählt, sonst über die Enterprise-Nummer, sonst über die Beschreibung."""
    if choice in PROFILES:
        return choice
    ent = enterprise(object_id)
    for k, p in PROFILES.items():
        if p["enterprise"] and p["enterprise"] == ent:
            return k
    d = (descr or "").lower()
    return next((k for k, p in PROFILES.items() if p["enterprise"] and p["name"].lower().replace("-", "") in d.replace("-", "")), "generic")


def _walk(c, oid):
    try:
        return {o[len(oid) + 1:]: v for o, v in c.walk(oid).items()}
    except snmplib.SNMPError:
        return {}


def _clean(v):
    s = snmplib.text(v).strip() if v is not None else ""
    return "" if s.lower() in ("", "n/a", "none", "unknown", "0") else s[:80]


def entity(c):
    """Gehäuse aus der ENTITY-MIB: dict(model, serial, firmware, hardware, manufacturer) – leere Werte weggelassen."""
    cls = _walk(c, ENT_CLASS)
    idx = next((k for k, v in sorted(cls.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0) if v == CHASSIS), None)
    if idx is None:
        return {}
    oids = dict(model=ENT_MODEL, serial=ENT_SERIAL, firmware=ENT_SW, hardware=ENT_HW, manufacturer=ENT_MFG)
    try:
        r = c.get(*(f"{o}.{idx}" for o in oids.values()), f"{ENT_FW}.{idx}")
    except snmplib.SNMPError:
        return {}
    out = {k: _clean(r.get(f"{o}.{idx}")) for k, o in oids.items()}
    out["firmware"] = out["firmware"] or _clean(r.get(f"{ENT_FW}.{idx}"))
    return {k: v for k, v in out.items() if v}


def netgear(c):
    """Inventar und Temperaturen aus dem Netgear-Teilbaum (erster Zweig, der antwortet)."""
    for base in NG_BASES:
        try:
            r = c.get(*(f"{base}.{o}" for o in NG_INV.values()))
        except snmplib.SNMPError:
            continue
        inv = {k: _clean(r.get(f"{base}.{o}")) for k, o in NG_INV.items()}
        temps = [v for v in _walk(c, f"{base}.{NG_TEMP}").values() if isinstance(v, int) and -40 < v < 150]
        if any(inv.values()) or temps:
            out = {k: v for k, v in inv.items() if v}
            if temps:
                out["temperature"] = max(temps)
            return out
    return {}


def cpu(c):
    loads = [v for v in _walk(c, HR_CPU).values() if isinstance(v, int)]
    return round(sum(loads) / len(loads)) if loads else None


def extra(c, key):
    """Zusatzangaben je Profil -> dict(model, serial, firmware, hardware, manufacturer, temperature, cpu); nur Gefundenes."""
    out = entity(c)
    if key == "netgear":
        ng = netgear(c)
        for k in ("model", "serial"):
            if ng.get(k) and not out.get(k):
                out[k] = ng[k]
        if ng.get("software"):
            out["firmware"] = out.get("firmware") or ng["software"]
        if "temperature" in ng:
            out["temperature"] = ng["temperature"]
    load = cpu(c)
    if load is not None:
        out["cpu"] = load
    return out


def hint(key, kind):
    """Hinweistext des Profils: kind = enable | write."""
    return (PROFILES.get(key) or {}).get(kind, "")
