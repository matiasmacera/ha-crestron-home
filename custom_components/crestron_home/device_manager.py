"""Device manager for Crestron Home integration."""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

from .api import CrestronApiError, CrestronClient

# Set to True to enable detailed device logging (disable in production)
DEBUG_MODE = False
from .const import (
    DEVICE_SUBTYPE_DOOR_SENSOR,
    DEVICE_SUBTYPE_OCCUPANCY_SENSOR,
    DEVICE_SUBTYPE_PHOTO_SENSOR,
    DEVICE_SUBTYPE_THERMOSTAT,
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
_CHANGE_FIELDS = ("status", "level", "position", "connection", "presence", "door_status")


class CrestronDeviceManager:
    """Manager for Crestron devices."""

    def _update_ha_parameters(self, device: CrestronDevice) -> None:
        """Update Home Assistant parameters based on device status.
        
        Logic:
        - If device is functioning normally: state = available
        - If device is offline: state = unavailable
        - If device matches an ignored pattern: hidden = true, state = N/A
        - If device type is disabled in config: hidden = true, state = N/A
        """
        
        # Get the Home Assistant device type
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
        # between /devices, /sensors, and /thermostats sharing numeric IDs.
        self.devices: Dict[str, CrestronDevice] = {}
        # Lightweight snapshot for change detection (key → tuple of field values)
        self._previous_snapshot: Dict[str, tuple] = {}
        self.last_poll_time: Optional[datetime] = None

        # Room lookup dict built once per poll (id → name), replaces linear scans
        self._room_lookup: Dict[int, str] = {}

        # Mapping of Crestron device types to Home Assistant device types
        self.device_type_mapping = {
            "Dimmer": DEVICE_TYPE_LIGHT,
            "Switch": DEVICE_TYPE_LIGHT,
            "Shade": DEVICE_TYPE_SHADE,
            "Scene": DEVICE_TYPE_SCENE,
            "OccupancySensor": DEVICE_TYPE_BINARY_SENSOR,
            "DoorSensor": DEVICE_TYPE_BINARY_SENSOR,
            "PhotoSensor": DEVICE_TYPE_SENSOR,
            "Thermostat": DEVICE_TYPE_THERMOSTAT,
        }

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
        return tuple(getattr(device, f) for f in _CHANGE_FIELDS)

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
            prev_names = {k: d.full_name for k, d in self.devices.items()}

            # Get all devices, sensors, and thermostats from the Crestron Home system
            fetch_thermostats = DEVICE_TYPE_THERMOSTAT in self.enabled_device_types

            coros = [
                self.client.get_devices(self.enabled_device_types, self.ignored_device_names),
                self.client.get_sensors(self.ignored_device_names),
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

            # Process devices
            self._process_devices(devices_data)

            # Process sensors
            self._process_sensors(sensors_data)

            # Process thermostats
            if thermostats_data:
                self._process_thermostats(thermostats_data)

            # Update last poll time
            self.last_poll_time = datetime.now()

            # Change detection using lightweight snapshots
            if prev_snapshot:
                for dev_key, device in self.devices.items():
                    prev = prev_snapshot.get(dev_key)
                    if prev is None:
                        _LOGGER.info("New device discovered: %s (key: %s)", device.full_name, dev_key)
                    elif self._device_snapshot_tuple(device) != prev:
                        _LOGGER.debug("Device changed: %s (key: %s)", device.full_name, dev_key)
                # Detect removed devices
                for dev_key in prev_snapshot:
                    if dev_key not in self.devices:
                        _LOGGER.info("Device removed: %s (key: %s)",
                                     prev_names.get(dev_key, "unknown"), dev_key)

            # Organize devices by type as dict[int, CrestronDevice] for O(1) lookups
            devices_by_type: Dict[str, Dict[int, CrestronDevice]] = {
                DEVICE_TYPE_LIGHT: {},
                DEVICE_TYPE_SHADE: {},
                DEVICE_TYPE_SCENE: {},
                DEVICE_TYPE_BINARY_SENSOR: {},
                DEVICE_TYPE_SENSOR: {},
                DEVICE_TYPE_THERMOSTAT: {},
            }

            for device in self.devices.values():
                ha_device_type = self._get_ha_device_type(device.type, device.subtype)
                if ha_device_type and ha_device_type in devices_by_type:
                    devices_by_type[ha_device_type][device.id] = device

            # Log device counts by type
            for device_type, type_devices in devices_by_type.items():
                _LOGGER.info("Found %d devices for %s platform", len(type_devices), device_type)

            # Log detailed device information if debug mode is enabled
            if DEBUG_MODE:
                self._log_device_snapshot()

            return devices_by_type

        except CrestronApiError as error:
            _LOGGER.error("Error polling devices: %s", error)
            raise

    def _process_devices(self, devices_data: List[Dict[str, Any]]) -> None:
        """Process device data from the API and update the device snapshot."""
        for device_data in devices_data:
            device_id = device_data.get("id")
            if not device_id:
                continue

            device_type = device_data.get("subType") or device_data.get("type", "")
            # Composite key avoids collisions with sensors/thermostats
            dev_key = f"device:{device_id}"

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

                device.last_updated = datetime.now()

                # Update position for shades
                if device_type == "Shade":
                    device.position = device_data.get("position", 0)

                device.raw_data = device_data
                self._update_ha_parameters(device)
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

    def _process_sensors(self, sensors_data: List[Dict[str, Any]]) -> None:
        """Process sensor data from the API and update the device snapshot."""
        for sensor_data in sensors_data:
            sensor_id = sensor_data.get("id")
            if not sensor_id:
                continue

            sensor_type = sensor_data.get("subType", "")
            # Composite key avoids collisions with devices/thermostats
            dev_key = f"sensor:{sensor_id}"

            # Get room information via O(1) lookup
            room_id = sensor_data.get("roomId")
            room_name = self._room_lookup.get(room_id, "") if room_id else ""

            # Create or update sensor
            if dev_key in self.devices:
                sensor = self.devices[dev_key]
                sensor.connection = sensor_data.get("connectionStatus", "online")
                sensor.last_updated = datetime.now()

                # Update sensor-specific properties
                if sensor_type == DEVICE_SUBTYPE_OCCUPANCY_SENSOR:
                    sensor.presence = sensor_data.get("presence", "Unavailable")
                    sensor.status = sensor_data.get("presence", "Unavailable") not in ["Vacant", "Unavailable"]
                elif sensor_type == DEVICE_SUBTYPE_DOOR_SENSOR:
                    sensor.door_status = sensor_data.get("door_status", "Closed")
                    sensor.battery_level = sensor_data.get("battery_level", "Normal")
                    sensor.status = sensor_data.get("door_status", "Closed") == "Open"
                elif sensor_type == DEVICE_SUBTYPE_PHOTO_SENSOR:
                    sensor.value = sensor_data.get("level", 0)
                    sensor.level = sensor_data.get("level", 0)

                sensor.raw_data = sensor_data
                self._update_ha_parameters(sensor)
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

                if sensor_type == DEVICE_SUBTYPE_OCCUPANCY_SENSOR:
                    sensor.presence = sensor_data.get("presence", "Unavailable")
                    sensor.status = sensor_data.get("presence", "Unavailable") not in ["Vacant", "Unavailable"]
                elif sensor_type == DEVICE_SUBTYPE_DOOR_SENSOR:
                    sensor.door_status = sensor_data.get("door_status", "Closed")
                    sensor.battery_level = sensor_data.get("battery_level", "Normal")
                    sensor.status = sensor_data.get("door_status", "Closed") == "Open"
                elif sensor_type == DEVICE_SUBTYPE_PHOTO_SENSOR:
                    sensor.value = sensor_data.get("level", 0)
                    sensor.level = sensor_data.get("level", 0)

                self.devices[dev_key] = sensor
                self._update_ha_parameters(sensor)

    def _process_thermostats(self, thermostats_data: List[Dict[str, Any]]) -> None:
        """Process thermostat data from the Crestron Home API."""
        for tstat in thermostats_data:
            tstat_id = tstat.get("id")
            if tstat_id is None:
                continue

            try:
                # Composite key avoids collisions with devices/sensors
                dev_key = f"thermostat:{tstat_id}"
                room_id = tstat.get("roomId")
                room_name = self._room_lookup.get(room_id, "") if room_id else ""

                if dev_key in self.devices:
                    device = self.devices[dev_key]
                    device.type = "Thermostat"
                    device.subtype = "Thermostat"
                    device.connection = tstat.get("connectionStatus", "online")
                    device.raw_data = tstat
                    device.last_updated = datetime.now()
                    self._update_ha_parameters(device)
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
        # Try to get from mapping
        ha_type = self.device_type_mapping.get(subtype) or self.device_type_mapping.get(device_type)
        
        # Special case for scenes
        if device_type == "Scene" or subtype == "Scene":
            return DEVICE_TYPE_SCENE
        
        return ha_type

    def _log_device_snapshot(self) -> None:
        """Log a detailed snapshot of all devices for debugging."""
        if not self.devices:
            _LOGGER.info("No devices found to log")
            return
        
        # Group devices by room for better readability
        devices_by_room: Dict[str, List[CrestronDevice]] = {}
        for device in self.devices.values():
            room_name = device.room or "Unknown Room"
            if room_name not in devices_by_room:
                devices_by_room[room_name] = []
            devices_by_room[room_name].append(device)
        
        # Log header
        _LOGGER.info("=" * 80)
        _LOGGER.info("CRESTRON DEVICE SNAPSHOT")
        _LOGGER.info("=" * 80)
        _LOGGER.info("Total devices: %d", len(self.devices))
        _LOGGER.info("Last updated: %s", self.last_poll_time.isoformat() if self.last_poll_time else "Never")
        _LOGGER.info("=" * 80)
        
        # Log devices by room
        for room_name, room_devices in sorted(devices_by_room.items()):
            _LOGGER.info("")
            _LOGGER.info("ROOM: %s (%d devices)", room_name, len(room_devices))
            _LOGGER.info("-" * 80)
            
            # Sort devices by type and name
            room_devices.sort(key=lambda d: (d.type, d.name))
            
            for device in room_devices:
                # Log basic device information
                _LOGGER.info("DEVICE: %s (ID: %d)", device.full_name, device.id)
                _LOGGER.info("  Type: %s / Subtype: %s", device.type, device.subtype)
                _LOGGER.info("  Status: %s / Level: %d", "ON" if device.status else "OFF", device.level)
                _LOGGER.info("  Connection: %s / Last Updated: %s", 
                            device.connection, device.last_updated.isoformat())
                _LOGGER.info("  Availability reason: %s / HA State: %s / HA Hidden: %s",
                            device.ha_reason or "None", device.ha_state, device.ha_hidden)
                
                # Log device-specific properties
                if device.type == "Shade" or device.subtype == "Shade":
                    _LOGGER.info("  Position: %d", device.position)
                
                if device.subtype == DEVICE_SUBTYPE_OCCUPANCY_SENSOR:
                    _LOGGER.info("  Presence: %s", device.presence)
                
                if device.subtype == DEVICE_SUBTYPE_DOOR_SENSOR:
                    _LOGGER.info("  Door Status: %s / Battery Level: %s", 
                                device.door_status, device.battery_level)
                
                if device.subtype == DEVICE_SUBTYPE_PHOTO_SENSOR:
                    _LOGGER.info("  Value: %s / Unit: %s", 
                                device.value, device.unit or "None")
                
                _LOGGER.info("-" * 80)
        
        _LOGGER.info("=" * 80)
        _LOGGER.info("END OF DEVICE SNAPSHOT")
        _LOGGER.info("=" * 80)

