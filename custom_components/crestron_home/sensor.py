"""Support for Crestron Home sensors."""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import LIGHT_LUX
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_SUBTYPE_PHOTO_SENSOR,
    DEVICE_TYPE_SENSOR,
    DOMAIN,
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
    """Set up Crestron Home sensors based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_SENSOR not in enabled_device_types:
        _LOGGER.debug("Sensor platform not enabled, skipping setup")
        return

    def _create_sensor(
        coordinator, device: CrestronDevice
    ) -> Optional[CrestronBaseEntity]:
        if device.subtype == DEVICE_SUBTYPE_PHOTO_SENSOR:
            return CrestronHomePhotoSensor(coordinator, device)
        return None

    async_setup_platform_entities(
        entry, coordinator, async_add_entities, DEVICE_TYPE_SENSOR, _create_sensor
    )


class CrestronHomeSensor(CrestronBaseEntity, SensorEntity):
    """Base class for Crestron Home sensors."""

    _device_type_key = DEVICE_TYPE_SENSOR


class CrestronHomePhotoSensor(CrestronHomeSensor):
    """Representation of a Crestron Home photosensor."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        device = self._get_device()
        return float(device.value or device.level or 0)
