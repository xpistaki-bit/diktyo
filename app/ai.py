"""KI-Nachschlagen für den Katalog über die Claude API (optional, eigener API-Schlüssel).

Claude recherchiert mit der Websuche Datenblätter zu Hersteller und Modell und liefert die Felder eines
Katalogeintrags über das Werkzeug „catalog_entry“ (strenges Schema). Gesendet werden nur Hersteller, Modell und
die erkannten Eckdaten – nie Seriennummer, UUID oder Daten aus dem Netz des Nutzers. Das Ergebnis ist ein Vorschlag
mit Quellen, der vor dem Speichern geprüft wird.
"""
import json

from . import catalog, security
from .db import get_setting, set_setting

MODELS = {  # Modell -> (Name, $ je 1 Mio. Eingabe-Token, $ je 1 Mio. Ausgabe-Token)
    "claude-opus-5-5": ("Claude Opus 5.5", 4.0, 20.0),
    "claude-sonnet-5-5": ("Claude Sonnet 5.5", 2.0, 10.0),
    "claude-haiku-5-5": ("Claude Haiku 5.5", 0.10, 0.50),
}
DEFAULT_MODEL = "claude-opus-5-5"
SEARCH_PRICE = 0.01  # $ je Websuche
MAX_SEARCHES = 5


class AIError(Exception):
    pass


def settings(c):
    s = get_setting(c, "ai", {}) or {}
    return dict(model=s.get("model") if s.get("model") in MODELS else DEFAULT_MODEL, key=s.get("key") or "")


def save(c, key=None, model=None):
    s = dict(get_setting(c, "ai", {}) or {})
    if key is not None and key != security.MASK:
        s["key"] = security.encrypt(key.strip()) if key.strip() else ""
    if model in MODELS:
        s["model"] = model
    set_setting(c, "ai", s)


def configured(c):
    return bool(settings(c)["key"])


TOOL = {
    "name": "catalog_entry",
    "description": "Liefert den recherchierten Katalogeintrag. Genau einmal aufrufen, nachdem die Daten recherchiert sind.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(catalog.TYPES), "description": "Gerätetyp"},
            "manufacturer": {"type": "string", "description": "Hersteller, kurz (z. B. „HP“, „Dell“, „AVM“)"},
            "model": {"type": "string", "description": "Modellbezeichnung ohne Hersteller"},
            "ports": {
                "type": "array",
                "description": "Kabelgebundene Netzwerk-/WAN-Anschlüsse in Gruppen gleicher Art und Geschwindigkeit. Keine USB-, Video- oder Audioanschlüsse.",
                "items": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Anzahl"},
                        "kind": {"type": "string", "enum": list(catalog.PORT_KINDS)},
                        "speed": {"type": "string", "description": "z. B. „1G“, „2.5G“, „10G“; leer wenn unbekannt"},
                        "label": {"type": "string", "description": "Bezeichnung, z. B. „LAN“, „WAN“, „SFP+“; leer wenn keine"},
                        "poe": {"type": "boolean"},
                    },
                    "required": ["count", "kind", "speed", "label", "poe"],
                    "additionalProperties": False,
                },
            },
            "wifi": {"type": "string", "description": "WLAN, z. B. „Wi-Fi 6 (2,4/5 GHz)“; leer wenn keines"},
            "managed": {"type": "boolean", "description": "verwaltbarer (managed) Switch/Router mit Weboberfläche oder SNMP"},
            "note": {"type": "string", "description": "1–2 Sätze mit den wichtigsten Eckdaten (Formfaktor, Prozessor/Chipsatz, Besonderheiten)"},
            "sources": {"type": "array", "items": {"type": "string"}, "description": "URLs der genutzten Quellen, Herstellerseiten zuerst"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"],
                           "description": "high = Herstellerdatenblatt gefunden, low = nur indirekte Hinweise"},
        },
        "required": ["type", "manufacturer", "model", "ports", "wifi", "managed", "note", "sources", "confidence"],
        "additionalProperties": False,
    },
}

SYSTEM = """Du recherchierst technische Daten zu Netzwerk- und Computer-Hardware für einen Gerätekatalog einer \
Heimnetz-Dokumentation. Suche mit der Websuche nach dem Datenblatt bzw. den QuickSpecs des Herstellers (bevorzugt) \
oder verlässlichen Fachquellen. Erfasse die kabelgebundenen Netzwerkanschlüsse genau (Anzahl, RJ45/SFP/SFP+, \
Geschwindigkeit, PoE) und WLAN, falls vorhanden. Gibt es Ausstattungsvarianten, nimm die Grundausstattung und nenne \
die Varianten in der Notiz. Erfinde nichts: Was du nicht belegen kannst, lässt du leer und setzt confidence entsprechend. \
Rufe zum Schluss genau einmal das Werkzeug catalog_entry auf."""


def _client(key):
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=2)


def _prompt(hint, lang):
    lines = [f"Hersteller: {hint.get('manufacturer', '')}", f"Modell: {hint.get('model', '')}"]
    for k, label in (("family", "Produktfamilie"), ("type", "vermuteter Typ"), ("sku", "SKU"), ("chassis", "Gehäuse")):
        if hint.get(k):
            lines.append(f"{label}: {hint[k]}")
    if hint.get("nics"):
        lines.append("Erkannte Netzwerkkarten: " + "; ".join(hint["nics"]))
    lines.append(f"Schreibe die Notiz auf {'Englisch' if lang == 'en' else 'Deutsch'}.")
    return "Recherchiere dieses Gerät für den Katalog:\n" + "\n".join(lines)


def _cost(model, usage):
    _, pin, pout = MODELS.get(model, MODELS[DEFAULT_MODEL])
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    tokens_in = (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
    return tokens_in, usage.output_tokens or 0, searches, tokens_in * pin / 1e6 + (usage.output_tokens or 0) * pout / 1e6 + searches * SEARCH_PRICE


def lookup(c, hint, lang="de"):
    """hint = dict(manufacturer, model, family, type, sku, chassis, nics) -> dict(entry, sources, confidence, usage)"""
    import anthropic
    s = settings(c)
    if not s["key"]:
        raise AIError("Kein Claude-API-Schlüssel hinterlegt (Einstellungen → KI)")
    if not hint.get("manufacturer") or not hint.get("model"):
        raise AIError("Hersteller und Modell werden für die KI-Suche gebraucht")
    client = _client(security.decrypt(s["key"]))
    messages = [{"role": "user", "content": _prompt(hint, lang)}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}, TOOL]
    total = dict(input=0, output=0, searches=0, cost=0.0)
    served_by = s["model"]
    try:
        for _ in range(4):  # Websuche kann den Turn pausieren (pause_turn) – dann fortsetzen
            args = dict(model=s["model"], max_tokens=16000, system=SYSTEM, messages=messages, tools=tools, output_config={"effort": "medium"})
            try:  # Ausweichmodell, falls ein Sicherheitsfilter die Anfrage ablehnt
                resp = client.beta.messages.create(**args, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            except anthropic.BadRequestError as ex:
                if "fallback" not in str(getattr(ex, "message", ex)).lower():
                    raise
                resp = client.beta.messages.create(**args)
            i, o, n, cost = _cost(resp.model, resp.usage)
            total.update(input=total["input"] + i, output=total["output"] + o, searches=total["searches"] + n, cost=total["cost"] + cost)
            served_by = resp.model
            call = next((b for b in resp.content if b.type == "tool_use" and b.name == "catalog_entry"), None)
            if call:
                return _result(call.input, resp, total, served_by)
            if resp.stop_reason == "refusal":
                raise AIError("Die KI hat die Anfrage abgelehnt")
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
    except anthropic.AuthenticationError:
        raise AIError("Claude-API-Schlüssel ungültig")
    except anthropic.PermissionDeniedError:
        raise AIError("Der API-Schlüssel darf dieses Modell oder die Websuche nicht nutzen (Websuche in der Console freigeben)")
    except anthropic.RateLimitError:
        raise AIError("Claude API: Anfragelimit erreicht – kurz warten")
    except anthropic.BadRequestError as ex:
        msg = getattr(ex, "message", str(ex))
        if "credit" in msg.lower() or "billing" in msg.lower():
            raise AIError("Claude API: kein Guthaben auf dem Konto")
        raise AIError(f"Claude API lehnt die Anfrage ab: {msg[:200]}")
    except anthropic.APIStatusError as ex:
        raise AIError(f"Claude API meldet Fehler {ex.status_code}")
    except anthropic.APIConnectionError:
        raise AIError("Claude API nicht erreichbar (Internetzugang des Containers prüfen)")
    raise AIError("Die KI hat keinen Katalogeintrag geliefert – später erneut versuchen")


def _result(data, resp, total, served_by):
    if isinstance(data, str):  # sollte bei strict nicht vorkommen
        data = json.loads(data)
    entry = dict(type=data.get("type") if data.get("type") in catalog.TYPES else "other",
                 manufacturer=str(data.get("manufacturer") or "").strip()[:80], model=str(data.get("model") or "").strip()[:120],
                 ports=catalog.clean_groups(data.get("ports") or []), wifi=str(data.get("wifi") or "").strip()[:80],
                 managed=bool(data.get("managed")), note=str(data.get("note") or "").strip()[:500])
    sources = [u for u in (data.get("sources") or []) if isinstance(u, str) and u.startswith(("http://", "https://"))][:6]
    if not sources:  # sonst die Treffer der Websuche
        for b in resp.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                sources += [r.url for r in b.content if getattr(r, "url", None)][:3]
    entry["source"] = (sources[0] if sources else "KI-Recherche")[:120]
    return dict(entry=entry, sources=sources, confidence=data.get("confidence", "low"),
                usage=dict(total, cost=round(total["cost"], 4), model=MODELS.get(served_by, (served_by,))[0]))


def test(key, model):
    """Kleine Anfrage ohne Websuche, um Schlüssel und Modell zu prüfen."""
    import anthropic
    try:
        r = _client(key).messages.create(model=model, max_tokens=1024, output_config={"effort": "low"},
                                         messages=[{"role": "user", "content": "Antworte nur mit: ok"}])
    except anthropic.AuthenticationError:
        raise AIError("Claude-API-Schlüssel ungültig")
    except anthropic.APIStatusError as ex:
        raise AIError(f"Claude API meldet Fehler {ex.status_code}: {getattr(ex, 'message', '')[:160]}")
    except anthropic.APIConnectionError:
        raise AIError("Claude API nicht erreichbar (Internetzugang des Containers prüfen)")
    return dict(ok=True, model=MODELS.get(r.model, (r.model,))[0])
