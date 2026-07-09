"""Device manager for Crestron Home integration."""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from homeassistant.core import HomeAssistant

from .api import CrestronApiError, CrestronClient
from .const import (
    CRESTRON_TYPE_TO_DEVICE_TYPE,
    DEVICE_SUBTYPE_DOOR_SENSOR,
    DEVICE_SUBTYPE_OCCUPANCY_SENSOR,
    DEVICE_SUBTYPE_PHOTO_SENSOR,
    DEVICE_TYPE_BINARY_SENSOR,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SCENE,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_THERMOSTAT,
)
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)

# Fields compared for change detection (avoids full deepcopy)
_CHANGE_FIELDS = (
    "status",
    "level",
    "position",
    "connection",
    "presence",
    "door_status",
    "battery_level",
    "value",
)

# Thermostat state lives in raw_data, so change detection must look there too
_THERMOSTAT_RAW_FIELDS = (
    "currentTemperature",
    "currentMode",
    "mode",
    "currentFanMode",
    "schedulerState",
    "running",
)


class CrestronDeviceManager:
    """Manager for Crestron devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: CrestronClient,
        enabled_device_types: List[str],
        ignored_device_names: Optional[List[str]] = None,
    ) -> None:
        """Initialize the device manager."""
        self.hass = hass
        self.client = client
        self.enabled_device_types = enabled_device_types
        self.ignored_device_names = ignored_device_names or []

        # Device storage – keys are composite "namespace:id" to avoid collisions
        # between /devices, /scenes, /sensors, and /thermostats sharing numeric IDs.
        self.devices: Dict[str, CrestronDevice] = {}
        self.last_poll_time: Optional[datetime] = None

        # (ha_device_type, device_id) pairs that changed in the last poll.
        # Entities use this to skip redundant state writes. None until first poll.
        self.last_changed: Optional[Set[Tuple[str, int]]] = None

        # Room lookup dict built once per poll (id → name), replaces linear scans
        self._room_lookup: Dict[int, str] = {}

    def _update_ha_parameters(self, device: CrestronDevice) -> None:
        """Update Home Assistant parameters based on device status.

        Logic:
        - If device is functioning normally: state = available
        - If device is offline: state = unavailable
        - If device matches an ignored pattern: hidden = true, state = N/A
        - If device type is disabled in config: hidden = true, state = N/A
        """
        ha_device_type = self._get_ha_device_type(device.type, device.subtype)

        # Check if device matches an ignored pattern
        if self._matches_ignored_pattern(device.full_name, device.type):
            device.ha_hidden = True    # Mark as hidden
            device.ha_state = None     # N/A
            device.ha_reason = "Device hidden by name filter"
            return

        # Check if device type is disabled in config
        if ha_device_type and ha_device_type not in self.enabled_device_types:
            device.ha_hidden = True    # Mark as hidden
            device.ha_state = None     # N/A
            device.ha_reason = "Device hidden by category filter"
            return

        # Device is not hidden
        device.ha_hidden = False

        # Check connection status for availability
        if device.connection == "offline":
            device.ha_state = False  # Unavailable
            device.ha_reason = "Device is offline"
        else:
            device.ha_state = True  # Available
            device.ha_reason = ""  # No reason needed for normal operation

    def _matches_ignored_pattern(self, name: str, device_type: str) -> bool:
        """Check if a device name or type matches any of the ignored patterns.

        Supports pattern matching with % wildcard:
        - bathroom → exact match
        - %bathroom → ends with bathroom
        - bathroom% → starts with bathroom
        - %bathroom% → contains bathroom
        """
        if not self.ignored_device_names:
            return False

        name = name.lower()
        device_type = device_type.lower()

        for pattern in self.ignored_device_names:
            pattern = pattern.lower()

            # Check for different pattern types
            if pattern.startswith("%") and pattern.endswith("%"):
                # %bathroom% → contains bathroom
                search_term = pattern[1:-1]
                if search_term in name or search_term in device_type:
                    return True
            elif pattern.startswith("%"):
                # %bathroom → ends with bathroom
                if name.endswith(pattern[1:]) or device_type.endswith(pattern[1:]):
                    return True
            elif pattern.endswith("%"):
                # bathroom% → starts with bathroom
                if name.startswith(pattern[:-1]) or device_type.startswith(pattern[:-1]):
                    return True
            else:
                # bathroom → exact match
                if name == pattern or device_type == pattern:
                    return True

        return False

    @staticmethod
    def _device_snapshot_tuple(device: CrestronDevice) -> tuple:
        """Return a lightweight tuple of fields used for change detection."""
        snapshot = tuple(getattr(device, f) for f in _CHANGE_FIELDS)
        if device.type == "Thermostat":
            rd = device.raw_data
            snapshot += tuple(rd.get(f) for f in _THERMOSTAT_RAW_FIELDS)
            # Setpoints are nested lists/dicts: compare their string form
            snapshot += (str(rd.get("currentSetPoint") or rd.get("setPoint")),)
        return snapshot

    async def poll_devices(self) -> Dict[str, Dict[int, CrestronDevice]]:
        """Poll devices from the Crestron Home system and update the device snapshot."""
        try:
            _LOGGER.debug(
                "Polling devices with enabled types: %s, ignored names: %s",
                self.enabled_device_types,
                self.ignored_device_names
            )

            # Save lightweight snapshot for change detection (no deepcopy)
            prev_snapshot = {
                k: self._device_snapshot_tuple(d) for k, d in self.devices.items()
            }

            # Get all devices, sensors, and thermostats from the Crestron Home system
            fetch_thermostats = DEVICE_TYPE_THERMOSTAT in self.enabled_device_types

            coros = [
                self.client.get_devices(),
                self.client.get_sensors(),
            ]
            if fetch_thermostats:
                coros.append(self.client.get_thermostats())

            results = await asyncio.gather(*coros)

            devices_data = results[0]
            sensors_data = results[1]
            thermostats_data = results[2] if fetch_thermostats else []

            _LOGGER.debug("Received %d devices, %d sensors, and %d thermostats from API",
                         len(devices_data), len(sensors_data), len(thermostats_data))

            # Build room lookup dict for O(1) room name resolution
            self._room_lookup = {
                r.get("id"): r.get("name", "") for r in self.client.rooms
            }

            # Single timestamp per poll instead of datetime.now() per device
            now = datetime.now()

            # Keys seen in this poll: anything previously known but no longer
            # reported gets pruned below, so entities go unavailable instead of
            # showing stale state forever.
            seen: Set[str] = set()

            self._process_devices(devices_data, now, seen)
            self._process_sensors(sensors_data, now, seen)
            if thermostats_data:
                self._process_thermostats(thermostats_data, now, seen)

            # Prune devices that disappeared, but only within namespaces that
            # were actually polled (thermostats are conditional) AND whose
            # raw fetch this poll wasn't suspiciously empty. api.py silently
            # returns [] for a malformed/unexpected-shape HTTP-200 body, so a
            # single bad response must not be read as "the user deleted every
            # device" and mass-prune a whole namespace.
            known_namespaces = {k.split(":", 1)[0] for k in self.devices}
            polled_namespaces = {"device", "scene", "sensor"}
            if fetch_thermostats:
                polled_namespaces.add("thermostat")

            if not devices_data and known_namespaces & {"device", "scene"}:
                _LOGGER.warning(
                    "Devices/scenes API returned no results this poll but "
                    "devices were previously known; skipping pruning for "
                    "devices and scenes this poll"
                )
                polled_namespaces -= {"device", "scene"}
            if not sensors_data and "sensor" in known_namespaces:
                _LOGGER.warning(
                    "Sensors API returned no results this poll but sensors "
                    "were previously known; skipping pruning for sensors "
                    "this poll"
                )
                polled_namespaces.discard("sensor")
            if fetch_thermostats and not thermostats_data and "thermostat" in known_namespaces:
                _LOGGER.warning(
                    "Thermostats API returned no results this poll but "
                    "thermostats were previously known; skipping pruning for "
                    "thermostats this poll"
                )
                polled_namespaces.discard("thermostat")

            stale_keys = [
                k for k in self.devices
                if k not in seen and k.split(":", 1)[0] in polled_namespaces
            ]
            for dev_key in stale_keys:
                _LOGGER.info(
                    "Device removed from Crestron: %s (key: %s)",
                    self.devices[dev_key].full_name, dev_key,
                )
                del self.devices[dev_key]

            self.last_poll_time = now

            # Change detection using lightweight snapshots
            changed_keys: Set[str] = set()
            for dev_key, device in self.devices.items():
                prev = prev_snapshot.get(dev_key)
                if prev is None:
                    changed_keys.add(dev_key)
                    if prev_snapshot:
                        _LOGGER.info(
                            "New device discovered: %s (key: %s)",
                            device.full_name, dev_key,
                        )
                elif self._device_snapshot_tuple(device) != prev:
                    changed_keys.add(dev_key)
                    _LOGGER.debug("Device changed: %s (key: %s)", device.full_name, dev_key)

            # Organize devices by type as dict[int, CrestronDevice] for O(1) lookups,
            # and expose the changed set as (ha_device_type, id) pairs for entities.
            devices_by_type: Dict[str, Dict[int, CrestronDevice]] = {
                DEVICE_TYPE_LIGHT: {},
                DEVICE_TYPE_SHADE: {},
                DEVICE_TYPE_SCENE: {},
                DEVICE_TYPE_BINARY_SENSOR: {},
                DEVICE_TYPE_SENSOR: {},
                DEVICE_TYPE_THERMOSTAT: {},
            }
            changed: Set[Tuple[str, int]] = set()

            for dev_key, device in self.devices.items():
                ha_device_type = self._get_ha_device_type(device.type, device.subtype)
                if ha_device_type and ha_device_type in devices_by_type:
                    devices_by_type[ha_device_type][device.id] = device
                    if dev_key in changed_keys:
                        changed.add((ha_device_type, device.id))

            self.last_changed = changed

            _LOGGER.debug(
                "Devices per platform: %s (%d changed)",
                {t: len(d) for t, d in devices_by_type.items()},
                len(changed),
            )

            return devices_by_type

        except CrestronApiError as error:
            _LOGGER.error("Error polling devices: %s", error)
            raise

    def _process_devices(
        self, devices_data: List[Dict[str, Any]], now: datetime, seen: Set[str]
    ) -> None:
        """Process device and scene data from the API and update the snapshot."""
        for device_data in devices_data:
            device_id = device_data.get("id")
            if not device_id:
                continue

            device_type = device_data.get("subType") or device_data.get("type", "")
            # Scenes come from /scenes with their own ID space: separate namespace
            namespace = "scene" if device_type == "Scene" else "device"
            dev_key = f"{namespace}:{device_id}"
            seen.add(dev_key)

            # Get room information
            room_id = device_data.get("roomId")
            room_name = device_data.get("roomName", "")

            # Create or update device
            if dev_key in self.devices:
                # Update existing device
                device = self.devices[dev_key]
                device.status = device_data.get("status", False)
                device.level = device_data.get("level", 0)

                # Scenes don't have a physical connection status
                if device_type == "Scene":
                    device.connection = "n/a"
                else:
                    device.connection = device_data.get("connectionStatus", "online")

                device.last_updated = now

                # Update position for shades
                if device_type == "Shade":
                    device.position = device_data.get("position", 0)

                device.raw_data = device_data
            else:
                connection_status = "n/a" if device_type == "Scene" else device_data.get("connectionStatus", "online")

                device = CrestronDevice(
                    id=device_id,
                    room=room_name,
                    name=device_data.get("name", ""),
                    type=device_type,
                    subtype=device_type,
                    status=device_data.get("status", False),
                    level=device_data.get("level", 0),
                    connection=connection_status,
                    room_id=room_id,
                    position=device_data.get("position", 0) if device_type == "Shade" else 0,
                    raw_data=device_data,
                )
                self.devices[dev_key] = device

            self._update_ha_parameters(device)

    @staticmethod
    def _apply_sensor_state(sensor: CrestronDevice, sensor_data: Dict[str, Any], sensor_type: str) -> None:
        """Apply subtype-specific state from raw sensor data."""
        if sensor_type == DEVICE_SUBTYPE_OCCUPANCY_SENSOR:
            presence = sensor_data.get("presence", "Unavailable")
            sensor.presence = presence
            sensor.status = presence not in ("Vacant", "Unavailable")
        elif sensor_type == DEVICE_SUBTYPE_DOOR_SENSOR:
            door_status = sensor_data.get("door_status", "Closed")
            sensor.door_status = door_status
            sensor.battery_level = sensor_data.get("battery_level", "Normal")
            sensor.status = door_status == "Open"
        elif sensor_type == DEVICE_SUBTYPE_PHOTO_SENSOR:
            level = sensor_data.get("level", 0)
            sensor.value = level
            sensor.level = level

    def _process_sensors(
        self, sensors_data: List[Dict[str, Any]], now: datetime, seen: Set[str]
    ) -> None:
        """Process sensor data from the API and update the device snapshot."""
        for sensor_data in sensors_data:
            sensor_id = sensor_data.get("id")
            if not sensor_id:
                continue

            sensor_type = sensor_data.get("subType", "")
            # Composite key avoids collisions with devices/scenes/thermostats
            dev_key = f"sensor:{sensor_id}"
            seen.add(dev_key)

            # Get room information via O(1) lookup
            room_id = sensor_data.get("roomId")
            room_name = self._room_lookup.get(room_id, "") if room_id else ""

            # Create or update sensor
            if dev_key in self.devices:
                sensor = self.devices[dev_key]
                sensor.connection = sensor_data.get("connectionStatus", "online")
                sensor.last_updated = now
                sensor.raw_data = sensor_data
            else:
                sensor = CrestronDevice(
                    id=sensor_id,
                    room=room_name,
                    name=sensor_data.get("name", ""),
                    type=sensor_type,
                    subtype=sensor_type,
                    connection=sensor_data.get("connectionStatus", "online"),
                    room_id=room_id,
                    raw_data=sensor_data,
                )
                self.devices[dev_key] = sensor

            self._apply_sensor_state(sensor, sensor_data, sensor_type)
            self._update_ha_parameters(sensor)

    def _process_thermostats(
        self, thermostats_data: List[Dict[str, Any]], now: datetime, seen: Set[str]
    ) -> None:
        """Process thermostat data from the Crestron Home API."""
        for tstat in thermostats_data:
            tstat_id = tstat.get("id")
            if tstat_id is None:
                continue

            try:
                # Composite key avoids collisions with devices/scenes/sensors
                dev_key = f"thermostat:{tstat_id}"
                seen.add(dev_key)
                room_id = tstat.get("roomId")
                room_name = self._room_lookup.get(room_id, "") if room_id else ""

                if dev_key in self.devices:
                    device = self.devices[dev_key]
                    device.connection = tstat.get("connectionStatus", "online")
                    device.raw_data = tstat
                    device.last_updated = now
                else:
                    device = CrestronDevice(
                        id=tstat_id,
                        room=room_name,
                        name=tstat.get("name", "Thermostat"),
                        type="Thermostat",
                        subtype="Thermostat",
                        connection=tstat.get("connectionStatus", "online"),
                        room_id=room_id,
                        raw_data=tstat,
                    )
                    self.devices[dev_key] = device

                self._update_ha_parameters(device)

                _LOGGER.debug(
                    "Processed thermostat: %s (ID: %s, Mode: %s, Temp: %s)",
                    device.full_name, tstat_id,
                    tstat.get("currentMode") or tstat.get("mode", "unknown"),
                    tstat.get("currentTemperature", "unknown"),
                )
            except Exception as ex:
                _LOGGER.error("Error processing thermostat id=%s: %s", tstat_id, ex)

    def _get_ha_device_type(self, device_type: str, subtype: str) -> Optional[str]:
        """Map Crestron device type to Home Assistant device type."""
        return (
            CRESTRON_TYPE_TO_DEVICE_TYPE.get(subtype)
            or CRESTRON_TYPE_TO_DEVICE_TYPE.get(device_type)
        )
