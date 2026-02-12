"""Support for Crestron Home scenes."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_TYPE_SCENE,
    DOMAIN,
    MANUFACTURER,
    MODEL,
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
    """Set up Crestron Home scenes based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_SCENE not in enabled_device_types:
        _LOGGER.debug("Scene platform not enabled, skipping setup")
        return

    scenes = []
    for device in coordinator.data.get(DEVICE_TYPE_SCENE, {}).values():
        scene = CrestronHomeScene(coordinator, device)
        if device.ha_hidden:
            scene._attr_hidden_by = "integration"
        scenes.append(scene)

    _LOGGER.debug("Adding %d scene entities", len(scenes))
    async_add_entities(scenes)


class CrestronHomeScene(CrestronBaseEntity, Scene):
    """Representation of a Crestron Home scene."""

    _device_type_key = DEVICE_TYPE_SCENE

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the scene."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"crestron_scene_{device.id}"

        scene_type = device.raw_data.get("sceneType", "")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device.id))},
            name=device.full_name,
            manufacturer=MANUFACTURER,
            model=f"{MODEL} {scene_type}",
            via_device=(DOMAIN, coordinator.client.host),
            suggested_area=device.room,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available (check coordinator is connected)."""
        return self.coordinator.last_update_success

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self.coordinator.client.execute_scene(self._crestron_device.id)
        await self.coordinator.async_request_refresh()
