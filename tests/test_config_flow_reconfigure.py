"""Tests for the legacy-entry reconfigure flow (spec 002-embedded-local-server, US3).

Covers pre-filled values, the optional advertised_ip override, successful
reconfiguration (data rewrite + reload + repair-issue cleanup), and
cancelling/dismissing (entry stays flagged).
"""

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

from tests.helpers import make_entry


def _legacy_entry(entry_id="entry1"):
    return make_entry(
        data={
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


def _make_flow(hass, entry):
    flow = CremalinkConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"entry_id": entry.entry_id}
    entry.add_to_hass(hass)
    return flow


@pytest.fixture(autouse=True)
def _patch_issue_registry(monkeypatch):
    # Replace the `ir` binding itself: patching an attr on the auto-created
    # mock child is undone via delattr by pytest>=9.2, which poisons the mock
    # (deleted names raise AttributeError on every later access).
    monkeypatch.setattr(cf_mod, "ir", MagicMock())
    yield


async def test_reconfigure_form_prefills_dsn_and_device_name(hass):
    entry = _legacy_entry()
    flow = _make_flow(hass, entry)

    result = await flow.async_step_reconfigure(None)

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"]["dsn"] == "DSN1"
    assert result["description_placeholders"]["device_name"] == "My Machine"


async def test_reconfigure_accepts_optional_advertised_ip_override(hass, monkeypatch):
    entry = _legacy_entry()
    flow = _make_flow(hass, entry)
    update = MagicMock()
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update)

    result = await flow.async_step_reconfigure({CONF_ADVERTISED_IP: "10.0.0.5"})

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    new_data = update.call_args.kwargs["data"]
    assert new_data[CONF_ADVERTISED_IP] == "10.0.0.5"


async def test_reconfigure_rejects_invalid_advertised_ip(hass, monkeypatch):
    entry = _legacy_entry()
    flow = _make_flow(hass, entry)
    update = MagicMock()
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update)

    result = await flow.async_step_reconfigure({CONF_ADVERTISED_IP: "192.168.178.999"})

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_advertised_ip"
    update.assert_not_called()


async def test_completing_reconfigure_rewrites_entry_and_reloads(hass, monkeypatch):
    entry = _legacy_entry()
    flow = _make_flow(hass, entry)
    update = MagicMock()
    reload_mock = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_mock)

    await flow.async_step_reconfigure({})

    new_data = update.call_args.kwargs["data"]
    assert CONF_ADDON_URL not in new_data
    assert new_data[CONF_CONNECTION_MODE] == CONNECTION_MODE_EMBEDDED
    assert new_data[CONF_DSN] == "DSN1"
    assert new_data[CONF_LAN_KEY] == "key1"
    assert new_data[CONF_DEVICE_IP] == "192.168.1.5"
    reload_mock.assert_awaited_once_with(entry.entry_id)
    cf_mod.ir.async_delete_issue.assert_called_once_with(
        hass, DOMAIN, f"reconfigure_{entry.entry_id}"
    )


async def test_not_submitting_leaves_entry_untouched(hass, monkeypatch):
    """Dismissing/cancelling (never submitting) never rewrites entry data."""
    entry = _legacy_entry()
    flow = _make_flow(hass, entry)
    update = MagicMock()
    reload_mock = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_mock)

    await flow.async_step_reconfigure(None)

    update.assert_not_called()
    reload_mock.assert_not_awaited()
    assert CONF_ADDON_URL in entry.data
