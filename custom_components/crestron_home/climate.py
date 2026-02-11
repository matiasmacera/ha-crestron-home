"""Support for Crestron Home thermostats."""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLED_DEVICE_TYPES,
    DEVICE_TYPE_THERMOSTAT,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import CrestronHomeDataUpdateCoordinator
from .entity import CrestronRoomEntity
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)

# Crestron mode → HA HVACMode
CRESTRON_TO_HVAC_MODE = {
    "Off": HVACMode.OFF,
    "Heat": HVACMode.HEAT,
    "Cool": HVACMode.COOL,
    "Auto": HVACMode.HEAT_COOL,
}

# HA HVACMode → Crestron mode string
HVAC_MODE_TO_CRESTRON = {v: k for k, v in CRESTRON_TO_HVAC_MODE.items()}

# Crestron fan mode strings
CRESTRON_FAN_AUTO = "Auto"
CRESTRON_FAN_ON = "On"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron Home thermostats based on config entry."""
    coordinator: CrestronHomeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Check if thermostat platform is enabled
    enabled_device_types = entry.data.get(CONF_ENABLED_DEVICE_TYPES, [])
    if DEVICE_TYPE_THERMOSTAT not in enabled_device_types:
        _LOGGER.debug("Thermostat platform not enabled, skipping setup")
        return

    added_ids: set[str] = set()

    @callback
    def _async_add_thermostats() -> None:
        """Add thermostat entities from coordinator data."""
        thermostats = []

        _LOGGER.warning("CLIMATE SETUP: coordinator.data keys = %s", list(coordinator.data.keys()) if coordinator.data else "NO DATA")
        _LOGGER.warning("CLIMATE SETUP: DEVICE_TYPE_THERMOSTAT = '%s'", DEVICE_TYPE_THERMOSTAT)
        
        thermostat_devices = coordinator.data.get(DEVICE_TYPE_THERMOSTAT, [])
        _LOGGER.warning("CLIMATE SETUP: Found %d thermostat devices in coordinator.data", len(thermostat_devices))

        for device in thermostat_devices:
            device_id = str(device.id)
            _LOGGER.warning("CLIMATE SETUP: Processing device id=%s name=%s type=%s", device_id, device.name, device.type)
            if device_id in added_ids:
                continue

            thermostat = CrestronHomeThermostat(coordinator, device)

            # Set hidden_by if device is marked as hidden
            if device.ha_hidden:
                thermostat._attr_hidden_by = "integration"

            thermostats.append(thermostat)
            added_ids.add(device_id)

        if thermostats:
            _LOGGER.info("Adding %d thermostat entities", len(thermostats))
            async_add_entities(thermostats)

    # Add any thermostats already available
    _async_add_thermostats()

    # Listen for coordinator updates to add new thermostats
    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_thermostats)
    )


class CrestronHomeThermostat(CrestronRoomEntity, CoordinatorEntity, ClimateEntity):
    """Representation of a Crestron Home thermostat (HZ-THSTAT)."""

    def __init__(
        self,
        coordinator: CrestronHomeDataUpdateCoordinator,
        device: CrestronDevice,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self._device_info = device  # For CrestronRoomEntity
        self._device = device

        self._attr_unique_id = f"crestron_thermostat_{device.id}"
        self._attr_name = device.full_name
        self._attr_has_entity_name = False

        # Determine temperature unit from raw_data
        units = device.raw_data.get("temperatureUnits", "FahrenheitWholeDegrees")
        if "Celsius" in units:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_target_temperature_step = 0.5
        else:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
            self._attr_target_temperature_step = 1.0

        # Build supported HVAC modes from API response
        available_modes = device.raw_data.get("availableSystemModes", [])
        self._attr_hvac_modes = [HVACMode.OFF]  # Always allow OFF
        for mode_str in available_modes:
            ha_mode = CRESTRON_TO_HVAC_MODE.get(mode_str)
            if ha_mode and ha_mode not in self._attr_hvac_modes:
                self._attr_hvac_modes.append(ha_mode)

        # Build supported fan modes from API response
        self._attr_fan_modes = device.raw_data.get("availableFanModes", [CRESTRON_FAN_AUTO, CRESTRON_FAN_ON])

        # Set min/max from setpoint range
        set_point = device.raw_data.get("setPoint", {})
        self._attr_min_temp = self._from_crestron_temp(set_point.get("minValue", 590))
        self._attr_max_temp = self._from_crestron_temp(set_point.get("maxValue", 990))

        # Supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"thermostat_{device.id}")},
            name=device.full_name,
            manufacturer=MANUFACTURER,
            model="HZ-THSTAT",
            via_device=(DOMAIN, coordinator.client.host),
            suggested_area=device.room,
        )

    # ── Temperature conversion helpers ──────────────────────────────

    def _from_crestron_temp(self, value: int | None) -> float | None:
        """Convert Crestron tenths-of-degree int to real degrees (e.g. 760 → 76.0)."""
        if value is None:
            return None
        return round(value / 10.0, 1)

    def _to_crestron_temp(self, value: float) -> int:
        """Convert real degrees to Crestron tenths-of-degree int (e.g. 76.0 → 760)."""
        return int(round(value * 10))

    # ── State properties (read from coordinator) ────────────────────

    def _get_device(self) -> CrestronDevice:
        """Get the latest device data from coordinator."""
        for device in self.coordinator.data.get(DEVICE_TYPE_THERMOSTAT, []):
            if device.id == self._device.id:
                return device
        return self._device

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._get_device().is_available

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._from_crestron_temp(
            self._get_device().raw_data.get("currentTemperature")
        )

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        sp = self._get_device().raw_data.get("setPoint", {})
        return self._from_crestron_temp(sp.get("temperature"))

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        mode_str = self._get_device().raw_data.get("mode", "Off")
        return CRESTRON_TO_HVAC_MODE.get(mode_str, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Infer current HVAC action from mode + temps."""
        device = self._get_device()
        mode_str = device.raw_data.get("mode", "Off")
        if mode_str == "Off":
            return HVACAction.OFF

        current = device.raw_data.get("currentTemperature")
        target = (device.raw_data.get("setPoint") or {}).get("temperature")
        if current is None or target is None:
            return HVACAction.IDLE

        if mode_str == "Cool" and current > target:
            return HVACAction.COOLING
        if mode_str == "Heat" and current < target:
            return HVACAction.HEATING
        if mode_str == "Auto":
            if current > target:
                return HVACAction.COOLING
            if current < target:
                return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        return self._get_device().raw_data.get("currentFanMode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        device = self._get_device()
        return {
            "crestron_id": device.id,
            "room_name": device.room,
            "scheduler_state": device.raw_data.get("schedulerState"),
            "connection_status": device.connection,
            "setpoint_type": (device.raw_data.get("setPoint") or {}).get("type"),
        }

    # ── Commands ────────────────────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        crestron_mode = HVAC_MODE_TO_CRESTRON.get(hvac_mode)
        if crestron_mode is None:
            _LOGGER.warning("Unsupported HVAC mode: %s", hvac_mode)
            return

        await self.coordinator.client.set_thermostat_mode(
            self._device.id, crestron_mode
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return

        # Determine setpoint type from current mode
        device = self._get_device()
        sp_type = (device.raw_data.get("setPoint") or {}).get("type", device.raw_data.get("mode", "Cool"))

        await self.coordinator.client.set_thermostat_setpoint(
            self._device.id, sp_type, self._to_crestron_temp(temp)
        )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        await self.coordinator.client.set_thermostat_fan_mode(
            self._device.id, fan_mode
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn thermostat on (restore last non-Off mode or default to Auto)."""
        # Pick the first non-Off mode available
        for mode in self._attr_hvac_modes:
            if mode != HVACMode.OFF:
                await self.async_set_hvac_mode(mode)
                return

    async def async_turn_off(self) -> None:
        """Turn thermostat off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    # ── Coordinator callback ────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        if self._device.ha_hidden:
            entity_registry = async_get_entity_registry(self.hass)
            if entity_registry.async_get(self.entity_id):
                entity_registry.async_update_entity(
                    self.entity_id, hidden_by="integration"
                )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        for device in self.coordinator.data.get(DEVICE_TYPE_THERMOSTAT, []):
            if device.id == self._device.id:
                self._device = device
                self._device_info = device
                break
        self.async_write_ha_state()
