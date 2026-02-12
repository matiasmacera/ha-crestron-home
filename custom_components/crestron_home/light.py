"""Support for Crestron Home lights."""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CrestronClient
from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_SUBTYPE_DIMMER,
    DEVICE_TYPE_LIGHT,
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
    """Set up Crestron Home lights based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_LIGHT not in enabled_device_types:
        _LOGGER.debug("Light platform not enabled, skipping setup")
        return

    lights = []
    for device in coordinator.data.get(DEVICE_TYPE_LIGHT, {}).values():
        if device.type == DEVICE_SUBTYPE_DIMMER:
            light = CrestronHomeDimmer(coordinator, device)
        else:
            light = CrestronHomeLight(coordinator, device)

        if device.ha_hidden:
            light._attr_hidden_by = "integration"

        lights.append(light)

    _LOGGER.debug("Adding %d light entities", len(lights))
    async_add_entities(lights)


class CrestronHomeBaseLight(CrestronBaseEntity, LightEntity):
    """Base class for Crestron Home lights."""

    _device_type_key = DEVICE_TYPE_LIGHT
    _supports_optimistic = True

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the light."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"crestron_light_{device.id}"
        self._attr_device_class = None

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._get_device().level > 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        level = CrestronClient.percentage_to_crestron(100)

        self._mark_optimistic()
        self._crestron_device.level = level
        self._crestron_device.status = True
        self.async_write_ha_state()

        await self.coordinator.client.set_light_state(self._crestron_device.id, level)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        self._mark_optimistic()
        self._crestron_device.level = 0
        self._crestron_device.status = False
        self.async_write_ha_state()

        await self.coordinator.client.set_light_state(self._crestron_device.id, 0)


class CrestronHomeLight(CrestronHomeBaseLight):
    """Representation of a Crestron Home non-dimmable light."""

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the light."""
        super().__init__(coordinator, device)
        self._attr_color_mode = ColorMode.ONOFF
        self._attr_supported_color_modes = {ColorMode.ONOFF}


class CrestronHomeDimmer(CrestronHomeBaseLight):
    """Representation of a Crestron Home dimmable light."""

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the light."""
        super().__init__(coordinator, device)
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_supported_features = LightEntityFeature.TRANSITION

    @property
    def brightness(self) -> Optional[int]:
        """Return the brightness of the light."""
        device = self._get_device()
        return int(CrestronClient.crestron_to_percentage(device.level) * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if ATTR_BRIGHTNESS in kwargs:
            brightness_pct = kwargs[ATTR_BRIGHTNESS] / 255 * 100
            level = CrestronClient.percentage_to_crestron(brightness_pct)
        else:
            level = CrestronClient.percentage_to_crestron(100)

        transition = int(kwargs.get(ATTR_TRANSITION, 0))

        self._mark_optimistic()
        self._crestron_device.level = level
        self._crestron_device.status = True
        self.async_write_ha_state()

        # Debounce brightness slider to avoid flooding the API
        if ATTR_BRIGHTNESS in kwargs:
            self._debounce_command(
                self.coordinator.client.set_light_state,
                self._crestron_device.id, level, transition,
            )
        else:
            await self.coordinator.client.set_light_state(
                self._crestron_device.id, level, time=transition
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off with optional fade out."""
        transition = int(kwargs.get(ATTR_TRANSITION, 0))

        self._mark_optimistic()
        self._crestron_device.level = 0
        self._crestron_device.status = False
        self.async_write_ha_state()

        await self.coordinator.client.set_light_state(
            self._crestron_device.id, 0, time=transition
        )
