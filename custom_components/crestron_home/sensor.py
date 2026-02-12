"""Support for Crestron Home sensors."""
from __future__ import annotations

import logging

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
from .entity import CrestronBaseEntity
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

    sensors = []
    for device in coordinator.data.get(DEVICE_TYPE_SENSOR, {}).values():
        if device.subtype == DEVICE_SUBTYPE_PHOTO_SENSOR:
            sensor = CrestronHomePhotoSensor(coordinator, device)
            if device.ha_hidden:
                sensor._attr_hidden_by = "integration"
            sensors.append(sensor)

    _LOGGER.debug("Adding %d sensor entities", len(sensors))
    async_add_entities(sensors)


class CrestronHomeSensor(CrestronBaseEntity, SensorEntity):
    """Base class for Crestron Home sensors."""

    _device_type_key = DEVICE_TYPE_SENSOR

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"crestron_sensor_{device.id}"


class CrestronHomePhotoSensor(CrestronHomeSensor):
    """Representation of a Crestron Home photosensor."""

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the photosensor."""
        super().__init__(coordinator, device)
        self._attr_device_class = SensorDeviceClass.ILLUMINANCE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = LIGHT_LUX

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        device = self._get_device()
        return float(device.value or device.level or 0)
