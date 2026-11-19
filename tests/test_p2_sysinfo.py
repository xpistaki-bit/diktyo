"""Katalogeintrag aus Systeminformationen (dmidecode, lspci, Lenovo, VM, Windows) – Nachschlagen ist hier nachgebildet."""
from app import sysinfo
from tests.test_m6 import H, login

DELL = """System Information
        Manufacturer: Dell Inc.
        Product Name: OptiPlex 7040
        Version: Not Specified
        Serial Number: ABC1234
        UUID: 4c4c4544-0000-0000-0000-000000000000
        Wake-up Type: Power Switch
        SKU Number: 06B9
        Family: OptiPlex
"""


def test_parse_variants():
    d = sysinfo.parse(DELL)
    assert (d["manufacturer"], d["model"], d["type"], d["family"]) == ("Dell", "OptiPlex 7040", "computer", "OptiPlex")
    lenovo = sysinfo.parse("Manufacturer: LENOVO\nProduct Name: 10MQS0B600\nVersion: ThinkCentre M920q\nSKU Number: LENOVO_MT_10MQ\n")
    assert lenovo["manufacturer"] == "Lenovo" and lenovo["model"] == "ThinkCentre M920q" and lenovo["type"] == "computer"
    hp = sysinfo.parse("Manufacturer: HP\nProduct Name: HP EliteBook 840 G5\n")
    assert hp["model"] == "EliteBook 840 G5" and hp["type"] == "laptop"
    vm = sysinfo.parse("Manufacturer: QEMU\nProduct Name: Standard PC (Q35 + ICH9, 2009)\n")
    assert vm["virtual"] and vm["type"] == "vm" and sysinfo.ports_for(vm) == []
    win = sysinfo.parse("Manufacturer        : Dell Inc.\nModel               : PowerEdge T140\n")
    assert win["manufacturer"] == "Dell" and win["model"] == "PowerEdge T140" and win["type"] == "server"
    nics = sysinfo.parse(DELL + "00:1f.6 Ethernet controller: Intel Corporation Ethernet Connection (2) I219-LM (rev 31)\n"
                                "01:00.0 Ethernet controller: Intel Corporation Ethernet Controller I226-V (rev 04)\n"
                                "02:00.0 Ethernet controller: Intel Corporation Ethernet Controller I226-V (rev 04)\n"
                                "03:00.0 Network controller: Intel Corporation Wi-Fi 6 AX200 (rev 1a)\n")
    assert sysinfo.ports_for(nics) == [dict(count=1, kind="rj45", speed="1G"), dict(count=2, kind="rj45", speed="2.5G")]


def test_api_suggestion_and_privacy(monkeypatch):
    sent = []
    monkeypatch.setattr(sysinfo, "lookup", lambda man, model, family="", lang="de": sent.append((man, model, family)) or dict(
        title="OptiPlex", url="https://en.wikipedia.org/wiki/OptiPlex", extract="OptiPlex is a line of business desktops.", lang="en"))
    cl = login()
    r = cl.post("/api/catalog/from-sysinfo", json={"text": DELL, "lookup": True}, headers=H).json()
    s = r["suggestion"]
    assert (s["manufacturer"], s["model"], s["type"]) == ("Dell", "OptiPlex 7040", "computer") and s["ports"] == [dict(count=1, kind="rj45", speed="1G")]
    assert s["note"].startswith("OptiPlex:") and s["source"] == "https://en.wikipedia.org/wiki/OptiPlex"
    # Seriennummer/UUID gehen weder ins Internet noch in die Antwort
    assert sent == [("Dell", "OptiPlex 7040", "OptiPlex")] and "serial" not in r["info"] and r["ignored"] == ["serial", "uuid"]
    assert "ABC1234" not in str(r)
    # speichern, danach erkennt der Vorschlag den vorhandenen Eintrag
    saved = cl.post("/api/catalog", json=s, headers=H).json()
    assert saved["source"].startswith("https://en.wikipedia.org") and saved["port_summary"]
    again = cl.post("/api/catalog/from-sysinfo", json={"text": DELL, "lookup": False}, headers=H).json()
    assert again["existing"]["id"] == saved["id"] and len(sent) == 1
    bad = cl.post("/api/catalog/from-sysinfo", json={"text": "hallo welt"}, headers=H)
    assert bad.status_code == 400 and "dmidecode" in bad.json()["error"]
