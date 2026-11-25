"""Katalogeintrag aus Systeminformationen: dmidecode, lspci, hostnamectl, PowerShell/wmic, /sys/class/dmi.

Erkennt Hersteller, Modell, Gerätetyp und Netzwerkanschlüsse; optional eine Beschreibung aus Wikipedia (gesendet
werden nur Hersteller und Modell, nie Seriennummer oder UUID). Ergebnis ist ein Vorschlag, der vor dem Speichern
geprüft wird.
"""
import re

import httpx

EMPTY = {"", "not specified", "to be filled by o.e.m.", "default string", "system product name", "system manufacturer",
         "system version", "none", "n/a", "o.e.m.", "not applicable", "unknown", "x.x", "0123456789"}
VENDORS = [
    (r"^dell", "Dell"), (r"^lenovo", "Lenovo"), (r"^(hp|hewlett[- ]packard)\b", "HP"), (r"^asustek|^asus", "ASUS"),
    (r"^micro-star|^msi\b", "MSI"), (r"^gigabyte", "Gigabyte"), (r"^acer", "Acer"), (r"^apple", "Apple"), (r"^intel", "Intel"),
    (r"^supermicro|^super micro", "Supermicro"), (r"^fujitsu", "Fujitsu"), (r"^microsoft", "Microsoft"), (r"^samsung", "Samsung"),
    (r"^toshiba|^dynabook", "Dynabook"), (r"^asrock", "ASRock"), (r"^qemu", "QEMU"), (r"^vmware", "VMware"),
    (r"^innotek", "VirtualBox"), (r"^xen", "Xen"), (r"^beelink", "Beelink"), (r"^minisforum|^micro computer \(hk\)", "Minisforum"),
    (r"^raspberry", "Raspberry Pi"), (r"^zotac", "ZOTAC"), (r"^shuttle", "Shuttle"), (r"^terra|^wortmann", "TERRA"),
]
LAPTOP = r"latitude|thinkpad|elitebook|probook|zbook|macbook|zenbook|vivobook|ideapad|yoga|surface (laptop|book)|travelmate|aspire|lifebook|notebook|laptop|xps 1[35]|xps 9\d{3}|inspiron 1[3-7]|chromebook|spectre|envy x360"
SERVER = r"poweredge|proliant|thinksystem|primergy|\bsys-\d|superserver|server"
COMPUTER = r"optiplex|precision|thinkcentre|thinkstation|elitedesk|prodesk|elite ?mini|vostro|nuc|mac ?mini|imac|mac pro|esprimo|veriton|desktop|tower|mini ?pc|ser\d|um\d{3}|inspiron 3\d{3}"
CHASSIS = {"notebook": "laptop", "laptop": "laptop", "portable": "laptop", "convertible": "laptop", "sub notebook": "laptop",
           "rack mount chassis": "server", "main server chassis": "server", "blade": "server", "multi-system chassis": "server",
           "desktop": "computer", "tower": "computer", "mini tower": "computer", "low profile desktop": "computer", "mini pc": "computer",
           "space-saving": "computer", "all in one": "computer", "small form factor": "computer", "lunch box": "computer"}
VIRTUAL = r"qemu|kvm|vmware|virtualbox|innotek|hyper-v|virtual machine|bochs|xen|standard pc \((q35|i440fx)"
NIC_SPEED = [  # (Muster im Namen des Ethernet-Controllers, Geschwindigkeit, Anschluss)
    (r"x710|xl710|x722|x550|x540|x520|82599|aqc1\d\d|aquantia|marvell.*10g|bcm57810|ql41|10g", "10G", None),
    (r"connectx|mellanox|e810|25g", "25G", "sfp28"), (r"i225|i226|rtl8125|2\.5g|2500", "2.5G", "rj45"),
    (r"rtl8126|5g", "5G", "rj45"), (r".*", "1G", "rj45"),
]


def _clean(v):
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return "" if v.lower() in EMPTY else v


def _vendor(v):
    v = _clean(v)
    low = v.lower()
    for pat, name in VENDORS:
        if re.search(pat, low):
            return name
    return re.sub(r",? (inc|corp|corporation|co|ltd|gmbh|technology|computer|international)\.?$", "", v, flags=re.I).strip()


KEY = re.compile(r"[A-Za-z][A-Za-z0-9 _./()-]*")


def _fields(text):
    """Schlüssel: Wert aus allen bekannten Formaten -> {schluessel_klein: wert}"""
    out = {}
    for line in text.splitlines():
        if len(line) > 1000:
            continue
        cut = [i for i in (line.find(":"), line.find("=")) if i >= 0]
        if not cut:
            continue
        key, val = line[:min(cut)].strip(), line[min(cut) + 1:].strip()
        # Schlüssel: Buchstabe am Anfang, dann Buchstaben, Ziffern, Leerzeichen und _./()- – geprüft ohne verschachtelte Wiederholung
        if val and 2 <= len(key) <= 41 and KEY.fullmatch(key):
            out.setdefault(key.lower().replace("_", " "), val.strip('"'))
    return out


def parse(text):
    """-> dict(manufacturer, model, type, family, version, sku, serial, uuid, chassis, virtual, nics=[...])"""
    f = _fields(text)
    pick = lambda *keys: next((_clean(f[k]) for k in keys if _clean(f.get(k))), "")  # noqa: E731
    vendor = _vendor(pick("manufacturer", "sys vendor", "hardware vendor", "vendor", "csmanufacturer"))
    product = pick("product name", "product", "model", "hardware model", "csmodel", "product name ", "name")
    version = pick("version", "product version", "systemversion")
    family = pick("family", "product family", "systemfamily")
    family = re.sub(r"^[0-9A-Fa-f]{4}_[0-9A-Fa-f]+\s*", "", family)  # HP: „103C_53307F HP EliteDesk“
    if family.lower().startswith(vendor.lower() + " "):
        family = family[len(vendor) + 1:]
    model = product
    if vendor == "Lenovo" and version and not re.fullmatch(r"[0-9A-Z]{8,10}", version):
        model = version  # Lenovo: Produktname = Maschinentyp (z. B. 10MQS0B600), Version = Modellname
    if model.lower().startswith(vendor.lower() + " "):
        model = model[len(vendor) + 1:]
    chassis = pick("type", "chassis type", "chassis")
    nics = []
    for line in text.splitlines():
        m = re.search(r"(ethernet controller|network controller)[^:\n]{0,200}:[ \t]*(\S.*)", line[:1000], re.I)
        if m and not re.search(r"wireless|wi-?fi|wlan|802\.11|centrino|ax2\d\d|ac \d{4}", m.group(2), re.I):
            nics.append(m.group(2).strip()[:120])
    joined = " ".join([vendor, product, version, family]).lower()
    virtual = bool(re.search(VIRTUAL, joined))
    typ = "vm" if virtual else CHASSIS.get(chassis.lower(), "")
    if not typ:
        typ = "laptop" if re.search(LAPTOP, joined) else "server" if re.search(SERVER, joined) else "computer" if re.search(COMPUTER, joined) else "computer"
    return dict(manufacturer=vendor, model=model, type=typ, family=family, version=version, sku=pick("sku number", "sku"),
                serial=pick("serial number", "serialnumber", "product serial"), uuid=pick("uuid", "product uuid"), chassis=chassis,
                virtual=virtual, nics=nics)


def ports_for(info):
    """Port-Gruppen aus den erkannten Netzwerkkarten (sonst 1× RJ45 1G)."""
    groups = []
    for n in info["nics"] or ([] if info["virtual"] else ["onboard"]):
        speed, kind = next((s, k) for pat, s, k in NIC_SPEED if re.search(pat, n.lower()))
        kind = kind or ("sfp+" if re.search(r"x710|xl710|x520|82599|bcm57810|ql41", n.lower()) else "rj45")
        if groups and (groups[-1]["kind"], groups[-1]["speed"]) == (kind, speed):
            groups[-1]["count"] += 1
        else:
            groups.append(dict(count=1, kind=kind, speed=speed))
    return groups


def lookup(manufacturer, model, family="", lang="de"):
    """Kurze Beschreibung aus Wikipedia (nur Hersteller und Modell werden gesendet). -> dict(title, url, extract) | None"""
    if not manufacturer or not model:
        return None
    words = model.split()
    queries = [f"{manufacturer} {' '.join(words[:n])}" for n in range(len(words), 0, -1)][:4]  # „HP EliteDesk 800 G4 DM 35W“ … „HP EliteDesk“
    if family and family.lower() not in model.lower():
        queries.append(f"{manufacturer} {family}")
    queries.append(f"{manufacturer} {words[0]}")
    headers = {"User-Agent": "diktyo network documentation (https://github.com/xpistaki-bit/diktyo)"}
    with httpx.Client(timeout=6, headers=headers, follow_redirects=True) as cl:
        for wiki in dict.fromkeys([lang, "en"]):
            for q in dict.fromkeys(queries):
                r = cl.get(f"https://{wiki}.wikipedia.org/w/rest.php/v1/search/title", params={"q": q, "limit": 5})
                r.raise_for_status()
                pages = r.json().get("pages") or []
                key = (family or words[0]).lower()
                # z. B. „OptiPlex“ (ohne Hersteller im Titel) oder „List of HP business desktops“
                page = next((p for p in pages if key in p["title"].lower() or (len(q.split()) > 1 and manufacturer.lower() in p["title"].lower().split())), None)
                if not page:
                    continue
                try:
                    s = cl.get(f"https://{wiki}.wikipedia.org/api/rest_v1/page/summary/{page['key']}").json()
                except (httpx.HTTPError, ValueError):
                    continue
                if s.get("type") == "disambiguation" or not s.get("extract"):
                    continue
                sentences = re.split(r"(?<=[.!?])\s+", s["extract"])
                return dict(title=s.get("title", page["title"]), url=(s.get("content_urls") or {}).get("desktop", {}).get("page", ""),
                            extract=" ".join(sentences[:2])[:400], lang=wiki)
    return None


def suggest(text, do_lookup=True, lang="de"):
    info = parse(text)
    if not info["manufacturer"] or not info["model"]:
        return dict(info=info, suggestion=None, lookup=None, lookup_status="off")
    wiki, status = None, "off"
    if do_lookup and not info["virtual"]:
        try:
            wiki = lookup(info["manufacturer"], info["model"], info["family"], lang)
            status = "found" if wiki else "none"
        except Exception as ex:  # Wikipedia nicht erreichbar o. ä.: nur die Art des Fehlers melden
            print(f"Wikipedia-Suche: {type(ex).__name__}: {ex}", flush=True)
            status = "error"
    note = f"{wiki['title']}: {wiki['extract']}" if wiki else ""
    if info["manufacturer"] == "Lenovo" and info["version"] and info["model"] == info["version"] and info["sku"]:
        note = (note + " " if note else "") + f"Maschinentyp {info['sku']}"
    sug = dict(manufacturer=info["manufacturer"], model=info["model"], type=info["type"], ports=ports_for(info), wifi="", managed=False,
               note=note[:500], source=(wiki or {}).get("url", "")[:120] or "Systeminfo")
    return dict(info=info, suggestion=sug, lookup=wiki, lookup_status=status)
