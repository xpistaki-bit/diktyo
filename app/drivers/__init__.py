"""Treiber für Integrationen. Jeder Treiber hat NAME, FIELDS, DEFAULT_INTERVAL, test(conf) und poll(conf, state)."""
from .. import mqtt
from . import asuswrt, fritzbox, homeassistant, proxmox, snmp

DRIVERS = {"fritzbox": fritzbox, "snmp": snmp, "asuswrt": asuswrt, "proxmox": proxmox, "homeassistant": homeassistant}
ERRORS = (fritzbox.DriverError, snmp.DriverError, asuswrt.DriverError, proxmox.DriverError, homeassistant.DriverError, mqtt.MQTTError)


def schema():
    return [dict(key=k, name=m.NAME, fields=m.FIELDS, interval=m.DEFAULT_INTERVAL) for k, m in DRIVERS.items()]
