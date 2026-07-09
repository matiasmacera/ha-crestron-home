"""Entity base classes for Crestron Home integration."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)

# Seconds to ignore coordinator updates after a command
OPTIMISTIC_COOLDOWN = 2.0

# Debounce delay for slider-type commands (brightness, position)
COMMAND_DEBOUNCE_SECONDS = 0.2


def async_setup_platform_entities(
    entry: ConfigEntry,
    coordinator,
    async_add_entities: AddEntitiesCallback,
    device_type_key: str,
    entity_factory: Callable[[Any, CrestronDevice], Optional["CrestronBaseEntity"]],
) -> None:
    """Add entities for current devices and hot-add newly discovered ones.

    Shared by all platforms: adds every device present in coordinator data now,
    then listens for coordinator updates so devices added to Crestron later show
    up without restarting Home Assistant. The factory may return None for
    subtypes the platform doesn't support.
    """
    known_ids: set[int] = set()

    @callback
    def _async_add_entities() -> None:
        new_entities = []
        for device in coordinator.data.get(device_type_key, {}).values():
            if device.id in known_ids:
                continue
            known_ids.add(device.id)

            entity = entity_factory(coordinator, device)
            if entity is not None:
                new_entities.append(entity)

        if new_entities:
            _LOGGER.debug(
                "Adding %d %s entities", len(new_entities), device_type_key
            )
            async_add_entities(new_entities)

    _async_add_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class CrestronBaseEntity(CoordinatorEntity):
    """Base entity for all Crestron Home entities.

    Absorbs the boilerplate that was duplicated across every platform:
    - Device/entity setup (unique_id, name, device_info, hidden handling)
    - _get_device() with O(1) coordinator lookup
    - Availability combining coordinator health + device connection
    - _handle_coordinator_update() with optimistic cooldown and skipping
      state writes for devices that didn't change in the last poll
    - Command debouncing for slider-type controls
    """

    # Subclasses must set this to the device-type key used in coordinator.data
    _device_type_key: str = ""
    # Subclasses that send commands should set True to enable optimistic cooldown
    _supports_optimistic: bool = False

    def __init__(self, coordinator, device: CrestronDevice) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._crestron_device = device
        self._attr_unique_id = f"crestron_{self._device_type_key}_{device.id}"
        self._attr_name = device.full_name
        self._attr_has_entity_name = False
        self._last_command_time: float = 0.0
        # Success state at the time of the last state write (None = never written)
        self._last_write_success: Optional[bool] = None

        # Debounce state
        self._pending_debounce: Optional[asyncio.TimerHandle] = None

        # Register filtered devices as hidden (canonical HA mechanism; applies
        # on first registration — async_added_to_hass handles existing entries)
        if device.ha_hidden:
            self._attr_entity_registry_visible_default = False

        # Identifiers are namespaced by device type: scenes/sensors/thermostats
        # come from separate API endpoints with independent numeric ID spaces,
        # so a bare ID would merge unrelated devices in the HA registry.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._device_type_key}_{device.id}")},
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
        data = self.coordinator.data or {}
        device = data.get(self._device_type_key, {}).get(self._crestron_device.id)
        return device if device is not None else self._crestron_device

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Unavailable when the coordinator can't reach the processor, when the
        device is no longer reported by the API, or when it is offline.
        """
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data or {}
        device = data.get(self._device_type_key, {}).get(self._crestron_device.id)
        if device is None:
            return False
        return device.is_available

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        if self._crestron_device.ha_hidden:
            entity_registry = async_get_entity_registry(self.hass)
            if entity_registry.async_get(self.entity_id):
                entity_registry.async_update_entity(
                    self.entity_id, hidden_by="integration"
                )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending debounced command when the entity is removed."""
        if self._pending_debounce is not None:
            self._pending_debounce.cancel()
            self._pending_debounce = None
        await super().async_will_remove_from_hass()

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

        success = self.coordinator.last_update_success
        data = self.coordinator.data or {}
        device = data.get(self._device_type_key, {}).get(self._crestron_device.id)
        if device is not None:
            self._crestron_device = device

        # Skip the state write when the coordinator is healthy (now and at the
        # last write) and this specific device didn't change in the last poll.
        changed = self.coordinator.device_manager.last_changed
        if (
            success
            and self._last_write_success is True
            and device is not None
            and changed is not None
            and (self._device_type_key, self._crestron_device.id) not in changed
        ):
            return

        self._last_write_success = success
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
