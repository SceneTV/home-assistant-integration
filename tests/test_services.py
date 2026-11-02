"""Tests for service targeting and new launcher command services."""

from __future__ import annotations

import pytest
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.android_tv_bridge.const import DOMAIN
from custom_components.android_tv_bridge.services import (
    SERVICE_SCHEMAS,
    async_register_services,
)

from .conftest import FakeRuntime


async def _setup(hass: HomeAssistant, *, fail_second: bool = False) -> dict:
    """Register two fake launchers with HA devices and services."""
    area = ar.async_get(hass).async_create("Living Room")
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    out: dict = {"area": area, "runtimes": [], "devices": [], "entries": []}
    hass.data.setdefault(DOMAIN, {})
    for index in range(2):
        entry = MockConfigEntry(domain=DOMAIN, unique_id=f"launcher-{index}")
        entry.add_to_hass(hass)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"launcher-{index}")},
            name=f"TV {index}",
        )
        entity_registry.async_get_or_create(
            "media_player",
            DOMAIN,
            f"launcher-{index}_media_player",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"tv_{index}",
        )
        runtime = FakeRuntime(f"TV {index}", fail=fail_second and index == 1)
        hass.data[DOMAIN][entry.entry_id] = runtime
        out["runtimes"].append(runtime)
        out["devices"].append(device)
        out["entries"].append(entry)
    device_registry.async_update_device(out["devices"][0].id, area_id=area.id)
    async_register_services(hass)
    return out


async def test_legacy_device_id_string_still_works(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "dismiss_popup",
        {"device_id": ctx["devices"][1].id},
        blocking=True,
    )
    assert ctx["runtimes"][0].commands == []
    assert ctx["runtimes"][1].commands == [("dismiss_popup", {}, None)]


async def test_entry_id_still_works(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "refresh_apps",
        {"entry_id": ctx["entries"][0].entry_id},
        blocking=True,
    )
    assert ctx["runtimes"][0].commands == [("refresh_apps", {}, None)]


async def test_area_target(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "show_popup",
        {"text": "Dinner"},
        target={"area_id": ctx["area"].id},
        blocking=True,
    )
    [(command, payload, timeout)] = ctx["runtimes"][0].commands
    assert (command, payload["text"], timeout) == ("show_popup", "Dinner", None)
    assert payload["popup_id"]  # always generated, see test_popup_actions.py
    assert ctx["runtimes"][1].commands == []


async def test_entity_target_and_fan_out(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "queue_pause",
        {},
        target={"entity_id": ["media_player.tv_0", "media_player.tv_1"]},
        blocking=True,
    )
    assert ctx["runtimes"][0].commands == [("queue_pause", {}, None)]
    assert ctx["runtimes"][1].commands == [("queue_pause", {}, None)]


async def test_partial_failure_raises_after_sending_to_all(hass: HomeAssistant) -> None:
    ctx = await _setup(hass, fail_second=True)
    with pytest.raises(HomeAssistantError, match="1 of 2"):
        await hass.services.async_call(
            DOMAIN,
            "queue_next",
            {},
            target={"device_id": [d.id for d in ctx["devices"]]},
            blocking=True,
        )
    assert ctx["runtimes"][0].commands == [("queue_next", {}, None)]


async def test_no_target_with_two_launchers_raises(hass: HomeAssistant) -> None:
    await _setup(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "queue_clear", {}, blocking=True)


async def test_target_without_launcher_raises(hass: HomeAssistant) -> None:
    await _setup(hass)
    empty_area = ar.async_get(hass).async_create("Garage")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "queue_clear", {}, target={"area_id": empty_area.id}, blocking=True
        )


async def test_show_web_popup_payload(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "show_web_popup",
        {
            "entry_id": ctx["entries"][0].entry_id,
            "html": "<b>hi</b>",
            "title": "T",
            "position": "top-right",
            "duration_ms": 8000,
            "width_dp": 400,
            "interactive": True,
            "timeout_ms": 5000,
        },
        blocking=True,
    )
    assert ctx["runtimes"][0].commands == [
        (
            "show_web_popup",
            {
                "title": "T",
                "html": "<b>hi</b>",
                "position": "top-right",
                "duration_ms": 8000,
                "width_dp": 400,
                "interactive": True,
            },
            5000,
        )
    ]


def test_show_web_popup_requires_exactly_one_source() -> None:
    schema = SERVICE_SCHEMAS["show_web_popup"]
    with pytest.raises(vol.Invalid):
        schema({"title": "x"})
    with pytest.raises(vol.Invalid):
        schema({"html": "<b>x</b>", "url": "https://example.com"})
    with pytest.raises(vol.Invalid):
        schema({"html": "x", "width_dp": 50})
    assert schema({"url": "https://example.com"})["url"] == "https://example.com"


async def test_queue_services_payloads(hass: HomeAssistant) -> None:
    ctx = await _setup(hass)
    entry_id = ctx["entries"][0].entry_id
    calls = [
        ("queue_add", {"uri": "https://youtu.be/x", "title": "X", "position": "next"}),
        (
            "queue_add",
            {"items": [{"uri": "https://a"}, {"uri": "https://b", "package": "com.b"}]},
        ),
        ("queue_remove", {"item_id": "qi-1"}),
        ("queue_move", {"item_id": "qi-1", "to_index": 2}),
        ("queue_clear", {}),
        ("queue_play", {}),
        ("queue_play", {"item_id": "qi-2"}),
        ("queue_next", {}),
        ("queue_pause", {}),
    ]
    for service, data in calls:
        await hass.services.async_call(
            DOMAIN, service, {"entry_id": entry_id, **data}, blocking=True
        )
    assert [c[:2] for c in ctx["runtimes"][0].commands] == [
        ("queue_add", {"items": [{"uri": "https://youtu.be/x", "title": "X"}], "position": "next"}),
        ("queue_add", {"items": [{"uri": "https://a"}, {"uri": "https://b", "package": "com.b"}]}),
        ("queue_remove", {"item_id": "qi-1"}),
        ("queue_move", {"item_id": "qi-1", "to_index": 2}),
        ("queue_clear", {}),
        ("queue_play", {}),
        ("queue_play", {"item_id": "qi-2"}),
        ("queue_next", {}),
        ("queue_pause", {}),
    ]


def test_queue_add_validation() -> None:
    schema = SERVICE_SCHEMAS["queue_add"]
    with pytest.raises(vol.Invalid):
        schema({})
    with pytest.raises(vol.Invalid):
        schema({"uri": "https://a", "items": [{"uri": "https://b"}]})
    with pytest.raises(vol.Invalid):
        schema({"items": [{"title": "missing uri"}]})
    with pytest.raises(vol.Invalid):
        schema({"uri": "https://a", "position": "front"})
