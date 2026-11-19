"""Treiber für Integrationen. Jeder Treiber hat NAME, FIELDS, DEFAULT_INTERVAL, test(conf) und poll(conf, state)."""
from . import fritzbox, snmp

DRIVERS = {"fritzbox": fritzbox, "snmp": snmp}
ERRORS = (fritzbox.DriverError, snmp.DriverError)


def schema():
    return [dict(key=k, name=m.NAME, fields=m.FIELDS, interval=m.DEFAULT_INTERVAL) for k, m in DRIVERS.items()]
