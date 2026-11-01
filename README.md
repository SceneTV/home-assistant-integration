# SceneTV Home Assistant Integration

Custom Home Assistant integration for the SceneTV Android TV launcher bridge.

## HACS installation

This repository is structured as a HACS custom integration repository.

1. In Home Assistant, open HACS.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/SceneTV/home-assistant-integration`.
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
- Media player, sensors, binary sensors, buttons, launcher mode select, notify entity, services, and bridge events
- Camera snapshot popups for cameras configured on the TV (`show_camera`)

## Media controls

SceneTV exposes the active Android media session as a Home Assistant media player
entity. Standard Home Assistant media actions map to the launcher
`media_command` envelope:

- `play`
- `pause`
- `play_pause`
- `stop`
- `next`
- `previous`

The lower-level `android_tv_bridge.media_command` service also accepts `rewind`
and `fast_forward` for automations that need those remote-control keys.

## Key events

Use the `android_tv_bridge.send_key` service to send supported remote-control key events to a paired SceneTV launcher. The service forwards the selected key as a `send_key` command payload, for example:

```yaml
service: android_tv_bridge.send_key
data:
  device_id: your_home_assistant_device_id
  key: DPAD_CENTER
```

Supported D-pad keys are `DPAD_UP`, `DPAD_DOWN`, `DPAD_LEFT`, `DPAD_RIGHT`, and `DPAD_CENTER`. The aliases `UP`, `DOWN`, `LEFT`, `RIGHT`, `CENTER`, `SELECT`, `OK`, and `ENTER` are also accepted.

## App and activity launch

Use `android_tv_bridge.launch_app` to open an app by package name, or
`android_tv_bridge.launch_activity` to open a specific activity.

```yaml
service: android_tv_bridge.launch_activity
data:
  device_id: your_home_assistant_device_id
  package: com.example.app
  activity: .MainActivity
```

The activity service also accepts a single Android component string:

```yaml
service: android_tv_bridge.launch_activity
data:
  device_id: your_home_assistant_device_id
  component: com.example.app/.MainActivity
```

## Deep-link shortcuts

Use `android_tv_bridge.open_uri` or `android_tv_bridge.launch_intent` to open a
deep link immediately. Use `android_tv_bridge.create_deep_link_shortcut` to add
a persistent shortcut tile to the active SceneTV launcher profile.

```yaml
service: android_tv_bridge.create_deep_link_shortcut
data:
  device_id: your_home_assistant_device_id
  title: YouTube Subscriptions
  subtitle: YouTube
  uri: https://www.youtube.com/feed/subscriptions
  package: com.google.android.youtube.tv
  launch_mode: play_then_exit
```

## Popup notifications

SceneTV exposes popup notifications as Home Assistant services and as a notify
entity. The services are the most flexible option for automations because they
support position, duration, color, transparency, font size, interrupt mode, and
image payloads.

```yaml
action: android_tv_bridge.show_popup
data:
  device_id: your_home_assistant_device_id
  title: Doorbell
  text: Someone is at the front door
  position: top-right
  color: teal
  transparency: 25%
  duration_ms: 10000
```

Image popups can use an HTTP/HTTPS image URL or a base64 image payload:

```yaml
action: android_tv_bridge.show_image
data:
  device_id: your_home_assistant_device_id
  title: Camera snapshot
  text: Driveway motion detected
  image_url: https://example.local/snapshot.jpg
  position: center
  duration_ms: 15000
```

For simple text notifications, use the generated notify entity with Home
Assistant's `notify.send_message` action:

```yaml
action: notify.send_message
target:
  entity_id: notify.living_room_tv_popup_notifications
data:
  title: SceneTV
  message: Movie night mode is active
```

Dashboard cards can send fixed popups by calling the service from a button:

```yaml
type: button
name: Send TV popup
tap_action:
  action: call-service
  service: android_tv_bridge.show_popup
  data:
    device_id: your_home_assistant_device_id
    title: SceneTV
    text: Test notification from the dashboard
    duration_ms: 5000
```

## Camera popups

`android_tv_bridge.show_camera` shows a snapshot popup from a camera that is
configured on the TV in SceneTV's camera settings. Home Assistant only sends the
camera id (for example `front_door`); stream URLs and camera credentials stay on
the TV. The popup is drawn over other apps, pauses playing media by default and
resumes it when the popup closes.

The service needs a SceneTV version that advertises the `show_camera` command;
older launchers get a clear error instead of a silent no-op.

| Field | Default | Notes |
| --- | --- | --- |
| `camera` | required | Camera id configured on the TV |
| `title` | camera name | Optional popup title |
| `position` | `top-right` | `top-left`, `top-right`, `bottom-left`, `bottom-right`, `center` |
| `size` | `medium` | `small`, `medium`, `large` |
| `duration_ms` | `15000` | 1000 to 600000 |
| `interrupt` | `false` | Take remote focus so OK or Back dismisses the popup |
| `profiles` | camera setting | SceneTV profile ids or names that may see the popup |
| `pause_media` | camera setting | Override whether playing media is paused |

Doorbell example:

```yaml
alias: Doorbell camera on the TV
triggers:
  - trigger: state
    entity_id: binary_sensor.front_doorbell
    to: "on"
actions:
  - action: android_tv_bridge.show_camera
    data:
      device_id: your_home_assistant_device_id
      camera: front_door
      title: Someone is at the door
      position: top-right
      size: medium
      duration_ms: 20000
      # Optional: only show it while one of these SceneTV profiles is active.
      profiles:
        - Living room
```

The TV answers after it has the first snapshot, so the service waits up to
12 seconds by default (`timeout_ms` overrides it). It raises an error when the
camera id is unknown or disabled on the TV, Home Assistant popups are turned off
on the TV, SceneTV may not draw over other apps, or the snapshot cannot be
fetched. When the active SceneTV profile is not one of the camera's popup
profiles, the TV drops the popup and the service returns quietly. Triggering the
same camera again while it is showing extends the popup instead of stacking a
new one. Use `android_tv_bridge.dismiss_popup` to close it early.

## Development status

The Android launcher API is still being implemented. Endpoint paths and payload shapes are isolated in `custom_components/android_tv_bridge/client.py` and `runtime.py` so the integration can track the launcher protocol as it stabilizes.
