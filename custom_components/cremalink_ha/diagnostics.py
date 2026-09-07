"""Diagnostics support for Cremalink.

Redacts the sensitive fields introduced by cloud-assisted onboarding
(spec FR-013): cloud account email/password, access/refresh tokens, and
the LAN key. Modeled directly on ``delonghi_coffee``'s ``diagnostics.py``.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS: set[str] = {
    "email",
    "password",
    "access_token",
    "refresh_token",
    "lan_key",
    "device_ip",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry, with sensitive fields redacted."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    embedded_server = data.get("embedded_server")

    embedded_server_info = None
    if embedded_server is not None:
        # bound_port/advertised_ip are not secrets -- surfaced for FR-008 debugging.
        embedded_server_info = {
            "state": embedded_server.state,
            "bound_port": embedded_server.bound_port,
            "advertised_ip": embedded_server.advertised_ip,
        }

    return {
        "entry_data": async_redact_data(dict(entry.data), REDACT_KEYS),
        "entry_options": async_redact_data(dict(entry.options), REDACT_KEYS),
        "coordinator_data": async_redact_data(getattr(coordinator, "data", None) or {}, REDACT_KEYS),
        "embedded_server": embedded_server_info,
    }
