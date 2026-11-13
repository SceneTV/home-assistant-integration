"""Tests for kids profile and screen time entities, services and events (#34)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.android_tv_bridge.const import DOMAIN, EVENT_MAP
from custom_components.android_tv_bridge.runtime import AndroidTVBridgeRuntime
from custom_components.android_tv_bridge.services import SERVICE_SCHEMAS

from .test_services import _setup

LAUNCHER_ID = "launcher-1"

KIDS = {
    "id": 2,
    "name": "Kids",
    "active": True,
    "restricted": True,
    "screen_time_today_min": 42,
    "daily_budget_min": 90,
    "remaining_min": 48,
    "bedtime_start": "20:00",
    "bedtime_end": "07:00",
    "limit_state": "ok",
}
PARENT = {
    "id": 1,
    "name": "Living Room",
    "active": False,
    "restricted": False,
    "screen_time_today_min": 10,
    "daily_budget_min": None,
    "remaining_min": None,
    "bedtime_start": None,
    "bedtime_end": None,
    "limit_state": "ok",
}
NEW_STATE = {
    "profiles": [PARENT, KIDS],
    "parental_enforcement_active": True,
    "profile_locked": False,
    "parental_pin_set": True,
}
OLD_STATE = {"profiles": [{"id": 1, "name": "Living Room", "active": True}]}


async def _start(
    hass: HomeAssistant, state: dict[str, Any]
) -> tuple[AndroidTVBridgeRuntime, list[tuple[str, dict[str, Any]]]]:
    """Set the integration up against a fake launcher state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LAUNCHER_ID,
        data={
            CONF_HOST: "192.168.1.50",
            CONF_PORT: 8765,
            CONF_NAME: "Living Room TV",
            "token": "t",
        },
    )
    entry.add_to_hass(hass)
    sent: list[tuple[str, dict[str, Any]]] = []

    async def fake_start(self: AndroidTVBridgeRuntime) -> None:
        self.metadata = {"device_id": LAUNCHER_ID, "display_name": "Living Room TV"}
        self.connected = True
        self._ws_task = hass.async_create_background_task(
            asyncio.Event().wait(), "fake launcher websocket"
        )
        self.coordinator.async_set_updated_data(dict(state))

    async def fake_send(self, command_type, payload=None, *, timeout_ms=None):
        sent.append((command_type, dict(payload or {})))
        return {"status": "succeeded"}

    with (
        patch.object(AndroidTVBridgeRuntime, "async_start", fake_start),
        patch.object(AndroidTVBridgeRuntime, "async_send_command", fake_send),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    # Keep recording after setup: the patch above only covered setup.
    runtime.async_send_command = lambda c, p=None, **kw: fake_send(runtime, c, p, **kw)
    return runtime, sent


async def test_profile_entities_from_state(hass: HomeAssistant) -> None:
    await _start(hass, NEW_STATE)

    today = hass.states.get("sensor.living_room_tv_kids_screen_time_today")
    assert today is not None
    assert today.state == "42"
    assert today.attributes["state_class"] == "total_increasing"
    assert today.attributes["unit_of_measurement"] == "min"
    assert today.attributes["limit_state"] == "ok"
    assert today.attributes["profile_id"] == 2

    assert hass.states.get("sensor.living_room_tv_kids_screen_time_remaining").state == "48"
    assert hass.states.get("number.living_room_tv_kids_daily_screen_time").state == "90"
    assert hass.states.get("time.living_room_tv_kids_bedtime_start").state == "20:00:00"
    assert hass.states.get("time.living_room_tv_kids_bedtime_end").state == "07:00:00"
    assert hass.states.get("switch.living_room_tv_kids_restricted").state == "on"

    # No budget or bedtime on the parent profile: unknown, not an error.
    parent = "living_room_tv_living_room"
    assert hass.states.get(f"sensor.{parent}_screen_time_remaining").state == "unknown"
    assert hass.states.get(f"number.{parent}_daily_screen_time").state == "unknown"
    assert hass.states.get(f"time.{parent}_bedtime_start").state == "unknown"
    assert hass.states.get(f"switch.{parent}_restricted").state == "off"

    assert hass.states.get("binary_sensor.living_room_tv_parental_enforcement").state == "on"
    assert hass.states.get("binary_sensor.living_room_tv_profile_locked").state == "off"


async def test_old_launcher_gets_no_profile_entities(hass: HomeAssistant) -> None:
    await _start(hass, OLD_STATE)

    for domain in ("number", "switch", "time"):
        assert hass.states.async_entity_ids(domain) == []
    assert not [
        entity_id
        for entity_id in hass.states.async_entity_ids("sensor")
        if "screen_time" in entity_id
    ]
    for key in ("parental_enforcement", "profile_locked"):
        state = hass.states.get(f"binary_sensor.living_room_tv_{key}")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE


async def test_part_a_only_launcher_gets_switch_only(hass: HomeAssistant) -> None:
    await _start(
        hass,
        {
            "profiles": [{"id": 2, "name": "Kids", "restricted": True}],
            "parental_enforcement_active": False,
        },
    )
    assert hass.states.get("switch.living_room_tv_kids_restricted").state == "on"
    assert hass.states.async_entity_ids("number") == []
    assert hass.states.get("binary_sensor.living_room_tv_parental_enforcement").state == "off"
    assert (
        hass.states.get("binary_sensor.living_room_tv_profile_locked").state
        == STATE_UNAVAILABLE
    )


async def test_new_profile_adds_entities_and_removed_goes_unavailable(
    hass: HomeAssistant,
) -> None:
    runtime, _ = await _start(hass, {"profiles": [PARENT]})
    assert hass.states.get("switch.living_room_tv_kids_restricted") is None

    runtime._merge_state({"profiles": [PARENT, KIDS]})
    await hass.async_block_till_done()
    assert hass.states.get("switch.living_room_tv_kids_restricted").state == "on"

    runtime._merge_state({"profiles": [PARENT]})
    await hass.async_block_till_done()
    assert (
        hass.states.get("switch.living_room_tv_kids_restricted").state
        == STATE_UNAVAILABLE
    )

    # Coming back does not add a duplicate.
    runtime._merge_state({"profiles": [PARENT, KIDS]})
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids("switch")) == 2


async def test_screen_time_resets_at_midnight(hass: HomeAssistant) -> None:
    runtime, _ = await _start(hass, NEW_STATE)
    runtime._merge_state({"profiles": [PARENT, {**KIDS, "screen_time_today_min": 0}]})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.living_room_tv_kids_screen_time_today").state == "0"


async def test_profile_entities_send_commands(hass: HomeAssistant) -> None:
    _, sent = await _start(hass, NEW_STATE)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.living_room_tv_kids_restricted"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.living_room_tv_kids_daily_screen_time", "value": 120},
        blocking=True,
    )
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.living_room_tv_kids_bedtime_start", "time": "19:30:00"},
        blocking=True,
    )
    assert sent == [
        ("set_profile_restricted", {"profile_id": 2, "restricted": False}),
        ("set_profile_policy", {"profile_id": 2, "daily_budget_min": 120}),
        ("set_profile_policy", {"profile_id": 2, "bedtime_start": "19:30"}),
    ]


async def test_profile_services_payloads(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    entry_id = ctx["entries"][0].entry_id
    calls = [
        (
            "set_profile_policy",
            {"profile": "Kids", "daily_budget_min": 60, "bedtime_start": "20:15:00"},
        ),
        ("set_profile_policy", {"profile_id": 2, "bedtime_end": None}),
        (
            "set_profile_policy",
            {"profile": "Kids", "clear_daily_budget": True, "clear_bedtime": True},
        ),
        ("grant_extra_time", {"profile": "Kids", "minutes": 15}),
        ("lock_profile", {"profile": "Kids"}),
        ("unlock_profile", {}),
        ("set_profile_restricted", {"profile_id": 2, "restricted": True}),
        (
            "set_profile_allowed_apps",
            {"profile": "Kids", "packages": ["com.a", " ", "com.b"]},
        ),
        (
            "set_profile_allowed_apps",
            {"profile": "Kids", "packages": "com.c", "mode": "remove"},
        ),
    ]
    for service, data in calls:
        await hass.services.async_call(
            DOMAIN, service, {"entry_id": entry_id, **data}, blocking=True
        )
    assert [c[:2] for c in ctx["runtimes"][0].commands] == [
        (
            "set_profile_policy",
            {"profile": "Kids", "daily_budget_min": 60, "bedtime_start": "20:15"},
        ),
        ("set_profile_policy", {"profile_id": 2, "bedtime_end": None}),
        (
            "set_profile_policy",
            {
                "profile": "Kids",
                "daily_budget_min": None,
                "bedtime_start": None,
                "bedtime_end": None,
            },
        ),
        ("grant_extra_time", {"profile": "Kids", "minutes": 15}),
        ("lock_profile", {"profile": "Kids"}),
        ("unlock_profile", {}),
        ("set_profile_restricted", {"profile_id": 2, "restricted": True}),
        (
            "set_profile_allowed_apps",
            {"profile": "Kids", "packages": ["com.a", "com.b"], "mode": "replace"},
        ),
        (
            "set_profile_allowed_apps",
            {"profile": "Kids", "packages": ["com.c"], "mode": "remove"},
        ),
    ]


def test_profile_service_validation() -> None:
    lock = SERVICE_SCHEMAS["lock_profile"]
    with pytest.raises(vol.Invalid):
        lock({})
    with pytest.raises(vol.Invalid):
        lock({"profile": "Kids", "profile_id": 2})
    policy = SERVICE_SCHEMAS["set_profile_policy"]
    with pytest.raises(vol.Invalid):
        policy({"profile": "Kids"})  # nothing to change
    with pytest.raises(vol.Invalid):
        policy({"profile": "Kids", "daily_budget_min": 2000})
    with pytest.raises(vol.Invalid):
        policy({"profile": "Kids", "bedtime_start": "25:00"})
    with pytest.raises(vol.Invalid):
        SERVICE_SCHEMAS["grant_extra_time"]({"profile": "Kids", "minutes": 0})
    with pytest.raises(vol.Invalid):
        SERVICE_SCHEMAS["set_profile_allowed_apps"](
            {"profile": "Kids", "packages": ["a"], "mode": "toggle"}
        )


async def test_profile_service_error_is_readable(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    runtime = ctx["runtimes"][0]

    async def unsupported(command_type, payload=None, *, timeout_ms=None):
        raise HomeAssistantError("unsupported_command")

    runtime.async_send_command = unsupported
    with pytest.raises(HomeAssistantError, match="update the launcher"):
        await hass.services.async_call(
            DOMAIN,
            "lock_profile",
            {"entry_id": ctx["entries"][0].entry_id, "profile": "Kids"},
            blocking=True,
        )


async def test_parental_events_have_dedicated_names(hass: HomeAssistant) -> None:
    names = (
        "launch_blocked",
        "parental_enforcement_changed",
        "screen_time_warning",
        "screen_time_limit_reached",
        "profile_locked",
        "profile_unlocked",
    )
    assert all(name in EVENT_MAP for name in names)

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=LAUNCHER_ID,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 8765, "token": "t"},
    )
    entry.add_to_hass(hass)
    runtime = AndroidTVBridgeRuntime(hass, entry)
    runtime.metadata = {"device_id": LAUNCHER_ID}
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, LAUNCHER_ID)}
    )
    captured = {name: async_capture_events(hass, f"{DOMAIN}.{name}") for name in names}
    generic = async_capture_events(hass, f"{DOMAIN}.event")

    for name in names:
        await runtime._handle_ws_payload(
            {
                "type": "event",
                "payload": {"type": name, "profile_id": 2, "profile": "Kids"},
            }
        )
    await hass.async_block_till_done()

    assert generic == []
    for name in names:
        assert len(captured[name]) == 1, name
        assert captured[name][0].data["profile"] == "Kids"
