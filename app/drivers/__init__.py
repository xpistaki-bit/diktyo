"""Treiber für Integrationen. Jeder Treiber hat NAME, FIELDS, DEFAULT_INTERVAL, test(conf) und poll(conf, state)."""
from .. import mqtt
from . import asuswrt, controller, docker, fritzbox, homeassistant, mikrotik, omada, opnsense, proxmox, snmp, unifi

DRIVERS = {"fritzbox": fritzbox, "snmp": snmp, "asuswrt": asuswrt, "proxmox": proxmox, "homeassistant": homeassistant,
           "omada": omada, "unifi": unifi, "mikrotik": mikrotik, "opnsense": opnsense, "docker": docker}
ERRORS = (fritzbox.DriverError, snmp.DriverError, asuswrt.DriverError, proxmox.DriverError, homeassistant.DriverError, controller.DriverError, mqtt.MQTTError)


def schema():
    return [dict(key=k, name=m.NAME, fields=m.FIELDS, interval=m.DEFAULT_INTERVAL) for k, m in DRIVERS.items()]
