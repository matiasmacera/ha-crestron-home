"""API Client for Crestron Home."""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp.client_exceptions import ClientConnectorError, ClientResponseError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_TIMEOUT,
    CRESTRON_API_PATH,
    CRESTRON_MAX_LEVEL,
    CRESTRON_SESSION_TIMEOUT,
    ROOMS_REFRESH_POLLS,
)

_LOGGER = logging.getLogger(__name__)


class CrestronApiError(Exception):
    """Exception to indicate a general API error."""


class CrestronAuthError(CrestronApiError):
    """Exception to indicate an authentication error."""


class CrestronConnectionError(CrestronApiError):
    """Exception to indicate a connection error."""


class CrestronClient:
    """API Client for Crestron Home."""

    def __init__(
        self, hass: HomeAssistant, host: str, token: str, verify_ssl: bool = False
    ) -> None:
        """Initialize the API client."""
        self.hass = hass
        self.host = host
        self.api_token = token
        self.base_url = f"https://{host}{CRESTRON_API_PATH}"
        self.auth_key: Optional[str] = None
        self.last_login: float = 0
        self.rooms: List[Dict[str, Any]] = []
        self._polls_since_rooms: int = 0
        self._verify_ssl = verify_ssl
        # Single shared session for ALL requests (login + API) – avoids leaking sessions
        self._session = async_get_clientsession(hass, verify_ssl=verify_ssl)
        self._timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)

        # Lock to prevent multiple simultaneous login attempts
        self._login_lock = asyncio.Lock()

    async def login(self) -> None:
        """Login to the Crestron Home system."""
        current_time = time.time()
        if self.auth_key and (current_time - self.last_login) < CRESTRON_SESSION_TIMEOUT:
            _LOGGER.debug("Session is still valid, skipping login")
            return

        async with self._login_lock:
            # Double-check after acquiring the lock
            current_time = time.time()
            if self.auth_key and (current_time - self.last_login) < CRESTRON_SESSION_TIMEOUT:
                _LOGGER.debug("Session is still valid, skipping login (after lock)")
                return

            _LOGGER.debug("Logging in to Crestron Home at %s", self.base_url)

            try:
                headers = {
                    "Accept": "application/json",
                    "Crestron-RestAPI-AuthToken": self.api_token,
                }

                # Reuse the shared HA session (already configured with SSL settings)
                async with self._session.get(
                    f"{self.base_url}/login",
                    headers=headers,
                    timeout=self._timeout,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    self.auth_key = data.get("authkey")
                    if not self.auth_key:
                        raise CrestronAuthError("No authentication key received")

                    self.last_login = current_time
                    _LOGGER.info(
                        "Successfully authenticated with Crestron Home, version: %s",
                        data.get("version", "unknown"),
                    )

            except asyncio.TimeoutError as error:
                _LOGGER.error("Login timed out after %ss", API_TIMEOUT)
                raise CrestronConnectionError(
                    f"Login timed out after {API_TIMEOUT}s"
                ) from error

            except ClientConnectorError as error:
                _LOGGER.error("Connection error: %s", error)
                raise CrestronConnectionError(f"Connection error: {error}") from error

            except ClientResponseError as error:
                _LOGGER.error("Authentication error: %s", error)
                raise CrestronAuthError(f"Authentication error: {error}") from error

            except CrestronApiError:
                raise

            except Exception as error:
                _LOGGER.error("Unexpected error during login: %s", error)
                raise CrestronApiError(f"Unexpected error: {error}") from error

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        _retry_on_auth: bool = True,
    ) -> Dict[str, Any]:
        """Make an API request to the Crestron Home system."""
        await self.login()

        if not self.auth_key:
            raise CrestronAuthError("Not authenticated")

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Crestron-RestAPI-AuthKey": self.auth_key,
        }

        try:
            async with self._session.request(
                method, url, headers=headers, json=data,
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                return await response.json()

        except asyncio.TimeoutError as error:
            raise CrestronConnectionError(
                f"Request to {endpoint} timed out after {API_TIMEOUT}s"
            ) from error

        except ClientResponseError as error:
            if error.status == 401:
                # Session expired server-side: re-authenticate and retry once
                self.auth_key = None
                self.last_login = 0
                if _retry_on_auth:
                    _LOGGER.debug(
                        "Session expired (401) on %s, re-authenticating and retrying",
                        endpoint,
                    )
                    return await self._api_request(
                        method, endpoint, data, _retry_on_auth=False
                    )
                raise CrestronAuthError("Authentication expired") from error
            raise CrestronApiError(f"API error: {error}") from error

        except CrestronApiError:
            raise

        except Exception as error:
            _LOGGER.error("API request error: %s", error)
            raise CrestronApiError(f"API request error: {error}") from error

    async def _refresh_rooms(self) -> None:
        """Fetch the room list and reset the refresh counter."""
        rooms_data = await self._api_request("GET", "/rooms")
        self.rooms = rooms_data.get("rooms", [])
        self._polls_since_rooms = 0

    async def get_devices(self) -> List[Dict[str, Any]]:
        """Get all devices and scenes from the Crestron Home system."""
        try:
            # Rooms rarely change: only refetch every ROOMS_REFRESH_POLLS polls,
            # or immediately below if an unknown roomId shows up.
            self._polls_since_rooms += 1
            fetch_rooms = not self.rooms or self._polls_since_rooms >= ROOMS_REFRESH_POLLS

            coros = [
                self._api_request("GET", "/scenes"),
                self._api_request("GET", "/devices"),
                self._api_request("GET", "/shades"),
            ]
            if fetch_rooms:
                coros.append(self._api_request("GET", "/rooms"))

            results = await asyncio.gather(*coros)
            scenes_data, devices_data, shades_data = results[0], results[1], results[2]
            if fetch_rooms:
                self.rooms = results[3].get("rooms", [])
                self._polls_since_rooms = 0

            raw_devices = devices_data.get("devices", [])
            raw_scenes = scenes_data.get("scenes", [])

            # O(1) lookups instead of per-device linear scans
            room_lookup: Dict[Any, str] = {
                r.get("id"): r.get("name", "") for r in self.rooms
            }
            shade_positions: Dict[Any, int] = {
                s.get("id"): s.get("position", 0)
                for s in shades_data.get("shades", [])
            }

            # A roomId we don't know about means a room was added/changed since
            # the last /rooms fetch: refresh now so names are right immediately.
            if not fetch_rooms and any(
                item.get("roomId") not in room_lookup
                for item in (*raw_devices, *raw_scenes)
                if item.get("roomId") is not None
            ):
                _LOGGER.debug("Unknown roomId found, refreshing room list")
                await self._refresh_rooms()
                room_lookup = {r.get("id"): r.get("name", "") for r in self.rooms}

            _LOGGER.debug(
                "Found %d rooms, %d scenes, %d devices, %d shades",
                len(self.rooms), len(raw_scenes), len(raw_devices), len(shade_positions),
            )

            devices: List[Dict[str, Any]] = []

            # Process regular devices
            for device in raw_devices:
                room_name = room_lookup.get(device.get("roomId"), "")
                device_type = device.get("subType") or device.get("type", "")

                devices.append({
                    "id": device.get("id"),
                    "type": device_type,
                    "subType": device_type,
                    "name": f"{room_name} {device.get('name', '')}",
                    "roomId": device.get("roomId"),
                    "roomName": room_name,
                    "level": device.get("level", 0),
                    "status": device.get("status", False),
                    "position": shade_positions.get(device.get("id"), 0) if device_type == "Shade" else 0,
                    "connectionStatus": device.get("connectionStatus", "online"),
                })

            # Process scenes - always typed "Scene" so shade scenes are treated
            # as scenes, not shades (original type is kept as sceneType)
            for scene in raw_scenes:
                room_name = room_lookup.get(scene.get("roomId"), "")

                devices.append({
                    "id": scene.get("id"),
                    "type": "Scene",
                    "subType": "Scene",
                    "sceneType": scene.get("type", ""),
                    "name": f"{room_name} {scene.get('name', '')}",
                    "roomId": scene.get("roomId"),
                    "roomName": room_name,
                    "level": 0,
                    "status": scene.get("status", False),
                    "position": 0,
                    "connectionStatus": "n/a",  # Scenes have no physical connection status
                })

            _LOGGER.debug("Prepared %d devices and scenes", len(devices))
            return devices

        except CrestronApiError:
            raise
        except Exception as error:
            _LOGGER.error("Error getting devices: %s", error)
            raise CrestronApiError(f"Error getting devices: {error}") from error

    async def get_shade_state(self, shade_id: int) -> Dict[str, Any]:
        """Get the state of a specific shade."""
        response = await self._api_request("GET", f"/shades/{shade_id}")
        return response.get("shades", [{}])[0]

    async def set_light_state(self, light_id: int, level: int, time: int = 0) -> None:
        """Set the state of a light."""
        level = max(0, min(level, CRESTRON_MAX_LEVEL))
        light_state = {
            "lights": [
                {
                    "id": light_id,
                    "level": level,
                    "time": time,
                }
            ]
        }
        
        await self._api_request("POST", "/lights/setstate", light_state)

    async def set_shade_position(self, shade_id: int, position: int) -> None:
        """Set the position of a shade."""
        position = max(0, min(position, CRESTRON_MAX_LEVEL))
        shade_state = {
            "shades": [
                {
                    "id": shade_id,
                    "position": position,
                }
            ]
        }
        
        await self._api_request("POST", "/shades/setstate", shade_state)

    async def execute_scene(self, scene_id: int) -> None:
        """Execute a scene."""
        await self._api_request("POST", f"/scenes/recall/{scene_id}", {})

    async def get_sensors(self) -> List[Dict[str, Any]]:
        """Get all sensors from the Crestron Home system."""
        response = await self._api_request("GET", "/sensors")
        return response.get("sensors", [])

    # ── Thermostat API methods ──────────────────────────────────────

    async def get_thermostats(self) -> List[Dict[str, Any]]:
        """Get all thermostats from the Crestron Home system."""
        response = await self._api_request("GET", "/thermostats")
        return response.get("thermostats", [])

    async def set_thermostat_mode(self, thermostat_id: int, mode: str) -> None:
        """Set thermostat HVAC mode (Off, Heat, Cool, Auto)."""
        await self._api_request("POST", "/thermostats/mode", {
            "thermostats": [
                {
                    "id": thermostat_id,
                    "mode": mode,
                }
            ],
        })

    async def set_thermostat_setpoint(
        self, thermostat_id: int, setpoint_type: str, temperature: int
    ) -> None:
        """Set thermostat target temperature (Crestron tenths-of-degree)."""
        await self._api_request("POST", "/thermostats/SetPoint", {
            "id": thermostat_id,
            "setpoints": [
                {
                    "type": setpoint_type,
                    "temperature": temperature,
                }
            ],
        })

    async def set_thermostat_fan_mode(self, thermostat_id: int, mode: str) -> None:
        """Set thermostat fan mode (Auto, On)."""
        await self._api_request("POST", "/thermostats/fanmode", {
            "thermostats": [
                {
                    "id": thermostat_id,
                    "mode": mode,
                }
            ],
        })

    async def set_thermostat_schedule(self, thermostat_id: int, mode: str) -> None:
        """Set thermostat schedule state (Run, Hold)."""
        await self._api_request("POST", "/thermostats/schedule", {
            "thermostats": [
                {
                    "id": thermostat_id,
                    "mode": mode,
                }
            ],
        })

    @staticmethod
    def crestron_to_percentage(value: int) -> int:
        """Convert a Crestron range value (0-65535) to percentage (0-100)."""
        if value <= 0:
            return 0
        return round((value / CRESTRON_MAX_LEVEL) * 100)

    @staticmethod
    def percentage_to_crestron(value: int) -> int:
        """Convert a percentage (0-100) to Crestron range value (0-65535)."""
        if value <= 0:
            return 0
        return round((CRESTRON_MAX_LEVEL * value) / 100)
