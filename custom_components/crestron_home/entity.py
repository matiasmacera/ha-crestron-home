"""Entity base classes for Crestron Home integration."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)

# Seconds to ignore coordinator updates after a command
OPTIMISTIC_COOLDOWN = 2.0

# Debounce delay for slider-type commands (brightness, position)
COMMAND_DEBOUNCE_SECONDS = 0.2


class CrestronBaseEntity(CoordinatorEntity):
    """Base entity for all Crestron Home entities.

    Absorbs the boilerplate that was duplicated across every platform:
    - Device/entity setup (unique_id, name, device_info)
    - _get_device() with O(1) coordinator lookup
    - async_added_to_hass() with hidden entity handling
    - _handle_coordinator_update() with optimistic cooldown
    - Command debouncing for slider-type controls
    """

    # Subclasses must set this to the device-type key used in coordinator.data
    _device_type_key: str = ""
    # Subclasses that send commands should set True to enable optimistic cooldown
    _supports_optimistic: bool = False

    def __init__(self, coordinator, device: CrestronDevice) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        # Renamed from _device_info to _crestron_device to avoid shadowing HA's _attr_device_info
        self._crestron_device = device
        self._attr_unique_id = f"crestron_{self._device_type_key}_{device.id}"
        self._attr_name = device.full_name
        self._attr_has_entity_name = False
        self._last_command_time: float = 0.0

        # Debounce state
        self._pending_debounce: Optional[asyncio.TimerHandle] = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device.id))},
            name=device.full_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            via_device=(DOMAIN, coordinator.client.host),
            suggested_area=device.room,
        )

    @property
    def room_id(self) -> Optional[int]:
        """Return the room ID for this entity."""
        return self._crestron_device.room_id

    def _get_device(self) -> CrestronDevice:
        """Get the latest device data from coordinator via O(1) dict lookup."""
        device = self.coordinator.data.get(self._device_type_key, {}).get(
            self._crestron_device.id
        )
        return device if device is not None else self._crestron_device

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_device().is_available

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        if self._crestron_device.ha_hidden:
            entity_registry = async_get_entity_registry(self.hass)
            if entity_registry.async_get(self.entity_id):
                entity_registry.async_update_entity(
                    self.entity_id, hidden_by="integration"
                )

    def _mark_optimistic(self) -> None:
        """Record that a command was just sent (for optimistic cooldown)."""
        self._last_command_time = time.monotonic()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self._supports_optimistic
            and time.monotonic() - self._last_command_time < OPTIMISTIC_COOLDOWN
        ):
            return

        device = self.coordinator.data.get(self._device_type_key, {}).get(
            self._crestron_device.id
        )
        if device is not None:
            self._crestron_device = device
        self.async_write_ha_state()

    def _debounce_command(self, coro_factory, *args) -> None:
        """Schedule a command with debouncing for slider-type controls.

        Cancels any pending debounced call and schedules a new one after
        COMMAND_DEBOUNCE_SECONDS. The caller should still do the optimistic
        state update synchronously before calling this.
        """
        if self._pending_debounce is not None:
            self._pending_debounce.cancel()

        async def _fire():
            try:
                await coro_factory(*args)
            except Exception:
                _LOGGER.exception("Debounced command failed")

        loop = self.hass.loop
        self._pending_debounce = loop.call_later(
            COMMAND_DEBOUNCE_SECONDS,
            lambda: self.hass.async_create_task(_fire()),
        )
