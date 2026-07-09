"""Config flow for Crestron Home integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .api import CrestronApiError, CrestronAuthError, CrestronClient, CrestronConnectionError
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
    DEVICE_TYPE_BINARY_SENSOR,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SCENE,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_THERMOSTAT,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

ALL_DEVICE_TYPES = [
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_SHADE,
    DEVICE_TYPE_SCENE,
    DEVICE_TYPE_BINARY_SENSOR,
    DEVICE_TYPE_SENSOR,
    DEVICE_TYPE_THERMOSTAT,
]

DEVICE_TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[
            {"value": DEVICE_TYPE_LIGHT, "label": "Lights"},
            {"value": DEVICE_TYPE_SHADE, "label": "Shades"},
            {"value": DEVICE_TYPE_SCENE, "label": "Scenes"},
            {"value": DEVICE_TYPE_BINARY_SENSOR, "label": "Binary Sensors"},
            {"value": DEVICE_TYPE_SENSOR, "label": "Sensors"},
            {"value": DEVICE_TYPE_THERMOSTAT, "label": "Thermostats"},
        ],
        multiple=True,
        mode=selector.SelectSelectorMode.LIST,
    ),
)

UPDATE_INTERVAL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_UPDATE_INTERVAL,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="seconds",
    ),
)

IGNORED_NAMES_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        multiple=True,
        suffix="Use % as wildcard (e.g., %bathroom%)",
    ),
)


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    client = CrestronClient(
        hass=hass,
        host=data[CONF_HOST],
        token=data[CONF_TOKEN],
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )

    try:
        await client.login()
    except CrestronConnectionError as error:
        raise CannotConnect from error
    except CrestronAuthError as error:
        raise InvalidAuth from error
    except CrestronApiError as error:
        raise CannotConnect from error

    # Return info that you want to store in the config entry.
    return {"title": f"Crestron Home ({data[CONF_HOST]})"}


class CrestronHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron Home."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CrestronHomeOptionsFlowHandler:
        """Get the options flow for this handler."""
        return CrestronHomeOptionsFlowHandler()

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # Ensure enabled_device_types is preserved from user selection
                # Only set defaults if the key is completely absent (not if user chose empty)
                user_input.setdefault(CONF_ENABLED_DEVICE_TYPES, list(ALL_DEVICE_TYPES))
                user_input.setdefault(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

                return self.async_create_entry(title=info["title"], data=user_input)

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # If there are no user inputs or there were errors, show the form again
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_TOKEN): str,
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): UPDATE_INTERVAL_SELECTOR,
                    vol.Optional(
                        CONF_ENABLED_DEVICE_TYPES, default=list(ALL_DEVICE_TYPES)
                    ): DEVICE_TYPE_SELECTOR,
                    vol.Optional(
                        CONF_IGNORED_DEVICE_NAMES, default=DEFAULT_IGNORED_DEVICE_NAMES
                    ): IGNORED_NAMES_SELECTOR,
                    vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle reauth when the API token becomes invalid."""
        self._reauth_entry_id = self.context["entry_id"]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Ask for a new API token and validate it."""
        errors: Dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self._reauth_entry_id)

        if user_input is not None:
            new_data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}
            try:
                await validate_input(self.hass, new_data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"host": entry.data[CONF_HOST]},
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )


class CrestronHomeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Crestron Home options."""

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        errors: Dict[str, str] = {}

        # Get current values: prefer options (latest), fallback to data (initial)
        def _current(key, default=None):
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        if user_input is not None:
            # Validate the updated configuration (with the SSL mode being saved)
            try:
                client = CrestronClient(
                    hass=self.hass,
                    host=self.config_entry.data[CONF_HOST],
                    token=self.config_entry.data[CONF_TOKEN],
                    verify_ssl=user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                )
                await client.login()

                # Return the options to be stored in entry.options
                # The async_reload_entry function will handle merging these with the data
                return self.async_create_entry(title="", data=user_input)

            except CrestronConnectionError:
                errors["base"] = "cannot_connect"
            except CrestronAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=_current(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                    ): UPDATE_INTERVAL_SELECTOR,
                    vol.Required(
                        CONF_ENABLED_DEVICE_TYPES,
                        default=_current(CONF_ENABLED_DEVICE_TYPES, list(ALL_DEVICE_TYPES)),
                    ): DEVICE_TYPE_SELECTOR,
                    vol.Optional(
                        CONF_IGNORED_DEVICE_NAMES,
                        default=_current(CONF_IGNORED_DEVICE_NAMES, DEFAULT_IGNORED_DEVICE_NAMES),
                    ): IGNORED_NAMES_SELECTOR,
                    vol.Optional(
                        CONF_VERIFY_SSL,
                        default=_current(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                    ): bool,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
