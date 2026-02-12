"""Support for Crestron Home covers (shades)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CrestronClient
from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_TYPE_SHADE,
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
    """Set up Crestron Home covers based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_SHADE not in enabled_device_types:
        _LOGGER.debug("Shade platform not enabled, skipping setup")
        return

    covers = []
    for device in coordinator.data.get(DEVICE_TYPE_SHADE, {}).values():
        cover = CrestronHomeShade(coordinator, device)
        if device.ha_hidden:
            cover._attr_hidden_by = "integration"
        covers.append(cover)

    _LOGGER.debug("Adding %d cover entities", len(covers))
    async_add_entities(covers)


class CrestronHomeShade(CrestronBaseEntity, CoverEntity):
    """Representation of a Crestron Home shade."""

    _device_type_key = DEVICE_TYPE_SHADE
    _supports_optimistic = True

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the shade."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"crestron_shade_{device.id}"
        self._attr_device_class = CoverDeviceClass.SHADE
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

    @property
    def current_cover_position(self) -> int:
        """Return current position of cover. 0 is closed, 100 is fully open."""
        return CrestronClient.crestron_to_percentage(self._get_device().position)

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self.current_cover_position == 0

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        target = CrestronClient.percentage_to_crestron(100)
        self._mark_optimistic()
        self._crestron_device.position = target
        self.async_write_ha_state()

        await self.coordinator.client.set_shade_position(self._crestron_device.id, target)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._mark_optimistic()
        self._crestron_device.position = 0
        self.async_write_ha_state()

        await self.coordinator.client.set_shade_position(self._crestron_device.id, 0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover by fetching the real-time position from the API."""
        try:
            shade_data = await self.coordinator.client.get_shade_state(self._crestron_device.id)
            current_raw = shade_data.get("position", self._crestron_device.position)
        except Exception:
            current_raw = self._crestron_device.position

        await self.coordinator.client.set_shade_position(self._crestron_device.id, current_raw)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        if ATTR_POSITION in kwargs:
            position = kwargs[ATTR_POSITION]
            target = CrestronClient.percentage_to_crestron(position)
            self._mark_optimistic()
            self._crestron_device.position = target
            self.async_write_ha_state()

            # Debounce position slider
            self._debounce_command(
                self.coordinator.client.set_shade_position,
                self._crestron_device.id, target,
            )
