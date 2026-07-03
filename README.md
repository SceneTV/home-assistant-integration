# SceneTV Home Assistant Integration

Custom Home Assistant integration for the SceneTV Android TV launcher bridge.

## HACS installation

This repository is structured as a HACS custom integration repository.

1. In Home Assistant, open HACS.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add this repository URL.
4. Select **Integration** as the category.
5. Install **SceneTV Android TV Bridge**.
6. Restart Home Assistant.
7. Go to **Settings -> Devices & services -> Add integration** and search for **SceneTV Android TV Bridge**.

## Manual installation

Copy `custom_components/android_tv_bridge` into your Home Assistant config directory:

```text
<home-assistant-config>/custom_components/android_tv_bridge
```

Restart Home Assistant, then add **SceneTV Android TV Bridge** from **Settings -> Devices & services**.

## Features

Initial scope:

- Zeroconf discovery for `_scenetv._tcp.local.`
- Config flow with TV-approved pairing
- One Home Assistant device per paired launcher
- Authenticated local WebSocket connection
- Sensors, binary sensors, buttons, launcher mode select, services, and bridge events

## Development status

The Android launcher API is still being implemented. Endpoint paths and payload shapes are isolated in `custom_components/android_tv_bridge/client.py` and `runtime.py` so the integration can track the launcher protocol as it stabilizes.
