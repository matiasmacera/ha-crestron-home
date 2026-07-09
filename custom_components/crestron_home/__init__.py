"""The Crestron Home integration."""
from __future__ import annotations

import logging
import re
from typing import List

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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
        hass, entry, client, update_interval, enabled_device_types, ignored_device_names
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

    _async_migrate_device_identifiers(hass, entry)

    enabled_platforms = _platforms_for_device_types(enabled_device_types)
    _LOGGER.debug("Setting up enabled platforms: %s", enabled_platforms)
    await hass.config_entries.async_forward_entry_setups(entry, enabled_platforms)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


def _async_migrate_device_identifiers(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate pre-0.5.0 bare-numeric device identifiers to namespaced ones.

    Identifiers used to be the bare numeric Crestron ID, which collided across
    the independent /devices, /scenes, /sensors ID spaces. Updating them in
    place (namespace inferred from the attached entities' unique_id) preserves
    user customizations like area assignments and renamed devices.
    """
    device_registry = async_get_device_registry(hass)
    entity_registry = async_get_entity_registry(hass)

    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        legacy = {
            ident for ident in device_entry.identifiers
            if len(ident) == 2 and ident[0] == DOMAIN and str(ident[1]).isdigit()
        }
        if not legacy:
            continue

        # Infer the namespace from this device's entity unique_ids
        # (crestron_light_5 → light, crestron_binary_sensor_7 → binary_sensor)
        prefixes = set()
        for entity_entry in er.async_entries_for_device(
            entity_registry, device_entry.id, include_disabled_entities=True
        ):
            match = re.fullmatch(r"crestron_([a-z_]+)_\d+", entity_entry.unique_id or "")
            if match:
                prefixes.add(match.group(1))

        try:
            if len(prefixes) == 1:
                prefix = next(iter(prefixes))
                new_identifiers = {
                    (DOMAIN, f"{prefix}_{ident[1]}") if ident in legacy else ident
                    for ident in device_entry.identifiers
                }
                _LOGGER.debug(
                    "Migrating device %s identifiers %s → %s",
                    device_entry.name, device_entry.identifiers, new_identifiers,
                )
                device_registry.async_update_device(
                    device_entry.id, new_identifiers=new_identifiers
                )
            else:
                # Ambiguous (an actual ID collision merged unrelated devices) or
                # no entities: detach so entities re-link to fresh namespaced devices
                _LOGGER.debug(
                    "Detaching ambiguous legacy device %s (%s)",
                    device_entry.name, device_entry.identifiers,
                )
                device_registry.async_update_device(
                    device_entry.id, remove_config_entry_id=entry.entry_id
                )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Failed to migrate device %s, detaching it instead", device_entry.name
            )
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    enabled_platforms = _platforms_for_device_types(enabled_device_types)

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, enabled_platforms):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

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
    """Reload the config entry when options change.

    Two-phase via this same listener: when entry.options is non-empty (a
    fresh options-flow submission), diff it against the last-applied config
    in entry.data, clean up any disabled device types, then merge options
    into data and clear entry.options. That async_update_entry call is
    itself a data change, so HA re-fires this listener; the second pass
    finds entry.options empty and performs the actual reload. Splitting it
    this way means exactly one reload happens per options save (merging and
    reloading in the same pass would double-fire: our own async_update_entry
    schedules a second listener call that would reload again).

    The reload itself goes through hass.config_entries.async_reload, which
    serializes on the entry's setup lock and correctly runs
    entry.async_on_unload callbacks — a manual async_unload_entry +
    async_setup_entry call here skipped those callbacks and could crash
    coordinator startup on modern HA, which requires setup to go through
    the framework.
    """
    if entry.options:
        old_enabled_types = set(entry.data.get(CONF_ENABLED_DEVICE_TYPES, []))
        new_enabled_types = set(entry.options.get(CONF_ENABLED_DEVICE_TYPES, old_enabled_types))
        disabled_types = [t for t in old_enabled_types if t not in new_enabled_types]

        _LOGGER.debug(
            "Applying new options. New types: %s, Disabled: %s",
            new_enabled_types, disabled_types,
        )

        if disabled_types:
            await _async_clean_entity_registry(hass, entry, disabled_types)

        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **entry.options}, options={}
        )
        return

    await hass.config_entries.async_reload(entry.entry_id)
