"""MQTT an Home Assistant: Discovery-Konfiguration, Zustände und Ereignisse (paho-mqtt)."""
import json

TOPIC = "diktyo"


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
    try:
        rc = c.connect(conf["mqtt_host"], int(conf.get("mqtt_port") or 1883), keepalive=30)
    except OSError as ex:
        raise MQTTError(f"MQTT-Broker nicht erreichbar: {ex}")
    if rc:
        raise MQTTError(f"MQTT-Verbindung abgelehnt (Code {rc})")
    c.loop_start()
    return c


def check(conf):
    c = _connect(conf)
    import time
    for _ in range(30):  # bis die Anmeldung beim Broker bestätigt ist
        if c.is_connected():
            break
        time.sleep(0.1)
    ok = c.is_connected()
    c.disconnect()
    c.loop_stop()
    if not ok:
        raise MQTTError("MQTT-Anmeldung abgelehnt (Benutzer oder Passwort prüfen)")
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
