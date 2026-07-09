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

from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    CRESTRON_MAX_LEVEL,
    DEVICE_SUBTYPE_DIMMER,
    DEVICE_TYPE_LIGHT,
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
    """Set up Crestron Home lights based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_LIGHT not in enabled_device_types:
        _LOGGER.debug("Light platform not enabled, skipping setup")
        return

    def _create_light(coordinator, device: CrestronDevice) -> CrestronBaseEntity:
        if device.type == DEVICE_SUBTYPE_DIMMER:
            return CrestronHomeDimmer(coordinator, device)
        return CrestronHomeLight(coordinator, device)

    async_setup_platform_entities(
        entry, coordinator, async_add_entities, DEVICE_TYPE_LIGHT, _create_light
    )


class CrestronHomeBaseLight(CrestronBaseEntity, LightEntity):
    """Base class for Crestron Home lights."""

    _device_type_key = DEVICE_TYPE_LIGHT
    _supports_optimistic = True

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._get_device().level > 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        self._mark_optimistic()
        self._crestron_device.level = CRESTRON_MAX_LEVEL
        self._crestron_device.status = True
        self.async_write_ha_state()

        await self.coordinator.client.set_light_state(
            self._crestron_device.id, CRESTRON_MAX_LEVEL
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        self._mark_optimistic()
        self._crestron_device.level = 0
        self._crestron_device.status = False
        self.async_write_ha_state()

        await self.coordinator.client.set_light_state(self._crestron_device.id, 0)


class CrestronHomeLight(CrestronHomeBaseLight):
    """Representation of a Crestron Home non-dimmable light."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}


class CrestronHomeDimmer(CrestronHomeBaseLight):
    """Representation of a Crestron Home dimmable light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.TRANSITION

    @property
    def brightness(self) -> Optional[int]:
        """Return the brightness of the light.

        Direct 0-65535 → 0-255 conversion (65535/255 is exactly 257, so the
        roundtrip with async_turn_on is lossless and the slider doesn't drift).
        """
        return round(self._get_device().level * 255 / CRESTRON_MAX_LEVEL)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if ATTR_BRIGHTNESS in kwargs:
            level = round(kwargs[ATTR_BRIGHTNESS] * CRESTRON_MAX_LEVEL / 255)
        else:
            level = CRESTRON_MAX_LEVEL

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
