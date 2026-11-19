"""MQTT an Home Assistant: Discovery-Konfiguration, Zustände und Ereignisse (paho-mqtt)."""
import json

TOPIC = "diktyo"
# Namen, die nur innerhalb von Home Assistant gelten (Docker-Netz des HA OS); díktyo nimmt dafür die Adresse von HA
INTERNAL = {"core-mosquitto", "localhost", "127.0.0.1", "homeassistant", "a0d7b954-mosquitto", "addon_core_mosquitto"}


def broker(conf):
    """MQTT-Broker-Adresse; HA-interne Namen werden durch den Host aus der HA-Adresse ersetzt."""
    from urllib.parse import urlparse
    h = (conf.get("mqtt_host") or "").strip()
    if h.lower() in INTERNAL:
        ha = conf.get("host") or ""
        return urlparse(ha if "://" in ha else f"http://{ha}").hostname or h
    return h


class MQTTError(Exception):
    pass


def _connect(conf):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        raise MQTTError("paho-mqtt ist nicht installiert")
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"diktyo-{conf.get('profile_id', 0)}", clean_session=True)
    if conf.get("mqtt_user"):
        c.username_pw_set(conf["mqtt_user"], conf.get("mqtt_pass") or "")
    host = broker(conf)
    try:
        rc = c.connect(host, int(conf.get("mqtt_port") or 1883), keepalive=30)
    except OSError as ex:
        if "Name or service not known" in str(ex) or "nodename nor servname" in str(ex) or getattr(ex, "errno", None) == -2:
            raise MQTTError(f"MQTT-Broker „{host}“ unbekannt: Den Namen gibt es nur innerhalb von Home Assistant. "
                            f"Die IP-Adresse von Home Assistant eintragen (Port 1883).")
        raise MQTTError(f"MQTT-Broker {host} nicht erreichbar: {ex}")
    if rc:
        raise MQTTError(f"MQTT-Verbindung abgelehnt (Code {rc})")
    c.loop_start()
    import time
    for _ in range(40):  # bis die Anmeldung beim Broker bestätigt ist
        if c.is_connected():
            return c
        time.sleep(0.1)
    c.disconnect()
    c.loop_stop()
    raise MQTTError("MQTT-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)")


def check(conf):
    c = _connect(conf)
    c.disconnect()
    c.loop_stop()
    return True


def publish(conf, messages):
    """messages: [(topic, payload(dict|str), retain)] -> Anzahl gesendet."""
    if not messages:
        return 0
    c = _connect(conf)
    infos = []
    try:
        for topic, payload, retain in messages:
            body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            infos.append(c.publish(topic, body, qos=1, retain=retain))
        for i in infos:
            i.wait_for_publish(timeout=5)
    finally:
        c.disconnect()
        c.loop_stop()
    return len(infos)
