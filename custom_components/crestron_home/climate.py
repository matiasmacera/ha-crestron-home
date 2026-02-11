"""Support for Crestron Home thermostats."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

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

# Crestron mode → HA HVACMode (case-insensitive lookup built below)
_CRESTRON_MODE_MAP = {
    "Off": HVACMode.OFF,
    "Heat": HVACMode.HEAT,
    "Cool": HVACMode.COOL,
    "Auto": HVACMode.HEAT_COOL,
}
# Build case-insensitive lookup
CRESTRON_TO_HVAC_MODE: dict[str, HVACMode] = {}
for _k, _v in _CRESTRON_MODE_MAP.items():
    CRESTRON_TO_HVAC_MODE[_k] = _v
    CRESTRON_TO_HVAC_MODE[_k.upper()] = _v
    CRESTRON_TO_HVAC_MODE[_k.lower()] = _v

# HA HVACMode → Crestron mode string (title case, matching API docs)
HVAC_MODE_TO_CRESTRON = {v: k for k, v in _CRESTRON_MODE_MAP.items()}


def _get_mode_str(raw_data: dict[str, Any]) -> str:
    """Get current mode string from raw thermostat data.

    The Crestron API may use 'currentMode' or 'mode' depending on the version.
    """
    return raw_data.get("currentMode") or raw_data.get("mode") or "Off"


def _get_target_temp_raw(raw_data: dict[str, Any]) -> int | None:
    """Get the current target temperature (in Crestron tenths) from raw data.

    Handles two API formats:
      - currentSetPoint: array of {type, temperature/value} (newer / Homebridge format)
      - setPoint: object with {type, temperature, minValue, maxValue} (docs format)
    """
    # Try currentSetPoint array first (Homebridge-observed format)
    csp = raw_data.get("currentSetPoint")
    if isinstance(csp, list) and csp:
        mode = _get_mode_str(raw_data).lower()
        # Try to find a setpoint matching the current mode
        for sp in csp:
            if sp.get("type", "").lower() == mode:
                # Support both "temperature" and "value" keys
                return sp.get("temperature") or sp.get("value")
        # Fall back to Cool, then Heat, then first available
        for pref in ("cool", "heat"):
            for sp in csp:
                if sp.get("type", "").lower() == pref:
                    return sp.get("temperature") or sp.get("value")
        # Last resort: first entry with a temperature/value
        for sp in csp:
            val = sp.get("temperature") or sp.get("value")
            if val is not None:
                return val
        return None

    # Fall back to setPoint object (official docs format)
    sp_obj = raw_data.get("setPoint")
    if isinstance(sp_obj, dict):
        return sp_obj.get("temperature")

    return None


def _get_setpoint_type(raw_data: dict[str, Any]) -> str:
    """Determine the setpoint type to use when setting temperature.

    Returns a mode string like 'Cool', 'Heat', or 'Auto'.
    """
    mode = _get_mode_str(raw_data)
    # For Off mode, default to Cool
    if mode.lower() == "off":
        return "Cool"
    # Title-case the mode to match Crestron API conventions
    return mode.title()


def _get_min_max_temps(raw_data: dict[str, Any]) -> tuple[int, int]:
    """Get min and max temperatures from availableSetPoints or setPoint.

    Returns (min_value, max_value) in Crestron tenths.
    """
    # Try availableSetPoints array first
    available_sps = raw_data.get("availableSetPoints")
    if isinstance(available_sps, list) and available_sps:
        all_mins = [sp.get("minValue") for sp in available_sps if sp.get("minValue") is not None]
        all_maxs = [sp.get("maxValue") for sp in available_sps if sp.get("maxValue") is not None]
        min_val = min(all_mins) if all_mins else None
        max_val = max(all_maxs) if all_maxs else None
        if min_val is not None and max_val is not None:
            return min_val, max_val

    # Fall back to setPoint object
    sp_obj = raw_data.get("setPoint")
    if isinstance(sp_obj, dict):
        min_v = sp_obj.get("minValue")
        max_v = sp_obj.get("maxValue")
        if min_v is not None and max_v is not None:
            return min_v, max_v

    # Return None sentinel so caller can use unit-appropriate defaults
    return None, None


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

        thermostat_devices = coordinator.data.get(DEVICE_TYPE_THERMOSTAT, {})
        _LOGGER.debug("CLIMATE SETUP: Found %d thermostat devices", len(thermostat_devices))

        for device in thermostat_devices.values():
            device_id = str(device.id)
            if device_id in added_ids:
                continue

            thermostat = CrestronHomeThermostat(coordinator, device)

            if device.ha_hidden:
                thermostat._attr_hidden_by = "integration"

            thermostats.append(thermostat)
            added_ids.add(device_id)

        if thermostats:
            _LOGGER.info("Adding %d thermostat entities", len(thermostats))
            async_add_entities(thermostats)

    _async_add_thermostats()

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
        self._device_info = device
        self._device = device

        self._attr_unique_id = f"crestron_thermostat_{device.id}"
        self._attr_name = device.full_name
        self._attr_has_entity_name = False

        # Determine temperature unit from raw_data
        # Crestron reports "DeciCelsius" or "DeciFahrenheit"
        units = device.raw_data.get("temperatureUnits", "DeciCelsius")
        if "Celsius" in units:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_target_temperature_step = 0.5
            self._is_celsius = True
        else:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
            self._attr_target_temperature_step = 1.0
            self._is_celsius = False

        # Build supported HVAC modes from availableSystemModes
        available_modes = device.raw_data.get("availableSystemModes", [])
        self._attr_hvac_modes = []
        for mode_str in available_modes:
            ha_mode = CRESTRON_TO_HVAC_MODE.get(mode_str)
            if ha_mode and ha_mode not in self._attr_hvac_modes:
                self._attr_hvac_modes.append(ha_mode)
        if HVACMode.OFF not in self._attr_hvac_modes:
            self._attr_hvac_modes.insert(0, HVACMode.OFF)

        # Build supported fan modes from availableFanModes
        # Crestron returns: ["Auto", "On", "CirculateLow", ...] or []
        available_fan = device.raw_data.get("availableFanModes", [])
        self._attr_fan_modes = available_fan if available_fan else None

        # Set min/max from availableSetPoints or setPoint
        min_raw, max_raw = _get_min_max_temps(device.raw_data)
        if min_raw is not None and max_raw is not None:
            self._attr_min_temp = self._from_crestron_temp(min_raw)
            self._attr_max_temp = self._from_crestron_temp(max_raw)
        else:
            self._attr_min_temp = 3.0 if self._is_celsius else 45.0
            self._attr_max_temp = 32.0 if self._is_celsius else 95.0

        # Supported features
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._attr_fan_modes:
            features |= ClimateEntityFeature.FAN_MODE
        self._attr_supported_features = features

        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"thermostat_{device.id}")},
            name=device.full_name,
            manufacturer=MANUFACTURER,
            model="HZ-THSTAT",
            via_device=(DOMAIN, coordinator.client.host),
            suggested_area=device.room,
        )

    # -- Temperature conversion helpers --

    def _from_crestron_temp(self, value: int | None) -> float | None:
        """Convert Crestron deci-degree int to real degrees.

        Crestron reports temperatures in tenths of a degree:
        DeciCelsius: 275 = 27.5C, 30 = 3.0C, 320 = 32.0C
        DeciFahrenheit: 760 = 76.0F
        """
        if value is None:
            return None
        return round(value / 10.0, 1)

    def _to_crestron_temp(self, value: float) -> int:
        """Convert real degrees to Crestron deci-degree int.

        27.5C = 275, 76.0F = 760
        """
        return int(round(value * 10))

    # -- State properties (read from coordinator) --

    def _get_device(self) -> CrestronDevice:
        """Get the latest device data from coordinator via O(1) dict lookup."""
        device = self.coordinator.data.get(DEVICE_TYPE_THERMOSTAT, {}).get(self._device.id)
        return device if device is not None else self._device

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
        return self._from_crestron_temp(
            _get_target_temp_raw(self._get_device().raw_data)
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        mode_str = _get_mode_str(self._get_device().raw_data)
        return CRESTRON_TO_HVAC_MODE.get(mode_str, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Infer current HVAC action from mode + temps.

        Uses the API's 'running' field if available, otherwise infers
        from mode and temperature comparison with a small deadband to
        avoid rapid toggling between IDLE and HEATING/COOLING.
        """
        device = self._get_device()
        mode_str = _get_mode_str(device.raw_data)

        if mode_str.lower() == "off":
            return HVACAction.OFF

        # Use explicit running state from API if available
        running = device.raw_data.get("running")
        if running is not None:
            if isinstance(running, str):
                running_lower = running.lower()
                if running_lower == "cooling":
                    return HVACAction.COOLING
                if running_lower == "heating":
                    return HVACAction.HEATING
                if running_lower in ("idle", "off"):
                    return HVACAction.IDLE

        current = device.raw_data.get("currentTemperature")
        target = _get_target_temp_raw(device.raw_data)
        if current is None or target is None:
            return HVACAction.IDLE

        # Deadband of 0.5 deci-degrees (0.05 real degrees) to avoid toggling
        deadband = 5
        mode_lower = mode_str.lower()
        if mode_lower == "cool" and current > target + deadband:
            return HVACAction.COOLING
        if mode_lower == "heat" and current < target - deadband:
            return HVACAction.HEATING
        if mode_lower == "auto":
            if current > target + deadband:
                return HVACAction.COOLING
            if current < target - deadband:
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
            "setpoint_type": _get_setpoint_type(device.raw_data),
            "temperature_units": device.raw_data.get("temperatureUnits"),
        }

    # -- Commands --

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
        sp_type = _get_setpoint_type(device.raw_data)

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
        """Turn thermostat on (restore last non-Off mode or default to Heat)."""
        for mode in self._attr_hvac_modes:
            if mode != HVACMode.OFF:
                await self.async_set_hvac_mode(mode)
                return

    async def async_turn_off(self) -> None:
        """Turn thermostat off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    # -- Coordinator callback --

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
        device = self.coordinator.data.get(DEVICE_TYPE_THERMOSTAT, {}).get(self._device.id)
        if device is not None:
            self._device = device
            self._device_info = device
        self.async_write_ha_state()
