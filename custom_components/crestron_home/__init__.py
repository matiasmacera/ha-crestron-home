"""The Crestron Home integration."""
from __future__ import annotations

import logging
from typing import List

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .api import CrestronApiError, CrestronClient
from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    CONF_HOST,
    CONF_IGNORED_DEVICE_NAMES,
    CONF_TOKEN,
    CONF_UPDATE_INTERVAL,
    CONF_VERIFY_SSL,
    DEFAULT_IGNORED_DEVICE_NAMES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DEVICE_TYPE_TO_PLATFORM,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    STARTUP_MESSAGE,
)
from .coordinator import CrestronHomeDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _platforms_for_device_types(device_types: list[str] | set[str]) -> list[Platform]:
    """Map a collection of device types to their HA platforms (single source of truth)."""
    return [
        DEVICE_TYPE_TO_PLATFORM[dt]
        for dt in device_types
        if dt in DEVICE_TYPE_TO_PLATFORM
    ]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron Home from a config entry."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    host = entry.data.get(CONF_HOST)
    token = entry.data.get(CONF_TOKEN)
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    ignored_device_names = entry.data.get(CONF_IGNORED_DEVICE_NAMES, DEFAULT_IGNORED_DEVICE_NAMES)
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    _LOGGER.debug("Ignored device name patterns: %s", ignored_device_names)

    client = CrestronClient(hass, host, token, verify_ssl=verify_ssl)

    _LOGGER.debug(
        "Creating coordinator with update_interval=%s, enabled_types=%s, ignored_names=%s",
        update_interval, enabled_device_types, ignored_device_names
    )

    coordinator = CrestronHomeDataUpdateCoordinator(
        hass, client, update_interval, enabled_device_types, ignored_device_names
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except CrestronApiError as err:
        raise ConfigEntryNotReady(f"Failed to connect to Crestron Home: {err}") from err

    hass.data[DOMAIN][entry.entry_id] = coordinator

    device_registry = async_get_device_registry(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host)},
        name=f"Crestron Home ({host})",
        manufacturer=MANUFACTURER,
        model=MODEL,
    )

    enabled_platforms = _platforms_for_device_types(enabled_device_types)
    _LOGGER.debug("Setting up enabled platforms: %s", enabled_platforms)
    await hass.config_entries.async_forward_entry_setups(entry, enabled_platforms)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry, platform_override: list = None) -> bool:
    """Unload a config entry."""
    if platform_override is not None:
        enabled_platforms = platform_override
    else:
        enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
        enabled_platforms = _platforms_for_device_types(enabled_device_types)

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, enabled_platforms):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_clean_entity_registry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    disabled_device_types: List[str]
) -> None:
    """Remove entities for disabled device types from the entity registry."""
    entity_registry = async_get_entity_registry(hass)

    domains_to_clean = _platforms_for_device_types(disabled_device_types)
    _LOGGER.debug("Cleaning up entities for domains: %s", domains_to_clean)

    entities_to_remove = [
        entity_id for entity_id, entity in entity_registry.entities.items()
        if entity.config_entry_id == entry.entry_id and entity.domain in domains_to_clean
    ]

    for entity_id in entities_to_remove:
        _LOGGER.debug("Removing entity %s from registry", entity_id)
        entity_registry.async_remove(entity_id)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    old_enabled_types = set(entry.data.get(CONF_ENABLED_DEVICE_TYPES, []))

    if not entry.options:
        await async_unload_entry(hass, entry)
        await async_setup_entry(hass, entry)
        return

    new_enabled_types = set(entry.options.get(CONF_ENABLED_DEVICE_TYPES, old_enabled_types))
    new_update_interval = entry.options.get(CONF_UPDATE_INTERVAL, entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
    new_ignored_device_names = entry.options.get(CONF_IGNORED_DEVICE_NAMES, entry.data.get(CONF_IGNORED_DEVICE_NAMES, DEFAULT_IGNORED_DEVICE_NAMES))

    disabled_types = [t for t in old_enabled_types if t not in new_enabled_types]

    _LOGGER.debug(
        "Reloading entry. Update interval: %s, New types: %s, Ignored names: %s, Disabled: %s",
        new_update_interval, new_enabled_types, new_ignored_device_names, disabled_types
    )

    if disabled_types:
        await _async_clean_entity_registry(hass, entry, disabled_types)

    old_platforms = _platforms_for_device_types(old_enabled_types)

    if entry.options:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **entry.options}
        )

    if await async_unload_entry(hass, entry, platform_override=old_platforms):
        _LOGGER.debug("Successfully unloaded entry")
    else:
        _LOGGER.warning("Failed to unload entry completely")
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            _LOGGER.debug("Forcing cleanup of entry data")
            hass.data[DOMAIN].pop(entry.entry_id, None)

    await async_setup_entry(hass, entry)
