"""Support for Crestron Home binary sensors."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

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
from .entity import CrestronBaseEntity, async_setup_platform_entities
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

    def _create_binary_sensor(
        coordinator, device: CrestronDevice
    ) -> Optional[CrestronBaseEntity]:
        if device.subtype == DEVICE_SUBTYPE_OCCUPANCY_SENSOR:
            return CrestronHomeOccupancySensor(coordinator, device)
        if device.subtype == DEVICE_SUBTYPE_DOOR_SENSOR:
            return CrestronHomeDoorSensor(coordinator, device)
        return None

    async_setup_platform_entities(
        entry,
        coordinator,
        async_add_entities,
        DEVICE_TYPE_BINARY_SENSOR,
        _create_binary_sensor,
    )


class CrestronHomeBinarySensor(CrestronBaseEntity, BinarySensorEntity):
    """Base class for Crestron Home binary sensors."""

    _device_type_key = DEVICE_TYPE_BINARY_SENSOR


class CrestronHomeOccupancySensor(CrestronHomeBinarySensor):
    """Representation of a Crestron Home occupancy sensor."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        device = self._get_device()
        return device.presence not in (PRESENCE_VACANT, PRESENCE_UNAVAILABLE)


class CrestronHomeDoorSensor(CrestronHomeBinarySensor):
    """Representation of a Crestron Home door sensor."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

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
