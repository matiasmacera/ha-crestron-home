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
- **Automatic Discovery**: Automatically discovers all compatible devices
- **Room-Based Organization**: Devices are automatically organized by room on the Home Assistant dashboard
- **Device Name Filtering**: Wildcard pattern matching to hide unwanted devices (e.g., `%bathroom%`)
- **Selective Platform Loading**: Choose which device types to enable/disable without reinstalling
- **Optimistic State Updates**: Immediate UI feedback when controlling devices (2s cooldown)
- **Command Debouncing**: Slider controls (brightness, shade position) are debounced at 200ms to prevent API flooding
- **Parallel API Polling**: Devices, sensors, and thermostats are fetched concurrently for faster updates
- **Change Detection**: Lightweight field-based change detection without deep copy overhead
- **Robust Error Handling**: Proper session management, authentication retry, and connection error recovery
- **Multi-language**: English and Spanish translations

### Supported Device Types

| Crestron Device Subtype | Home Assistant Entity | Features | Testing Status |
|-------------------------|------------------------|----------|----------------|
| Dimmer                  | Light                  | On/Off, Brightness, Fade Transition, Debounce | Tested |
| Switch                  | Light                  | On/Off | Tested |
| Shade                   | Cover                  | Open/Close, Position, Stop, Debounce | Tested |
| Scene                   | Scene                  | Activate | Tested |
| OccupancySensor         | Binary Sensor         | Occupancy detection | Tested |
| DoorSensor              | Binary Sensor         | Door open/closed status, Battery level | Not tested |
| PhotoSensor             | Sensor                | Light level measurement (lux) | Not tested |
| Thermostat              | Climate               | Temperature, Fan modes, HVAC modes, HVAC action | Tested |

> **Note**: The OccupancySensor and Thermostat implementations have been thoroughly tested. The DoorSensor and PhotoSensor implementations are included but have not been tested with actual hardware yet.

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
- **Dependencies**: aiohttp 3.8.0 or newer (for API communication)
- **Hardware Requirements**:
  - A Crestron Home system with CWS (Crestron Web Service) enabled
  - Network connectivity between Home Assistant and the Crestron processor
  - A valid API token for the Crestron Home system

## Architecture

### Component Structure

```
custom_components/crestron_home/
├── __init__.py          # Integration setup, platform loading, reload logic
├── api.py               # Crestron REST API client (login, devices, sensors, thermostats)
├── config_flow.py       # Configuration UI (setup + options flow)
├── const.py             # Constants, defaults, and device-type-to-platform mapping
├── coordinator.py       # DataUpdateCoordinator for periodic polling
├── device_manager.py    # Device processing, change detection, composite key storage
├── entity.py            # CrestronBaseEntity (shared boilerplate, optimistic cooldown, debouncing)
├── models.py            # CrestronDevice dataclass
├── manifest.json        # Integration metadata
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

1. **API Client** (`api.py`): Handles HTTPS communication with the Crestron CWS server. Uses the shared Home Assistant aiohttp session for all requests (login + API) to avoid connection leaks. Sessions expire after 10 minutes with automatic re-login.

2. **Device Manager** (`device_manager.py`): Maintains a consistent snapshot of all devices using composite keys (`device:N`, `sensor:N`, `thermostat:N`) to prevent ID collisions between different API namespaces. Uses lightweight tuple-based snapshots for change detection instead of deep copies. Room name resolution uses an O(1) dictionary lookup.

3. **Coordinator** (`coordinator.py`): Uses Home Assistant's `DataUpdateCoordinator` pattern to poll devices at the configured interval. Returns a dictionary of devices organized by type with O(1) lookup by device ID.

4. **Base Entity** (`entity.py`): `CrestronBaseEntity` absorbs all duplicated boilerplate from the 6 platform files: device/entity setup, coordinator data lookup, hidden entity handling, optimistic cooldown (2s), and command debouncing (200ms). All platforms inherit from this class.

5. **Platform Entities**: Each platform (light, cover, scene, climate, sensor, binary_sensor) creates entities that read state from the coordinator and send commands through the API client. Slider-type controls (brightness, shade position) use debouncing to prevent flooding the Crestron API.

6. **Device Model** (`models.py`): The `CrestronDevice` dataclass normalizes different device types into a common structure. Handles room name deduplication in `full_name` (avoids "Room Room Device" when the API already includes the room name).

7. **Platform Mapping** (`const.py`): A single `DEVICE_TYPE_TO_PLATFORM` dictionary serves as the source of truth for mapping device types to HA platforms, used consistently across setup, unload, and cleanup operations.

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
