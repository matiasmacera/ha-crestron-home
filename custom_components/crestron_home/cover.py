"""Support for Crestron Home covers (shades)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_PICTURE, Platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CrestronClient
from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_SUBTYPE_SHADE,
    DEVICE_TYPE_SHADE,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .coordinator import CrestronHomeDataUpdateCoordinator
from .entity import CrestronRoomEntity
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron Home covers based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Check if shade platform is enabled
    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_SHADE not in enabled_device_types:
        _LOGGER.debug("Shade platform not enabled, skipping setup")
        return
    
    # Get all shade devices from the coordinator
    covers = []
    
    for device in coordinator.data.get(DEVICE_TYPE_SHADE, {}).values():
        cover = CrestronHomeShade(coordinator, device)

        # Set hidden_by if device is marked as hidden
        if device.ha_hidden:
            cover._attr_hidden_by = "integration"

        covers.append(cover)
    
    _LOGGER.debug("Adding %d cover entities", len(covers))
    async_add_entities(covers)


class CrestronHomeShade(CrestronRoomEntity, CoordinatorEntity, CoverEntity):
    """Representation of a Crestron Home shade."""

    def __init__(
        self,
        coordinator: CrestronHomeDataUpdateCoordinator,
        device: CrestronDevice,
    ) -> None:
        """Initialize the shade."""
        super().__init__(coordinator)
        self._device_info = device  # Store as _device_info for CrestronRoomEntity
        self._device = device  # Keep _device for backward compatibility
        self._attr_unique_id = f"crestron_shade_{device.id}"
        self._attr_name = device.full_name
        self._attr_has_entity_name = False
        self._attr_device_class = CoverDeviceClass.SHADE
        
        # Support open, close, stop, and position
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device.id))},
            name=device.full_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            via_device=(DOMAIN, coordinator.client.host),
            suggested_area=device.room,
        )
    
    def _get_device(self) -> CrestronDevice:
        """Get the latest device data from coordinator via O(1) dict lookup."""
        device = self.coordinator.data.get(DEVICE_TYPE_SHADE, {}).get(self._device.id)
        return device if device is not None else self._device

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_device().is_available

    @property
    def current_cover_position(self) -> int:
        """Return current position of cover.

        0 is closed, 100 is fully open.
        """
        return CrestronClient.crestron_to_percentage(self._get_device().position)

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self.current_cover_position == 0

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        target = CrestronClient.percentage_to_crestron(100)
        self._device.position = target
        self.async_write_ha_state()

        await self.coordinator.client.set_shade_position(self._device.id, target)
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._device.position = 0
        self.async_write_ha_state()

        await self.coordinator.client.set_shade_position(self._device.id, 0)
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover by fetching the real-time position from the API."""
        try:
            shade_data = await self.coordinator.client.get_shade_state(self._device.id)
            current_raw = shade_data.get("position", self._device.position)
        except Exception:
            current_raw = self._device.position

        await self.coordinator.client.set_shade_position(self._device.id, current_raw)
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        if ATTR_POSITION in kwargs:
            position = kwargs[ATTR_POSITION]
            target = CrestronClient.percentage_to_crestron(position)
            self._device.position = target
            self.async_write_ha_state()

            await self.coordinator.client.set_shade_position(self._device.id, target)
            await self.coordinator.async_request_refresh()

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        
        # Ensure hidden status is properly registered in the entity registry
        if self._device.ha_hidden:
            entity_registry = async_get_entity_registry(self.hass)
            if entry := entity_registry.async_get(self.entity_id):
                entity_registry.async_update_entity(
                    self.entity_id, 
                    hidden_by="integration"
                )
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        device = self.coordinator.data.get(DEVICE_TYPE_SHADE, {}).get(self._device.id)
        if device is not None:
            self._device = device
            self._device_info = device
        self.async_write_ha_state()
