"""DataUpdateCoordinator for Crestron Home integration."""
from datetime import timedelta
import logging
from typing import Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import CrestronApiError, CrestronAuthError, CrestronClient, CrestronConnectionError
from .const import DOMAIN
from .device_manager import CrestronDeviceManager
from .models import CrestronDevice

_LOGGER = logging.getLogger(__name__)


class CrestronHomeDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Crestron Home system."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CrestronClient,
        update_interval: int,
        enabled_device_types: List[str],
        ignored_device_names: Optional[List[str]] = None,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.enabled_device_types = enabled_device_types
        self.ignored_device_names = ignored_device_names or []

        # Initialize the device manager
        self.device_manager = CrestronDeviceManager(
            hass, client, enabled_device_types, ignored_device_names
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> Dict[str, Dict[int, CrestronDevice]]:
        """Update data via device manager."""
        try:
            return await self.device_manager.poll_devices()

        except CrestronAuthError as error:
            # Token invalid even after a fresh login attempt: trigger reauth flow
            raise ConfigEntryAuthFailed(f"Authentication error: {error}") from error

        except CrestronConnectionError as error:
            raise UpdateFailed(f"Connection error: {error}") from error

        except CrestronApiError as error:
            raise UpdateFailed(f"API error: {error}") from error

        except Exception as error:
            raise UpdateFailed(f"Unexpected error: {error}") from error
