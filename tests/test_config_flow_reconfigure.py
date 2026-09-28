"""Tests for the legacy-entry reconfigure flow (spec 002-embedded-local-server, US3).

Covers pre-filled values, the optional advertised_ip override, successful
reconfiguration (data rewrite + reload + repair-issue cleanup), and
cancelling/dismissing (entry stays flagged).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.cremalink_ha import config_flow as cf_mod
from custom_components.cremalink_ha.config_flow import CremalinkConfigFlow
from custom_components.cremalink_ha.const import (
    CONF_ADDON_URL,
    CONF_ADVERTISED_IP,
    CONF_CONNECTION_MODE,
    CONF_CONNECTION_TYPE,
    CONF_DSN,
    CONF_LAN_KEY,
    CONF_DEVICE_IP,
    CONNECTION_LOCAL,
    CONNECTION_MODE_EMBEDDED,
    DEVICE_NAME,
    DOMAIN,
)


def _run(coro):
    return asyncio.run(coro)


class _FakeEntry:
    def __init__(self, data, entry_id="entry1"):
        self.data = data
        self.entry_id = entry_id


def _legacy_entry(entry_id="entry1"):
    return _FakeEntry(
        {
            CONF_CONNECTION_TYPE: CONNECTION_LOCAL,
            DEVICE_NAME: "My Machine",
            CONF_DSN: "DSN1",
            "device_map": "ECAM452",
            CONF_ADDON_URL: "http://localhost:10280",
            CONF_LAN_KEY: "key1",
            CONF_DEVICE_IP: "192.168.1.5",
        },
        entry_id=entry_id,
    )


def _make_flow(entry):
    flow = CremalinkConfigFlow()
    hass = MagicMock()
    hass.config_entries.async_get_entry = lambda entry_id: entry
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    flow.hass = hass
    flow.context = {"entry_id": entry.entry_id}
    return flow, hass


@pytest.fixture(autouse=True)
def _patch_issue_registry(monkeypatch):
    monkeypatch.setattr(cf_mod.ir, "async_delete_issue", MagicMock())
    yield


def test_reconfigure_form_prefills_dsn_and_device_name():
    entry = _legacy_entry()
    flow, _hass = _make_flow(entry)

    result = _run(flow.async_step_reconfigure(None))

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"]["dsn"] == "DSN1"
    assert result["description_placeholders"]["device_name"] == "My Machine"


def test_reconfigure_accepts_optional_advertised_ip_override():
    entry = _legacy_entry()
    flow, hass = _make_flow(entry)

    result = _run(flow.async_step_reconfigure({CONF_ADVERTISED_IP: "10.0.0.5"}))

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert new_data[CONF_ADVERTISED_IP] == "10.0.0.5"


def test_reconfigure_rejects_invalid_advertised_ip():
    entry = _legacy_entry()
    flow, hass = _make_flow(entry)

    result = _run(
        flow.async_step_reconfigure({CONF_ADVERTISED_IP: "192.168.178.999"})
    )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_advertised_ip"
    hass.config_entries.async_update_entry.assert_not_called()


def test_completing_reconfigure_rewrites_entry_and_reloads():
    entry = _legacy_entry()
    flow, hass = _make_flow(entry)

    _run(flow.async_step_reconfigure({}))

    new_data = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert CONF_ADDON_URL not in new_data
    assert new_data[CONF_CONNECTION_MODE] == CONNECTION_MODE_EMBEDDED
    assert new_data[CONF_DSN] == "DSN1"
    assert new_data[CONF_LAN_KEY] == "key1"
    assert new_data[CONF_DEVICE_IP] == "192.168.1.5"
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
    cf_mod.ir.async_delete_issue.assert_called_once_with(hass, DOMAIN, f"reconfigure_{entry.entry_id}")


def test_not_submitting_leaves_entry_untouched():
    """Dismissing/cancelling (never submitting) never rewrites entry data."""
    entry = _legacy_entry()
    flow, hass = _make_flow(entry)

    _run(flow.async_step_reconfigure(None))

    hass.config_entries.async_update_entry.assert_not_called()
    hass.config_entries.async_reload.assert_not_awaited()
    assert CONF_ADDON_URL in entry.data
