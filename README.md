# Home Assistant Integration for Crestron Home (Extended Fork)

<p align="center">
  <img src="logo.png" alt="Crestron Home" width="200">
</p>

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub License](https://img.shields.io/github/license/matiasmacera/ha-crestron-home.svg)](LICENSE)

> **Note**: This is a fork of the original [ha-crestron-home](https://github.com/ruudruud/ha-crestron-home) by [@ruudruud](https://github.com/ruudruud).
> This fork extends the original integration with additional device support, improved robustness, and new features.
> All credit for the original implementation goes to the original author.

This repository contains a custom component for Home Assistant that integrates with Crestron Home systems. It allows you to control your Crestron Home devices (lights, shades, scenes, thermostats) and monitor sensors through Home Assistant.

## Overview

The integration communicates with the Crestron Home CWS (Crestron Web Service) server via HTTPS to discover and control devices in your Crestron Home system.

## Features

- **Lights**: Control Crestron Home lights
  - Dimmers with brightness control, **fade in/out transitions**, and **command debouncing** (200ms)
  - Switches with on/off control
- **Shades**: Control Crestron Home shades (open, close, set position with **debouncing**, stop movement)
- **Scenes**: Activate Crestron Home scenes with room-based organization
- **Thermostats**: Climate control with temperature set point, fan modes (Auto/On/Circulate), HVAC modes (Off/Heat/Cool/Auto), and HVAC action inference
- **Sensors**: Support for Crestron Home sensors:
  - Occupancy sensors (binary sensors for presence detection)
  - Door sensors (binary sensors with battery level reporting)
  - Photo sensors (illuminance measurement in lux)
- **Configuration Flow**: Easy setup through the Home Assistant UI with options flow for reconfiguration
- **Re-authentication Flow**: If the API token becomes invalid, HA prompts for a new one instead of silently failing
- **Dynamic Device Discovery**: Devices added to Crestron Home appear in HA without a restart; removed devices become unavailable
- **Room-Based Organization**: Devices are automatically organized by room on the Home Assistant dashboard
- **Device Name Filtering**: Wildcard pattern matching to hide unwanted devices (e.g., `%bathroom%`)
- **Selective Platform Loading**: Choose which device types to enable/disable without reinstalling
- **Optimistic State Updates**: Immediate UI feedback when controlling devices (2s cooldown)
- **Command Debouncing**: Slider controls (brightness, shade position) are debounced at 200ms to prevent API flooding
- **Parallel API Polling**: Devices, sensors, and thermostats are fetched concurrently for faster updates
- **Efficient Change Detection**: Lightweight field-based change detection; entities skip state writes when their device didn't change
- **Room List Caching**: `/rooms` is only refetched every 20 polls (or immediately when an unknown room shows up)
- **Robust Error Handling**: Shared session management, automatic re-login with request retry on session expiry, and connection error recovery
- **Multi-language**: English and Spanish translations

### Supported Device Types

| Crestron Device Subtype | Home Assistant Entity | Features | Testing Status |
|-------------------------|------------------------|----------|----------------|
| Dimmer                  | Light                  | On/Off, Brightness, Fade Transition, Debounce | **Verified live on v0.5.0** |
| Switch                  | Light                  | On/Off | **Verified live on v0.5.0** |
| Shade                   | Cover                  | Open/Close, Position, Stop, Debounce | Tested (pre-0.5.0) |
| Scene                   | Scene                  | Activate | Tested (pre-0.5.0) |
| OccupancySensor         | Binary Sensor         | Occupancy detection | Tested (pre-0.5.0) |
| DoorSensor              | Binary Sensor         | Door open/closed status, Battery level | Not tested |
| PhotoSensor             | Sensor                | Light level measurement (lux) | Not tested |
| Thermostat              | Climate               | Temperature, Fan modes, HVAC modes, HVAC action | **Verified live on v0.5.0** |

> **Testing notes**: The v0.5.0 device-registry identifier migration was verified on a real-world installation: all devices migrated with 0 legacy identifiers remaining, 0 duplicated devices, 0 component errors in the log, and 0 unavailable entities. Lights (on/off/brightness) and thermostats (mode, current/target temperature) were confirmed reporting live state after the migration. Shade, Scene, and OccupancySensor were tested on real hardware in earlier versions but were not present in the v0.5.0 verification install; DoorSensor and PhotoSensor are implemented but have never been tested with actual hardware.

## Installation

### HACS (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed
2. Go to HACS > Integrations > Click the three dots in the top right corner > Custom repositories
3. Add `https://github.com/matiasmacera/ha-crestron-home` and select "Integration" as the category
4. Click "Add"
5. Search for "Crestron Home" in the HACS Integrations page
6. Click "Install"
7. Restart Home Assistant

> **Tip**: If you want the original version (without thermostat/transition support), use the [original repository](https://github.com/ruudruud/ha-crestron-home) instead.

### Manual Installation

1. Download the latest release from the GitHub repository
2. Extract the `custom_components/crestron_home` directory into your Home Assistant's `custom_components` directory
3. Restart Home Assistant

## Configuration

### Getting an API Token

![Crestron Home Integration](https://raw.githubusercontent.com/ruudruud/ha-crestron-home/main/images/web-api-settings.png)

1. Open the Crestron Home Setup app
2. Go to Settings > System Settings > Web API
3. Enable the Web API
4. Generate a new API token
5. Copy the token for use in the integration setup

### Setting up the Integration

1. Go to Home Assistant > Settings > Devices & Services
2. Click "Add Integration"
3. Search for "Crestron Home"
4. Enter the following information:
   - **Host**: The IP address or hostname of your Crestron Home processor
   - **API Token**: The token you generated in the Crestron Home Setup app
   - **Update Interval**: How often to poll for updates (in seconds)
     - Default: 15 seconds, minimum: 10 seconds
     - Lower values provide more responsive updates but increase system load
   - **Device Types to Include**: Select which types of devices to include
     - Lights: All dimmers and switches
     - Shades: All motorized shades/covers
     - Scenes: All scenes defined in your Crestron Home system
     - Binary Sensors: Occupancy sensors and door sensors
     - Sensors: Photosensors and other measurement devices
     - Thermostats: All climate control devices
   - **Ignored Device Names**: Patterns to filter out unwanted devices (use `%` as wildcard)
     - `%bathroom%` hides any device with "bathroom" in its name
     - `bathroom%` hides devices starting with "bathroom"
     - `%bathroom` hides devices ending with "bathroom"
   - **Verify SSL**: Enable if your Crestron processor has a valid SSL certificate (default: disabled)
5. Click "Submit"
6. Please allow for some time for the device synchronization.

### Reconfiguring the Integration

You can change the integration settings at any time without removing and re-adding it:

1. Go to Home Assistant > Settings > Devices & Services
2. Find the Crestron Home integration
3. Click "Configure"
4. Modify the settings as needed (update interval, device types, ignored names, SSL)
5. Click "Submit"

The integration will automatically reload with the new configuration. If you disable a device type, its entities will be cleanly removed from Home Assistant.

### Light Transitions (Fade In/Out)

Dimmable lights support native Home Assistant transitions for smooth fade effects. You can use transitions:

- **From automations/scripts**:
  ```yaml
  service: light.turn_on
  target:
    entity_id: light.living_room_dimmer
  data:
    brightness_pct: 80
    transition: 3  # Fade over 3 seconds
  ```
- **Fade to off**:
  ```yaml
  service: light.turn_off
  target:
    entity_id: light.living_room_dimmer
  data:
    transition: 5  # Fade out over 5 seconds
  ```

## Requirements

- **Home Assistant Core**: Version 2024.2 or newer
- **Python**: Version 3.11 or newer
- **Dependencies**: None beyond Home Assistant itself (uses HA's bundled aiohttp)
- **Hardware Requirements**:
  - A Crestron Home system with CWS (Crestron Web Service) enabled
  - Network connectivity between Home Assistant and the Crestron processor
  - A valid API token for the Crestron Home system

## Architecture

### Component Structure

```
custom_components/crestron_home/
├── __init__.py          # Integration setup, platform loading, reload logic, identifier migration
├── api.py               # Crestron REST API client (login, devices, sensors, thermostats, room caching)
├── config_flow.py       # Configuration UI (setup + options + reauth flow)
├── const.py             # Constants, defaults, and type/platform mappings
├── coordinator.py       # DataUpdateCoordinator for periodic polling
├── device_manager.py    # Device processing, change detection, pruning, composite key storage
├── entity.py            # CrestronBaseEntity + shared dynamic-discovery helper
├── models.py            # CrestronDevice dataclass
├── manifest.json        # Integration metadata
├── strings.json         # Source strings for translations
├── translations/        # Localization files (en, es)
├── icon.png             # Integration icon (256x256)
├── logo.png             # Integration logo (1024x1024)
├── light.py             # Light platform (dimmer + switch with debouncing)
├── cover.py             # Cover platform (shades with debouncing)
├── scene.py             # Scene platform
├── climate.py           # Climate platform (thermostats)
├── binary_sensor.py     # Binary sensor platform (occupancy, door)
└── sensor.py            # Sensor platform (photo sensor)
```

### How It Works

1. **API Client** (`api.py`): Handles HTTPS communication with the Crestron CWS server. Uses the shared Home Assistant aiohttp session for all requests (login + API) to avoid connection leaks. Sessions expire after 10 minutes with automatic re-login, and a request that hits a 401 is retried once after re-authenticating. Room and shade lookups are O(1) dictionaries, and the room list is cached across polls.

2. **Device Manager** (`device_manager.py`): Maintains a consistent snapshot of all devices using composite keys (`device:N`, `scene:N`, `sensor:N`, `thermostat:N`) to prevent ID collisions between different API namespaces. Uses lightweight tuple-based snapshots for change detection (including thermostat raw fields like temperature and mode) and publishes the set of changed devices each poll. Devices that disappear from the API are pruned so their entities go unavailable.

3. **Coordinator** (`coordinator.py`): Uses Home Assistant's `DataUpdateCoordinator` pattern to poll devices at the configured interval. Returns a dictionary of devices organized by type with O(1) lookup by device ID. Raises `ConfigEntryAuthFailed` on persistent auth errors to trigger the reauth flow.

4. **Base Entity** (`entity.py`): `CrestronBaseEntity` absorbs all duplicated boilerplate from the 6 platform files: device/entity setup, coordinator data lookup, hidden entity handling, availability (coordinator health + device connection), optimistic cooldown (2s), and command debouncing (200ms). Entities skip redundant state writes when their device didn't change in the last poll. A shared `async_setup_platform_entities` helper gives every platform dynamic device discovery.

5. **Platform Entities**: Each platform (light, cover, scene, climate, sensor, binary_sensor) creates entities that read state from the coordinator and send commands through the API client. Slider-type controls (brightness, shade position) use debouncing to prevent flooding the Crestron API.

6. **Device Model** (`models.py`): The `CrestronDevice` dataclass normalizes different device types into a common structure. Handles room name deduplication in `full_name` (avoids "Room Room Device" when the API already includes the room name).

7. **Type Mappings** (`const.py`): `CRESTRON_TYPE_TO_DEVICE_TYPE` (Crestron subtype → device type) and `DEVICE_TYPE_TO_PLATFORM` (device type → HA platform) are the single source of truth for type mapping, used consistently across the API client, device manager, setup, unload, and cleanup.

## Troubleshooting

### Connection Issues

- Ensure your Crestron Home processor is reachable from your Home Assistant instance
- Verify that the Web API is enabled in the Crestron Home Setup app
- Check that the API token is valid and has not expired
- Verify that the correct host/IP is configured
- If you see SSL errors, try disabling "Verify SSL" in the integration configuration

### Missing Devices

- Make sure the device types you want to control are selected in the integration configuration
- Check if the device name matches any of the "Ignored Device Names" patterns
- Verify that the devices are properly configured in your Crestron Home system
- Check Home Assistant logs for any error messages from the integration

### Device Type Configuration

When you configure the integration, you can select which device types to include. Here's what happens when you change these settings:

- **Adding Device Types**: When you add a device type, the integration will discover and add all devices of that type to Home Assistant.
- **Removing Device Types**: When you remove a device type, all entities of that type will be completely removed from Home Assistant. This ensures your Home Assistant instance stays clean without orphaned entities.
- **Re-adding Device Types**: If you later re-add a device type, the entities will be recreated with default settings.

> **Note**: Any customizations you made to entities (such as custom names, icons, or area assignments) will be lost when you remove their device type from the configuration.

### Thermostat Not Showing Correct Temperature

The Crestron API reports temperatures in "deci-degrees" (e.g., 275 = 27.5°C). The integration automatically converts these values. If temperatures seem wrong, check:

- The temperature unit setting in your Crestron Home system
- The unit system configured in Home Assistant (Settings > General)

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### v0.5.0 (2026-07-09)
- **Correctness Fixes**:
  - Fixed device registry ID collisions: registry identifiers are now namespaced by device type (`light_5`, `scene_5`, ...) instead of the bare numeric ID, which could merge unrelated devices (e.g., a scene and a light sharing an ID). Existing registry entries are migrated in place, preserving area assignments and custom names
  - Scenes now use their own internal namespace (`scene:N`), fully separating them from `/devices` IDs
  - Entity availability now reflects coordinator health: if the Crestron processor becomes unreachable, entities show as unavailable instead of frozen at their last state
  - Devices removed from Crestron are pruned each poll and their entities become unavailable (previously they lingered with stale state)
  - The SSL verification setting is now honored when validating credentials in the config/options flow
  - Pending debounced commands are cancelled when an entity is removed
- **Dynamic Device Discovery**: All platforms (previously only thermostats) hot-add devices that appear in Crestron Home — no HA restart needed
- **Re-authentication Flow**: An invalid API token now triggers HA's reauth prompt (enter the new token in the UI) instead of silent polling errors
- **Performance**:
  - `api.py` room/shade matching went from O(devices × rooms) linear scans to O(1) dict lookups (thousands of comparisons saved per poll)
  - The `/rooms` endpoint is cached and only refetched every 20 polls, or immediately when an unknown room appears (one fewer HTTP request per poll)
  - Entities skip state writes when their device didn't change in the last poll (change detection now also covers thermostat raw fields, door battery, and sensor values)
  - A 401 mid-session re-authenticates and retries the request once instead of failing the whole poll
  - Exact brightness conversion (0-65535 ↔ 0-255 is lossless), so the brightness slider no longer drifts by 1-2 points
- **Code Quality**:
  - New shared `async_setup_platform_entities` helper removes the per-platform setup boilerplate
  - Unified the Crestron subtype mapping into `CRESTRON_TYPE_TO_DEVICE_TYPE` (was triplicated across api.py/device_manager.py)
  - Removed dead code: unused API methods, `DEBUG_MODE` logging block, unused parameters, redundant `unique_id` overrides
  - Proper entity hiding via `entity_registry_visible_default` (the old `_attr_hidden_by` assignment was a no-op)
  - Removed the `aiohttp` requirement from the manifest (HA bundles it; pinning could conflict on HA updates)
- **Infrastructure**:
  - Added GitHub Actions CI: hassfest + HACS validation on every push/PR and weekly
  - Added `strings.json` as the translation source of truth; added missing `verify_ssl` labels and reauth strings (en/es)

### v0.4.0 (2026-02-12)
- **Performance Optimizations**:
  - Replaced `deepcopy` with lightweight tuple-based snapshots for change detection (lower memory, faster polls)
  - Fixed ID collision risk between devices/sensors/thermostats using composite keys (`device:N`, `sensor:N`, `thermostat:N`)
  - Eliminated `aiohttp.ClientSession` leak on login — now reuses the shared HA session for all requests
  - Room name resolution changed from O(N) linear scan to O(1) dictionary lookup
- **Command Debouncing**: Added 200ms debounce for brightness sliders and shade position controls to prevent API flooding
- **Code Quality**:
  - Created `CrestronBaseEntity` base class absorbing all duplicated boilerplate from 6 platform files (~480 lines removed)
  - Unified device-type-to-platform mapping into a single `DEVICE_TYPE_TO_PLATFORM` constant (was duplicated 4 times)
  - Fixed `_device_info` naming collision with HA's `_attr_device_info` (renamed to `_crestron_device`)
  - Removed dead code: unused imports, environment variable fallbacks, unused API methods
  - Fixed mutable default `[]` to immutable `()` in constants
- **Branding**: Added Crestron Home icon and logo files for HACS and HA
- **Translations**: Added Spanish language support (`translations/es.json`)

### v0.3.0 (2026-02-11)
- **Light Transitions**: Added native Home Assistant transition support for dimmable lights (fade in/out)
- **Robustness Improvements**:
  - Fixed device name deduplication (avoids "Room Room Device" when API already includes room name)
  - Added O(1) device lookups in coordinator data (dict-based instead of list iteration)
  - Improved thermostat HVAC action inference with deadband to prevent rapid toggling
  - Added explicit `running` field support from API for accurate HVAC action
  - Parallel API calls for devices, sensors, and thermostats
  - Added change detection logging between polls
  - Improved error handling with proper exception hierarchy
  - Session management with login lock to prevent concurrent login attempts
  - Entity registry cleanup when device types are disabled
  - Options flow for reconfiguration without re-adding the integration

### v0.2.0
- **Thermostat Support**: Added climate platform with temperature control, fan modes, and HVAC modes
- **Initial Fork**: Extended the original integration with thermostat support and various fixes

### v0.1.0 (Original)
- Initial implementation by [@ruudruud](https://github.com/ruudruud)
- Light, shade, scene, and sensor support

## Acknowledgments

- This fork is based on the original work by [@ruudruud](https://github.com/ruudruud) in [ha-crestron-home](https://github.com/ruudruud/ha-crestron-home).
- The original project was inspired by and adapted from the [Homebridge Crestron Home plugin](https://github.com/evgolsh/homebridge-crestron-home).

## Disclaimer

This integration is an independent project and is not affiliated with, endorsed by, or approved by Crestron Electronics, Inc. All product names, trademarks, and registered trademarks are the property of their respective owners. The use of these names, trademarks, and brands does not imply endorsement.

This software is provided "as is," without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.

Users are responsible for ensuring that their use of this integration complies with all applicable laws and regulations, as well as any agreements they have with third parties, including Crestron Electronics, Inc. It is the user's responsibility to obtain any necessary permissions or licenses before using this integration.
