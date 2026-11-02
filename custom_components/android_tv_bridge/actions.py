"""TV-to-Home Assistant actions: home screen action tiles and popup buttons.

The launcher never holds a Home Assistant token. Instead, the user picks which
scripts and scenes this TV may run in the integration options ("exposed
actions"). The integration sends that list to the launcher (``set_ha_actions``)
so /configure can offer it as a picker. When a tile or popup button is pressed,
the launcher emits an event whose ``action_id`` is the entity id; the
integration runs it only if it is still exposed, and always fires the bus event
so automations and device triggers can react too.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_FRIENDLY_NAME, ATTR_ICON
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import CONF_EXPOSED_ACTIONS, EXPOSED_ACTION_DOMAINS

_LOGGER = logging.getLogger(__name__)

BRIDGE_SET_HA_ACTIONS = "set_ha_actions"
BRIDGE_ACTION_RESULT = "action_result"

ACTION_EVENT_TYPES = frozenset({"action_tile_pressed", "popup_action"})

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_NOT_EXPOSED = "not_exposed"

_MAX_MESSAGE_LENGTH = 80

# entity domain -> service that "runs" it
_RUN_SERVICES: dict[str, str] = {
    "script": "turn_on",
    "scene": "turn_on",
}


def exposed_action_ids(entry: ConfigEntry) -> list[str]:
    """Return the entity ids the user exposed to this TV, in a stable order."""
    raw = entry.options.get(CONF_EXPOSED_ACTIONS) or []
    if isinstance(raw, str):
        raw = [raw]
    seen: set[str] = set()
    ids: list[str] = []
    for value in raw:
        entity_id = str(value).strip()
        if not entity_id or entity_id in seen:
            continue
        if _domain(entity_id) not in EXPOSED_ACTION_DOMAINS:
            continue
        seen.add(entity_id)
        ids.append(entity_id)
    return ids


def action_catalog(hass: HomeAssistant, entity_ids: list[str]) -> list[dict[str, Any]]:
    """Build the ``set_ha_actions`` list: id, display name, domain and icon."""
    registry = er.async_get(hass)
    catalog: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        entry = registry.async_get(entity_id)
        name = (
            (entry.name if entry else None)
            or (state.attributes.get(ATTR_FRIENDLY_NAME) if state else None)
            or (entry.original_name if entry else None)
            or _pretty_object_id(entity_id)
        )
        icon = (entry.icon if entry else None) or (
            state.attributes.get(ATTR_ICON) if state else None
        )
        item: dict[str, Any] = {
            "id": entity_id,
            "name": str(name),
            "domain": _domain(entity_id),
        }
        if icon:
            item["icon"] = str(icon)
        catalog.append(item)
    return catalog


async def async_run_exposed_action(
    hass: HomeAssistant,
    entry: ConfigEntry,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the pressed action if it is exposed and return a result for the TV.

    The result's ``status`` is ``completed``, ``failed`` or ``not_exposed``.
    ``not_exposed`` is not an error: the action may be handled by an
    automation listening for the event.
    """
    action_id = str(payload.get("action_id") or "").strip()
    if not action_id or action_id not in exposed_action_ids(entry):
        return {"status": STATUS_NOT_EXPOSED}

    domain = _domain(action_id)
    service = _RUN_SERVICES.get(domain)
    if service is None or not hass.services.has_service(domain, service):
        return {"status": STATUS_FAILED, "message": "Action is not available"}
    if hass.states.get(action_id) is None:
        return {"status": STATUS_FAILED, "message": "Action no longer exists"}

    try:
        await hass.services.async_call(
            domain,
            service,
            {ATTR_ENTITY_ID: action_id},
            blocking=True,
        )
    except HomeAssistantError as err:
        _LOGGER.warning("SceneTV action %s failed: %s", action_id, err)
        return {"status": STATUS_FAILED, "message": _short(str(err)) or "Failed"}
    except Exception:  # noqa: BLE001 - report any failure back to the TV
        _LOGGER.exception("SceneTV action %s raised", action_id)
        return {"status": STATUS_FAILED, "message": "Failed"}
    return {"status": STATUS_COMPLETED}


def action_result_payload(
    payload: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Build the ``action_result`` command for a tile press, or None.

    Only tiles show a result; popups dismiss themselves when a button is pressed.
    """
    source = payload.get("source") or ("tile" if "tile_id" in payload else None)
    if source != "tile":
        return None
    source_id = payload.get("source_id", payload.get("tile_id"))
    if source_id is None:
        return None
    command: dict[str, Any] = {
        "source": "tile",
        "source_id": str(source_id),
        "action_id": payload.get("action_id"),
        "status": result.get("status"),
    }
    if payload.get("press_id"):
        command["press_id"] = payload["press_id"]
    if result.get("message"):
        command["message"] = result["message"]
    return command


def _domain(entity_id: str) -> str:
    try:
        return split_entity_id(entity_id)[0]
    except ValueError:
        return ""


def _pretty_object_id(entity_id: str) -> str:
    try:
        object_id = split_entity_id(entity_id)[1]
    except ValueError:
        return entity_id
    return object_id.replace("_", " ").strip().capitalize() or entity_id


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text[:_MAX_MESSAGE_LENGTH]
