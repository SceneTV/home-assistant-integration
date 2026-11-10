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
- Config flow that pairs with the TV's Android TV Remote service (you type the six character code the TV shows; the launcher shows no approval prompt)
- One Home Assistant device per paired launcher
- Authenticated local WebSocket connection
- Media player, sensors, binary sensors, buttons, launcher mode select, notify entity, services, and bridge events
- The device page's **Visit** link opens the launcher's configuration portal (`http://<tv>:8765/configure`)

## Targeting TVs

Every `android_tv_bridge.*` service accepts a standard Home Assistant
`target`: devices, areas, entities (any SceneTV entity, such as the media
player), floors or labels. One call can reach several TVs; the command is sent
to all of them in parallel, and the call fails afterwards with a list of the
TVs that did not accept it.

```yaml
action: android_tv_bridge.show_popup
target:
  area_id: living_room
data:
  title: Dinner
  text: Food is ready
```

Older forms keep working: `data: device_id: <ha_device_id>` (a single string)
and `data: entry_id: <config_entry_id>`. When only one TV is configured, no
target is needed.

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

### Volume

When the launcher reports volume (`volume_level`, `volume_max`,
`volume_muted` in its state), the media player also supports
`media_player.volume_up`, `volume_down`, `volume_mute` and `volume_set`. These
send the launcher `volume_command` (`up`, `down`, `mute`, `unmute`). The
launcher only changes volume in steps, so `volume_set` sends as many `up` or
`down` steps as needed to reach the requested level.

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

## Action tiles

Action tiles are home screen tiles that run a Home Assistant script or scene.
The TV never stores a Home Assistant token.

1. In **Settings > Devices & services > SceneTV > Configure**, pick the scripts
   and scenes this TV may run ("Actions the TV can run").
2. On the TV's `/configure` page choose **Layout > Add > Home Assistant action**
   and pick one from the list, or create the tile from Home Assistant:

```yaml
service: android_tv_bridge.create_action_tile
target:
  device_id: your_home_assistant_device_id
data:
  action: script.movie_mode
  subtitle: Dims the lights
```

Pressing the tile runs the script or scene (only if it is still exposed) and
the tile shows "Done" or the error. Every press also fires
`android_tv_bridge.action_tile_pressed` with `action_id`, `source`,
`source_id`, `tile_title`, `profile_id` and `profile_name`, so you can use a
custom `action_id` (for example `movie_mode`) and handle it in an automation:

```yaml
trigger:
  - platform: event
    event_type: android_tv_bridge.action_tile_pressed
    event_data:
      action_id: movie_mode
```

Popup buttons (`popup_action`) with an exposed script or scene as their
`action_id` run it the same way.

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

### Popup buttons (actionable popups)

`show_popup` and `show_image` accept up to three `actions`. The TV shows them as
buttons next to a built-in **Dismiss** button, over whatever app is playing. The
remote's D-pad moves between them, OK presses one, and Back always closes the
popup. Each press fires `android_tv_bridge.popup_action`.

| Action field | Meaning |
| --- | --- |
| `id` | Required. 1 to 64 letters, digits or `_ . : -`. `dismiss` is reserved. Sent back as `action_id`. |
| `label` | Button text, up to 40 characters. Defaults to the id. |
| `style` | `default`, `primary` or `destructive` (red). |
| `default` | `true` on at most one action to give it focus. Otherwise Dismiss has focus, so a stray OK press never fires "Unlock". |
| `data` | Optional object, echoed back unchanged in the event. |

Other fields: `dismiss_label` renames the Dismiss button, and `popup_id` sets
the id that every popup event carries. When you leave `popup_id` out, the
integration generates one and returns it as a response, so a script can wait
for the answer to *this* popup. Popups with buttons take remote focus, and
`duration_ms` defaults to 30000 for them.

```yaml
sequence:
  - action: android_tv_bridge.show_image
    target:
      device_id: your_home_assistant_device_id
    data:
      title: Front door
      image_url: https://example.local/doorbell.jpg
      actions:
        - id: unlock
          label: Unlock
          style: destructive
        - id: talk
          label: Talk
    response_variable: popup
  - wait_for_trigger:
      - trigger: event
        event_type: android_tv_bridge.popup_action
        event_data:
          popup_id: "{{ popup.popup_id }}"
          action_id: unlock
    timeout: "00:00:30"
    continue_on_timeout: false
  - action: lock.unlock
    target:
      entity_id: lock.front_door
```

`popup_action` carries `action_id`, `action_label`, `popup_id`, `source`
(`popup`), `source_id` (same as `popup_id`), `profile_id`, `profile_name` and
`data`. Back, Dismiss, the timeout, `dismiss_popup` and a newer popup do not
fire `popup_action`; they fire `popup_dismissed` with `popup_id` and a `reason`
of `user`, `expired`, `dismissed` or `replaced` (`action` follows a button
press). Launchers that support buttons report `capabilities.popups.actions:
true`; older launchers ignore `actions` and show a plain popup.

## Web popups

`android_tv_bridge.show_web_popup` shows inline HTML or a web page. Give exactly
one of `html` or `url` (HTTPS, or HTTP on a private or local address). It is the
same native popup as `show_popup`, so it shows over any app; it defaults to the
center position. `show_popup` and `show_image` also take an `html` body with
`allow_javascript`, `interactive`, `width_dp` and `height_dp`. Scripts run unless
`allow_javascript` is false; `interactive` only gives the page remote focus.
Requires the launcher's Home Assistant popups setting and overlay permission
(SceneTV launcher with HTML popups; older launchers show web popups only over
the launcher).

```yaml
action: android_tv_bridge.show_web_popup
target:
  device_id: your_home_assistant_device_id
data:
  title: Laundry
  html: "<h1>The washer is done</h1>"
  position: center
  duration_ms: 10000
  width_dp: 600
  interactive: false
```

With `interactive: true` the remote can focus the page, and the page can call
`SceneTV.postAction(...)`. Each action arrives in Home Assistant as an
`android_tv_bridge.web_action` event.

## Media queue

Queue services drive the launcher's media queue:

| Service | Fields |
| --- | --- |
| `android_tv_bridge.queue_add` | `uri` (plus optional `package`, `title`, `subtitle`, `image_url`) or `items` (a list of those), optional `position`: `end` or `next` |
| `android_tv_bridge.queue_remove` | `item_id` |
| `android_tv_bridge.queue_move` | `item_id`, `to_index` |
| `android_tv_bridge.queue_clear` | none |
| `android_tv_bridge.queue_play` | optional `item_id` (otherwise resume) |
| `android_tv_bridge.queue_next` | none |
| `android_tv_bridge.queue_pause` | none |

```yaml
action: android_tv_bridge.queue_add
target:
  device_id: your_home_assistant_device_id
data:
  uri: https://www.youtube.com/watch?v=dQw4w9WgXcQ
  package: com.google.android.youtube.tv
  title: Tonight's first video
  position: next
```

The current queue appears in the entity state data under `queue`. Launchers
without queue support reject these services as unsupported.

## Events

The integration fires these Home Assistant events:

| Event | When |
| --- | --- |
| `android_tv_bridge.foreground_app_changed` | The foreground app changed |
| `android_tv_bridge.media_started`, `media_paused`, `media_stopped`, `media_changed` | Media session changes |
| `android_tv_bridge.popup_shown`, `popup_dismissed` | A popup appeared or closed (`popup_id`; `popup_dismissed` also has `reason`) |
| `android_tv_bridge.popup_action` | A popup button was pressed (`action_id`, `popup_id`, `data`, see [Popup buttons](#popup-buttons-actionable-popups)) |
| `android_tv_bridge.profile_changed` | The active SceneTV profile changed |
| `android_tv_bridge.command_result` | A command finished |
| `android_tv_bridge.web_action` | A web card or web popup called `SceneTV.postAction` (`surface`, `surface_id`, `action`, `data`) |
| `android_tv_bridge.home_config_changed` | The launcher home screen layout changed |
| `android_tv_bridge.queue_item_started`, `queue_item_finished`, `queue_item_failed` | A queue item changed state (`item_id`) |
| `android_tv_bridge.queue_paused` | The queue paused (`reason`, for example `user_input` or `foreground_changed`) |
| `android_tv_bridge.queue_finished` | The last queue item finished |
| `android_tv_bridge.event` | Any other launcher event; the launcher's event name is in `event_type` |

`remote_key_pressed`, `launcher_focused`, `launcher_item_selected` and
`idle_changed` are still mapped but the launcher does not send them yet.

Every event carries:

- `entry_id`: the config entry id.
- `device_id`: the launcher's own id (unchanged, so existing automations keep
  working). This is **not** a Home Assistant device id.
- `ha_device_id`: the Home Assistant device-registry id, for matching against
  `device_id` targets and device pages.

```yaml
triggers:
  - trigger: event
    event_type: android_tv_bridge.web_action
    event_data:
      action: lights_off
actions:
  - action: light.turn_off
    target:
      area_id: living_room
```

## Device triggers

Each SceneTV TV offers device triggers, so automations can be built from the
device page or the automation editor without writing event YAML. Pick the TV
under **When** > **Device**.

| Trigger | Fires on | Optional filter |
| --- | --- | --- |
| Opened an app | `foreground_app_changed` | `package`, such as `com.plexapp.android` |
| Started / paused / stopped playing | `media_started`, `media_paused`, `media_stopped` | `package` of the media app |
| Switched profile | `profile_changed` | `profile`, a profile name or id |
| Showed / dismissed a popup | `popup_shown`, `popup_dismissed` | |
| Popup button pressed | `popup_action` | `action_id` |
| Action tile pressed | `action_tile_pressed` | `action_id` |
| Web card or popup sent an action | `web_action` | `action_id` (matches `action`) |
| Started the next queue item / finished the queue | `queue_item_started`, `queue_finished` | |
| Became idle / became active | `idle_changed` | |

```yaml
triggers:
  - trigger: device
    domain: android_tv_bridge
    device_id: 0123456789abcdef  # the TV's Home Assistant device id
    type: app_opened
    package: com.netflix.ninja
```

The trigger variables include the original event as `trigger.event`, so
`trigger.event.data` holds the launcher payload.

Popup buttons, action tiles and the idle signal need launcher support that is
still in progress. Those triggers are listed now and start firing once the
launcher sends the events; nothing needs to change on the Home Assistant side.

## Blueprints

Automation blueprints live in
[`blueprints/automation/android_tv_bridge`](blueprints/automation/android_tv_bridge).
HACS does not install blueprints, so import each one from **Settings** >
**Automations & scenes** > **Blueprints** > **Import blueprint** with its URL:

| Blueprint | What it does | Import URL |
| --- | --- | --- |
| Movie mode | Dims lights when playback starts, raises them on pause, restores them on stop. Optional app list and after-sunset only. | `https://github.com/SceneTV/home-assistant-integration/blob/main/blueprints/automation/android_tv_bridge/movie_mode.yaml` |
| Doorbell popup | Shows a camera snapshot over any app when a doorbell or motion sensor fires. Optionally pauses playback. | `https://github.com/SceneTV/home-assistant-integration/blob/main/blueprints/automation/android_tv_bridge/doorbell_popup.yaml` |
| Bedtime lock | Warns before bedtime, then stops playback and goes home. Until morning, closes apps opened on the kids profile. | `https://github.com/SceneTV/home-assistant-integration/blob/main/blueprints/automation/android_tv_bridge/bedtime_lock.yaml` |
| Lights off when idle | Turns lights off after nothing has played for a while (and on the TV's idle trigger once the launcher sends it). | `https://github.com/SceneTV/home-assistant-integration/blob/main/blueprints/automation/android_tv_bridge/lights_off_when_idle.yaml` |
| Profile from presence | Switches the TV to a person's profile when they come home, and optionally to another when they leave. | `https://github.com/SceneTV/home-assistant-integration/blob/main/blueprints/automation/android_tv_bridge/presence_profile.yaml` |

Notes:

- The bedtime lock is a soft lock. SceneTV profiles do not restrict apps yet,
  so switching profile on the TV gets around it.
- The doorbell popup loads the snapshot from Home Assistant through the
  camera's short-lived access token, so the TV needs to reach the Home
  Assistant URL you enter.
- Profiles are matched by name, so renaming a profile on the TV means updating
  the blueprint inputs.

## Troubleshooting

- **Pairing was revoked or the launcher was reinstalled.** Home Assistant shows a "Re-authentication required" card for the TV. Open it, submit, and enter the code the TV shows if it asks. Entities and automations keep working with the new token.
- **The TV got a new IP address.** Open the integration's menu and choose **Reconfigure** to change the host or port. Discovery also updates the address automatically when it sees the TV again.
- **Repairs.** Settings > System > Repairs lists a SceneTV issue when the accessibility service is off or the "Display over other apps" permission is missing on the TV. Each issue says how to fix it on the TV and clears itself once the TV reports the change.
- **Entities are unavailable.** Entities go unavailable while the launcher's live connection is down, because commands cannot reach the TV. The **Connection** diagnostic sensor stays available and shows when the link comes back.
- **Reporting a bug.** Download diagnostics from the device page (three-dot menu > Download diagnostics) and attach the file to an issue. The pairing token, host and network addresses are redacted.

The **Idle**, **Last key** and **Selected item** entities are disabled by default because the launcher does not report them yet. You can enable them in the entity settings.

## Development

Tests use `pytest-homeassistant-custom-component`:

```bash
pip install -r requirements_test.txt
pytest
```

## Development status

The Android launcher API is still being implemented. Endpoint paths and payload shapes are isolated in `custom_components/android_tv_bridge/client.py` and `runtime.py` so the integration can track the launcher protocol as it stabilizes.

## License

Apache License 2.0. See [LICENSE](LICENSE).
