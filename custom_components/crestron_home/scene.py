"""Support for Crestron Home scenes."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_TYPE_SCENE,
    DOMAIN,
    MODEL,
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
    """Set up Crestron Home scenes based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_SCENE not in enabled_device_types:
        _LOGGER.debug("Scene platform not enabled, skipping setup")
        return

    async_setup_platform_entities(
        entry, coordinator, async_add_entities, DEVICE_TYPE_SCENE, CrestronHomeScene
    )


class CrestronHomeScene(CrestronBaseEntity, Scene):
    """Representation of a Crestron Home scene."""

    _device_type_key = DEVICE_TYPE_SCENE

    def __init__(self, coordinator: CrestronHomeDataUpdateCoordinator, device: CrestronDevice) -> None:
        """Initialize the scene."""
        super().__init__(coordinator, device)

        scene_type = device.raw_data.get("sceneType", "")
        if scene_type:
            self._attr_device_info["model"] = f"{MODEL} {scene_type}"

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self.coordinator.client.execute_scene(self._crestron_device.id)
        await self.coordinator.async_request_refresh()
