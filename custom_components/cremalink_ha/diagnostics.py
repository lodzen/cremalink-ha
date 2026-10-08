"""Diagnostics support for Cremalink.

Redacts the sensitive fields introduced by cloud-assisted onboarding
(spec FR-013): cloud account email/password, access/refresh tokens, and
the LAN key. Modeled directly on ``delonghi_coffee``'s ``diagnostics.py``.
"""

from __future__ import annotations

from base64 import b64decode
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS: set[str] = {
    "app_crypto_key",
    "app_iv_seed",
    "email",
    "password",
    "access_token",
    "refresh_token",
    "lan_key",
    "device_ip",
    "advertised_ip",
    "dev_crypto_key",
    "dev_iv_seed",
    "dsn",
    "command",
    "cipher",
    "decoded_prefix",
    "enc",
    "random_1",
    "random_2",
    "sign",
    "time_1",
    "time_2",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "device_key",
    "encryption_key",
    "private_key",
    "secret",
    "session_key",
    "session_token",
    "token",
}
MAX_DIAGNOSTIC_EVENTS = 50

#: Blob families carrying user-entered names (profile names ``a4f0``,
#: recipe names ``aaf0``, bean-system ``baf0``). Their contents are
#: elided from diagnostics; the frame header + slot indices stay.
USER_NAME_BLOB_FAMILIES = {b"\xa4\xf0", b"\xaa\xf0", b"\xba\xf0"}


def _redact_blob_value(value: Any) -> Any:
    """Elide user-name blob contents in a single value.

    A base64 string that decodes to a ``0xD0`` frame in a name-bearing
    family is replaced by ``<family>/<slots>/**REDACTED**`` — the frame
    header and profile/recipe slot indices remain for debugging.
    """
    if not isinstance(value, str):
        return value
    try:
        raw = b64decode("".join(value.split()))
    except (ValueError, TypeError):
        return value
    if len(raw) < 6 or raw[0] != 0xD0 or raw[2:4] not in USER_NAME_BLOB_FAMILIES:
        return value
    family = raw[2:4].hex()
    slots = raw[4:6].hex()
    return f"{family}:{slots}:**REDACTED**"


def _redact_blobs(node: Any, depth: int = 0) -> Any:
    """Recursively redact user-name blobs in a diagnostics structure."""
    if depth > 6:
        return node
    if isinstance(node, dict):
        return {k: _redact_blobs(v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_redact_blobs(v, depth + 1) for v in node]
    return _redact_blob_value(node)


def _redact_event(event: dict[str, Any]) -> dict[str, Any]:
    """Redact event fields and detail keys before diagnostics export."""
    redacted = async_redact_data(dict(event), REDACT_KEYS)
    details = event.get("details")
    if isinstance(details, dict):
        redacted["details"] = async_redact_data(dict(details), REDACT_KEYS)
    return _redact_blobs(redacted)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with sensitive fields redacted."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    embedded_server = data.get("embedded_server")
    coordinator_data = getattr(coordinator, "data", None) or {}
    if embedded_server is not None:
        coordinator_data = None

    embedded_server_info = None
    if embedded_server is not None:
        embedded_server_info = {
            "state": embedded_server.state,
            "bound_port": embedded_server.bound_port,
            "advertised_ip": "**REDACTED**" if embedded_server.advertised_ip else None,
            "monitor_poll_interval": embedded_server.monitor_poll_interval,
            "nudger_poll_interval": embedded_server.nudger_poll_interval,
            "rekey_interval_seconds": embedded_server.rekey_interval_seconds,
            "recent_events": [
                _redact_event(event)
                for event in embedded_server.get_recent_events()[
                    -MAX_DIAGNOSTIC_EVENTS:
                ]
            ],
        }

    return {
        "entry_data": async_redact_data(dict(entry.data), REDACT_KEYS),
        "entry_options": async_redact_data(dict(entry.options), REDACT_KEYS),
        "coordinator_data": async_redact_data(coordinator_data, REDACT_KEYS),
        "embedded_server": embedded_server_info,
    }
