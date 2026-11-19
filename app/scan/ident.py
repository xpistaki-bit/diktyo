"""Geräteerkennung: Regeln, Katalogabgleich und (optional) Fingerbank. Ergebnis mit Begründungen für die Oberfläche."""
import json
import pathlib
import re

import httpx

BASE = pathlib.Path(__file__).resolve().parent.parent
FINGERBANK_URL = "https://api.fingerbank.org/api/v2/combinations/interrogate"
SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|co|corp|corporation|ltd|limited|gmbh|ag|bv|b\.v|llc|s\.a|sa|plc|kg|oy|ab|pte|technologies|"
                    r"technology|communications|electronics|computer|networks|systems|trading|international|digital|"
                    r"audiovisuelles marketing und computersysteme)\b.*$", re.I)
VENDOR_SHORT = {"avm": "AVM", "asustek": "ASUS", "tp-link": "TP-Link", "zyxel": "Zyxel", "amazon": "Amazon", "google": "Google", "apple": "Apple",
                "espressif": "Espressif", "raspberry": "Raspberry Pi", "ubiquiti": "Ubiquiti", "synology": "Synology", "sonos": "Sonos",
                "proxmox": "Proxmox", "signify": "Philips Hue", "devolo": "devolo", "netgear": "Netgear", "samsung": "Samsung"}


# ------------------------------------------------------------ Regeln
def merge_seed(c):
    have = {r["key"]: r for r in c.execute("SELECT key, custom FROM ident_rules")}
    for e in json.loads((BASE / "ident_rules.json").read_text(encoding="utf-8")):
        old = have.get(e["key"])
        vals = (e["label"], e["label_en"], e["type"], json.dumps(e["cond"], ensure_ascii=False), e["weight"])
        if old is None:
            c.execute("INSERT INTO ident_rules(label, label_en, type, cond, weight, key, custom) VALUES(?,?,?,?,?,?,0)", vals + (e["key"],))
        elif not old["custom"]:
            c.execute("UPDATE ident_rules SET label=?, label_en=?, type=?, cond=?, weight=? WHERE key=?", vals + (e["key"],))


def load_rules(c):
    out = []
    for r in c.execute("SELECT * FROM ident_rules ORDER BY weight DESC"):
        cond = json.loads(r["cond"] or "{}")
        try:
            comp = {k: re.compile(v, re.I) for k, v in cond.items() if k in ("vendor", "hostname", "mdns", "ssdp", "http") and isinstance(v, str)}
        except re.error:
            continue
        out.append(dict(key=r["key"], label=r["label"], label_en=r["label_en"] or r["label"], type=r["type"], weight=r["weight"], cond=cond, re=comp))
    return out


def facts(h):
    """Textfelder eines beobachteten Geräts für den Regelabgleich."""
    m, s, w = h.get("mdns") or {}, h.get("ssdp") or {}, h.get("http") or {}
    names = [x for x in [h.get("hostname"), h.get("netbios"), *m.get("names", [])] if x]
    return dict(
        vendor=h.get("vendor", ""), hostname=" ".join(names),
        mdns=" ".join([*m.get("services", []), *m.get("names", []), *(f"{k}={v}" for k, v in m.get("txt", {}).items())]),
        ssdp=" ".join(str(v) for v in s.values() if v), http=" ".join(str(w.get(k, "")) for k in ("title", "server", "realm")),
        ports=set(h.get("ports", [])), random=bool(h.get("random")),
    )


def _match(rule, f):
    reasons = []
    for k, rx in rule["re"].items():
        mt = rx.search(f[k] or "")
        if not mt:
            return None
        reasons.append(dict(k=k, v=_snippet(f[k], mt)))
    c = rule["cond"]
    if c.get("ports"):
        if not set(c["ports"]) <= f["ports"]:
            return None
        reasons += [dict(k="port", v=str(p)) for p in c["ports"]]
    if c.get("any_ports"):
        hit = sorted(set(c["any_ports"]) & f["ports"])
        if not hit:
            return None
        reasons += [dict(k="port", v=str(p)) for p in hit]
    if "random" in c:
        if bool(c["random"]) != f["random"]:
            return None
        if f["random"]:
            reasons.append(dict(k="random", v=""))
    return reasons if (rule["re"] or c.get("ports") or c.get("any_ports") or "random" in c) else None


def _snippet(text, mt):
    """Das passende Wort mit etwas Umgebung, für die Begründung."""
    words = re.findall(r"\S+", text)
    for w in words:
        if mt.group(0).lower() in w.lower():
            return w[:80]
    return mt.group(0)[:80]


# ------------------------------------------------------------ Katalog
def _token(model):
    """Unterscheidendes Wort eines Modellnamens, z. B. „6591“, „XGS1935-28“, „EBM68“."""
    toks = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9+\-]*", model) if re.search(r"\d", t) and len(t) >= 3]
    return max(toks, key=len) if toks else ""


def catalog_index(c):
    out = []
    for r in c.execute("SELECT * FROM device_models WHERE manufacturer <> 'Generisch'"):
        tok = _token(r["model"])
        if tok:
            d = json.loads(r["data"] or "{}")
            out.append(dict(id=r["id"], manufacturer=r["manufacturer"], model=r["model"], type=r["type"], token=tok,
                            rx=re.compile(r"(?<![A-Za-z0-9])" + re.escape(tok) + r"(?![A-Za-z0-9])", re.I),
                            vendors=[v.lower() for v in (d.get("match") or {}).get("vendor", [])] + [r["manufacturer"].lower()]))
    return out


def match_catalog(index, h, f):
    text = " ".join([f["ssdp"], f["http"], f["mdns"], f["hostname"]])
    vend = (f["vendor"] or "").lower()
    best = None
    for m in index:
        if not m["rx"].search(text):
            continue
        brand = any(v and (v in vend or v in text.lower()) for v in m["vendors"])
        if not brand:
            continue
        # das längere (spezifischere) Modell gewinnt, z. B. „7590 AX“ vor „7590“
        exact = m["model"].lower() in text.lower()
        score = (exact, len(m["token"]), len(m["model"]))
        if best is None or score > best[0]:
            best = (score, m)
    if best:
        return best[1]
    # Hostname wie „XGS1935“: Modell, dessen Name damit beginnt (bei mehreren das kürzeste, z. B. XGS1935-28 vor XGS1935-28HP)
    toks = [t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", f["hostname"]) if re.search(r"\d", t) and len(t) >= 5]
    cands = [m for m in index for t in toks if m["token"].lower().startswith(t.lower())
             and any(v and (v in vend or v in text.lower()) for v in m["vendors"])]
    return min(cands, key=lambda m: len(m["model"])) if cands else None


# ------------------------------------------------------------ Fingerbank
def fingerbank(key, h, timeout=6.0):
    """Fragt Fingerbank (externer Dienst). Gesendet werden nur MAC-Adresse und Hostname."""
    params = dict(key=key, mac=h.get("mac", "").lower())
    if h.get("hostname"):
        params["hostname"] = h["hostname"]
    try:
        r = httpx.get(FINGERBANK_URL, params=params, timeout=timeout)
        if r.status_code != 200:
            return None
        j = r.json()
        name = j.get("device_name") or (j.get("device") or {}).get("name")
        return dict(name=name, score=int(j.get("score") or 0)) if name else None
    except Exception:
        return None


FB_TYPES = [(r"echo|alexa|home ?pod|nest (mini|audio)|sonos|speaker", "speaker"), (r"iphone|android|phone|galaxy|pixel", "phone"),
            (r"ipad|tablet|kindle", "tablet"), (r"fire ?tv|chromecast|apple tv|roku|television|\btv\b", "tv"), (r"printer", "printer"),
            (r"camera|cam\b", "camera"), (r"playstation|xbox|nintendo", "console"), (r"router|gateway", "router"), (r"access point", "ap"),
            (r"switch", "switch"), (r"nas|diskstation", "nas"), (r"windows|macos|mac os|linux|computer", "computer")]


def _fb_type(name):
    for rx, t in FB_TYPES:
        if re.search(rx, name, re.I):
            return t
    return None


# ------------------------------------------------------------ Zusammenführen
def vendor_short(v):
    if not v:
        return ""
    low = v.lower()
    for k, s in VENDOR_SHORT.items():
        if k in low:
            return s
    s = SUFFIX.sub("", v).strip(" ,.")
    return " ".join(s.split()[:2])[:40]


def clean_host(name):
    """Kurzname ohne Domain, z. B. „proxmoxone.matrix“ -> „proxmoxone“."""
    name = (name or "").strip().rstrip(".")
    if not name or re.fullmatch(r"[\d.]+", name):
        return name
    return name.split(".")[0]


GENERIC_NAMES = re.compile(r"^(wps (access point|router)|wireless router|wfadevice|router|_?gateway|localhost|none(-\d+)?|unknown|android-?\d*|esp_[0-9a-f]+|"
                           r"spotifyconnect.*|mysimplelink|lwip\d*)$", re.I)


def _usable_name(c):
    """Verwirft Kennungen (Hex, Matter-IDs, Dienstnamen) und generische Gerätenamen."""
    c = (c or "").strip()
    return (bool(c) and len(c) <= 60 and "._" not in c and ":" not in c and not re.fullmatch(r"[0-9a-f:.\-]+", c, re.I)
            and not re.search(r"[0-9A-F]{16,}", c) and not GENERIC_NAMES.match(c))


def good_host(name):
    """Hostname ohne Domain, wenn er als Name taugt, sonst leer."""
    c = clean_host(name)
    return c if _usable_name(c) else ""


def suggest_name(h, ident):
    m = h.get("mdns") or {}
    s = h.get("ssdp") or {}
    for cand in (clean_host(h.get("hostname")), h.get("netbios"), *(m.get("names") or []), s.get("friendlyName")):
        if _usable_name(cand):
            return cand.strip()
    base = ident.get("model") or ident.get("label_short") or ident.get("manufacturer") or "Gerät"
    return f'{base} .{h["ip"].split(".")[-1]}' if h.get("ip") else base


def identify(rules, index, h, fb_key=None):
    f = facts(h)
    hits = []
    for r in rules:
        reasons = _match(r, f)
        if reasons is not None:
            hits.append((r, reasons))
    hits.sort(key=lambda x: -x[0]["weight"])
    out = dict(label="", label_en="", type="other", confidence=0, reasons=[], model_id=None, manufacturer=vendor_short(h.get("vendor", "")),
               model="", vendor=h.get("vendor", ""), random=bool(h.get("random")))
    if h.get("vendor"):
        out["reasons"].append(dict(k="vendor", v=h["vendor"]))
    if hits:
        r, reasons = hits[0]
        out.update(label=r["label"], label_en=r["label_en"], type=r["type"], confidence=r["weight"], rule=r["key"])
        out["reasons"] += [x for x in reasons if x["k"] != "vendor"]
        also, seen_l = [], {r["label"]}
        for x, _ in hits[1:]:
            if x["label"] not in seen_l and len(also) < 3:
                seen_l.add(x["label"])
                also.append(dict(label=x["label"], label_en=x["label_en"], weight=x["weight"]))
        out["also"] = also
    m = match_catalog(index, h, f)
    if m:
        out.update(model_id=m["id"], manufacturer=m["manufacturer"], model=m["model"], confidence=max(out["confidence"], 85) + 5)
        if out["type"] == "other" or out["confidence"] < 90 or not hits:
            out["type"] = m["type"]
        if not out["label"] or out["label"].endswith("-Gerät"):
            out["label"] = out["label_en"] = f'{m["manufacturer"]} {m["model"]}'
        out["reasons"].append(dict(k="model", v=f'{m["manufacturer"]} {m["model"]}'))
    if fb_key and h.get("mac") and not h.get("random"):
        fb = fingerbank(fb_key, h)
        if fb:
            out["fingerbank"] = fb
            out["reasons"].append(dict(k="fingerbank", v=fb["name"], score=fb["score"]))
            if fb["score"] >= 50 and fb["score"] > out["confidence"] - 10 and not m:
                out.update(label=fb["name"], label_en=fb["name"], confidence=max(out["confidence"], min(fb["score"], 95)))
                t = _fb_type(fb["name"])
                if t:
                    out["type"] = t
    if h.get("own"):
        out["reasons"].insert(0, dict(k="own", v=""))
        if out["confidence"] < 70:
            out.update(label="Dieser Rechner (führt den Scan aus)", label_en="This machine (runs the scan)", type="server", confidence=95)
    out["confidence"] = min(out["confidence"], 99)
    out["label_short"] = out["label"]
    return out
