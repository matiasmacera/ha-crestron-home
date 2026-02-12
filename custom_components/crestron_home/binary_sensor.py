"""Support for Crestron Home binary sensors."""
from __future__ import annotations

import logging
from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_SUBTYPE_DOOR_SENSOR,
    DEVICE_SUBTYPE_OCCUPANCY_SENSOR,
    DEVICE_TYPE_BINARY_SENSOR,
    DOOR_STATUS_OPEN,
    DOMAIN,
    PRESENCE_UNAVAILABLE,
    PRESENCE_VACANT,
)
from .coordinator import CrestronHomeDataUpdateCoordinator
from .entity import CrestronBaseEntity
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron Home binary sensors based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_BINARY_SENSOR not in enabled_device_types:
        _LOGGER.debug("Binary sensor platform not enabled, skipping setup")
        return

    binary_sensors = []
    for device in coordinator.data.get(DEVICE_TYPE_BINARY_SENSOR, {}).values():
        if device.subtype == DEVICE_SUBTYPE_OCCUPANCY_SENSOR:
            sensor = CrestronHomeOccupancySensor(coordinator, device)
        elif device.subtype == DEVICE_SUBTYPE_DOOR_SENSOR:
            sensor = CrestronHomeDoorSensor(coordinator, device)
        else:
            continue

        if device.ha_hidden:
            sensor._attr_hidden_by = "integration"

        binary_sensors.append(sensor)

    _LOGGER.debug("Adding %d binary sensor entities", len(binary_sensors))
    async_add_entities(binary_sensors)


class CrestronHomeBinarySensor(CrestronBaseEntity, BinarySensorEntity):
    """Base class for Crestron Home binary sensors."""

    _device_type_key = DEVICE_TYPE_BINARY_SENSOR

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"crestron_binary_sensor_{device.id}"


class CrestronHomeOccupancySensor(CrestronHomeBinarySensor):
    """Representation of a Crestron Home occupancy sensor."""

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the occupancy sensor."""
        super().__init__(coordinator, device)
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        device = self._get_device()
        return device.presence not in (PRESENCE_VACANT, PRESENCE_UNAVAILABLE)


class CrestronHomeDoorSensor(CrestronHomeBinarySensor):
    """Representation of a Crestron Home door sensor."""

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the door sensor."""
        super().__init__(coordinator, device)
        self._attr_device_class = BinarySensorDeviceClass.DOOR

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on (door is open)."""
        return self._get_device().door_status == DOOR_STATUS_OPEN

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        device = self._get_device()
        attributes = {}
        if device.battery_level:
            attributes["battery_level"] = device.battery_level
        return attributes
