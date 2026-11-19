# díktyo and Home Assistant

## Set up

1. **MQTT broker:** install the Mosquitto add-on in Home Assistant (Settings → Add-ons) and create an own user for
   díktyo (Settings → People → Users, or in the add-on configuration). The MQTT integration in Home Assistant must be
   set up (it is suggested automatically after installing the add-on).
2. **Token (optional, for names and areas):** in Home Assistant open your profile → Security → Long-lived access
   tokens → Create token.
3. In díktyo: profile → **Integrations** → **+ Home Assistant**. Enter the address of Home Assistant
   (e.g. `http://homeassistant.local:8123`), the token, the MQTT broker (address of Home Assistant, port 1883) with the
   díktyo user, and choose which devices are reported. "Test connection" checks token and MQTT sign-in.
   Enter the **IP address of Home Assistant** as MQTT broker. `core-mosquitto`, which Home Assistant shows in its own
   MQTT settings, only exists inside Home Assistant; díktyo replaces it with the address of Home Assistant
   automatically.

## What díktyo reports via MQTT (discovery)

| Entity | Content |
|---|---|
| Binary sensor "Network" per device (connectivity) | online/offline from monitoring, scans and integrations. Devices with a MAC address are attached to the existing HA device with the same MAC (for example the Shelly). |
| Sensor "New devices in the inbox" | number of devices waiting in the inbox |
| Sensor "Devices online" | number of confirmed devices online |
| Sensors "WAN download/upload" | current WAN traffic in Mbit/s (with the FRITZ!Box integration) |
| Event "Event" | `device_offline`, `device_online`, `new_device` with the attributes `device`, `ip`, `mac`, `label` |

Which devices get a binary sensor is set in the integration: infrastructure (routers, switches, access points,
servers, NAS), all confirmed devices, or none. Devices that are no longer reported are removed from Home Assistant.

## Notifications

Import the blueprint [`diktyo-benachrichtigung.yaml`](diktyo-benachrichtigung.yaml): Settings → Automations &
Scenes → Blueprints → Import blueprint, and paste the raw URL of the file
(`https://raw.githubusercontent.com/xpistaki-bit/diktyo/main/docs/home-assistant/diktyo-benachrichtigung.yaml`).
Then create an automation from it: choose the díktyo event entity, your phone and the events.

## Names and areas from Home Assistant

With the token díktyo reads all HA devices that have a MAC address and matches them with its own devices:

- **Names:** for new devices and devices whose name díktyo generated itself (hostname, guess with address), the HA
  name is taken over, e.g. "shelly1pmminig3-…" becomes "Heizung". Option "for all devices" overwrites every name.
- **Areas:** an HA area becomes the location of the device if it has none yet; missing locations are created.
