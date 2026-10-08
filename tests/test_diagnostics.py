"""Tests for diagnostics.py redaction of cloud-assisted onboarding secrets."""

import asyncio
from unittest.mock import MagicMock

from custom_components.cremalink_ha.const import DOMAIN
from custom_components.cremalink_ha.diagnostics import (
    REDACT_KEYS,
    async_get_config_entry_diagnostics,
)


def _run(coro):
    return asyncio.run(coro)


def test_diagnostics_redacts_sensitive_fields():
    entry = MagicMock()
    entry.data = {
        "email": "user@example.com",
        "password": "hunter2",
        "access_token": "at-secret",
        "refresh_token": "rt-secret",
        "lan_key": "lan-secret",
        "device_ip": "192.168.1.5",
        "dsn": "DSN1",
        "device_map": "ECAM452",
    }
    entry.options = {}
    entry.entry_id = "entry1"

    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.data = {"status": "ok"}
    hass.data = {DOMAIN: {"entry1": {"coordinator": coordinator}}}

    result = _run(async_get_config_entry_diagnostics(hass, entry))

    redacted = result["entry_data"]
    for key in REDACT_KEYS:
        if key in entry.data:
            assert redacted[key] == "**REDACTED**"
    assert redacted["dsn"] == "**REDACTED**"
    assert redacted["device_map"] == "ECAM452"


def test_diagnostics_redacts_embedded_server_ip_and_surfaces_port():
    entry = MagicMock()
    entry.data = {"dsn": "DSN1"}
    entry.options = {}
    entry.entry_id = "entry1"

    embedded_server = MagicMock()
    embedded_server.state = "running"
    embedded_server.bound_port = 10281
    embedded_server.advertised_ip = "192.168.1.50"
    embedded_server.monitor_poll_interval = 12
    embedded_server.nudger_poll_interval = 1
    embedded_server.rekey_interval_seconds = 60
    embedded_server.get_recent_events.return_value = [
        {
            "event": "monitor_datapoint",
            "level": "INFO",
            "ts": 1.0,
            "details": {
                "dsn": "DSN-SECRET",
                "device_ip": "192.168.1.50",
                "command": "secret-command",
                "raw_value_len": 24,
            },
        }
    ]

    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.data = {
        "raw_b64": "clear-monitor-frame",
        "parsed": {"status": 2},
    }
    hass.data = {
        DOMAIN: {
            "entry1": {"coordinator": coordinator, "embedded_server": embedded_server}
        }
    }

    result = _run(async_get_config_entry_diagnostics(hass, entry))

    assert result["embedded_server"] == {
        "state": "running",
        "bound_port": 10281,
        "advertised_ip": "**REDACTED**",
        "monitor_poll_interval": 12,
        "nudger_poll_interval": 1,
        "rekey_interval_seconds": 60,
        "recent_events": [
            {
                "event": "monitor_datapoint",
                "level": "INFO",
                "ts": 1.0,
                "details": {
                    "dsn": "**REDACTED**",
                    "device_ip": "**REDACTED**",
                    "command": "**REDACTED**",
                    "raw_value_len": 24,
                },
            }
        ],
    }
    assert result["coordinator_data"] is None


def test_diagnostics_bounds_recent_embedded_events():
    entry = MagicMock()
    entry.data = {"dsn": "DSN1"}
    entry.options = {}
    entry.entry_id = "entry1"

    embedded_server = MagicMock()
    embedded_server.get_recent_events.return_value = [
        {"event": f"event-{index}", "details": {}} for index in range(60)
    ]
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.data = {}
    hass.data = {
        DOMAIN: {
            "entry1": {"coordinator": coordinator, "embedded_server": embedded_server}
        }
    }

    result = _run(async_get_config_entry_diagnostics(hass, entry))

    events = result["embedded_server"]["recent_events"]
    assert len(events) == 50
    assert events[0]["event"] == "event-10"
    assert events[-1]["event"] == "event-59"
