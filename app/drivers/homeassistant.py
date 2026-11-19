"""Home Assistant: Namen und Bereiche aus HA übernehmen (REST-API, Long-Lived Token) und Status/Ereignisse per MQTT an HA melden.

Die MQTT-Seite (Discovery, Zustände, Ereignisse) erledigt app/integrations.py, weil sie Daten aus díktyo braucht.
"""
import httpx

NAME = "Home Assistant"
DEFAULT_INTERVAL = 60
FIELDS = [
    dict(key="host", label="Adresse von Home Assistant", type="text", default="http://homeassistant.local:8123", required=True),
    dict(key="password", label="Long-Lived Access Token (für Namen und Bereiche)", type="password", default="", secret=True),
    dict(key="import_names", label="Namen aus HA übernehmen", type="select", default="new", options=[
        ["new", "für neue und unbenannte Geräte"], ["all", "für alle Geräte"], ["no", "nein"]]),
    dict(key="import_areas", label="Bereiche als Standorte übernehmen", type="select", default="yes", options=[["yes", "ja, wenn leer"], ["no", "nein"]]),
    dict(key="mqtt_host", label="MQTT-Broker (z. B. Mosquitto in HA)", type="text", default=""),
    dict(key="mqtt_port", label="MQTT-Port", type="number", default=1883),
    dict(key="mqtt_user", label="MQTT-Benutzer", type="text", default=""),
    dict(key="mqtt_pass", label="MQTT-Passwort", type="password", default="", secret=True),
    dict(key="publish", label="An HA melden", type="select", default="infra", options=[
        ["infra", "Infrastruktur (Router, Switches, APs, Server, NAS)"], ["all", "alle bestätigten Geräte"], ["none", "nur Ereignisse und Zähler"]]),
]

# Alle HA-Geräte mit MAC-Adresse samt Name, Bereich, Hersteller und Modell (geprüft gegen HA 2026.11)
TEMPLATE = (
    "{% set ns = namespace(ids=[]) %}{% for s in states %}{% set d = device_id(s.entity_id) %}"
    "{% if d and d not in ns.ids %}{% set ns.ids = ns.ids + [d] %}{% endif %}{% endfor %}"
    "{% set out = namespace(l=[]) %}{% for d in ns.ids %}{% set m = namespace(l=[]) %}"
    "{% for c in (device_attr(d, 'connections') or []) %}{% if c[0] == 'mac' %}{% set m.l = m.l + [c[1]] %}{% endif %}{% endfor %}"
    "{% if m.l %}{% set out.l = out.l + [{'id': d, 'name': device_attr(d, 'name_by_user') or device_attr(d, 'name'), "
    "'area': area_name(d), 'manufacturer': device_attr(d, 'manufacturer'), 'model': device_attr(d, 'model'), 'macs': m.l}] %}{% endif %}"
    "{% endfor %}{{ out.l | tojson }}"
)


class DriverError(Exception):
    pass


def _url(conf):
    h = conf["host"].rstrip("/")
    return h if h.startswith(("http://", "https://")) else f"http://{h}:8123"


def _devices(conf):
    if not conf.get("password"):
        return None
    try:
        r = httpx.post(f"{_url(conf)}/api/template", json={"template": TEMPLATE}, timeout=20, verify=False,
                       headers={"Authorization": f"Bearer {conf['password']}"})
    except httpx.HTTPError as ex:
        raise DriverError(f"Home Assistant nicht erreichbar: {ex}")
    if r.status_code == 401:
        raise DriverError("Token abgelehnt (Long-Lived Access Token prüfen)")
    r.raise_for_status()
    import json
    try:
        return json.loads(r.text)
    except ValueError:
        raise DriverError("Unerwartete Antwort von Home Assistant")


def test(conf):
    out = {}
    if conf.get("password"):
        devs = _devices(conf)
        out.update(devices=len(devs), areas=len({d["area"] for d in devs if d.get("area")}))
    if conf.get("mqtt_host"):
        from .. import mqtt
        mqtt.check(conf)
        out["mqtt"] = True
    if not out:
        raise DriverError("Token oder MQTT-Broker angeben")
    return out


def poll(conf, state):
    devs = _devices(conf)
    return dict(ha_devices=devs, info=dict(devices=len(devs) if devs is not None else None)), {}, state
