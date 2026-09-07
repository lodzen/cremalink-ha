"""Tests for embedded-server lifecycle wiring in __init__.py / coordinator.py.

Covers spec 002-embedded-local-server US1 (new setups run embedded, no
add-on), US2 (lifecycle tied to config entry: start/stop/reload/removal,
per-entry isolation), and the legacy-entry reconfigure-required path (US3).
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import custom_components.cremalink_ha as init_mod
import pytest
from custom_components.cremalink_ha.const import (
    CONF_ADDON_URL,
    CONF_CONNECTION_MODE,
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_IP,
    CONF_DEVICE_MAP,
    CONF_DSN,
    CONF_LAN_KEY,
    CONNECTION_LOCAL,
    CONNECTION_MODE_EMBEDDED,
    DEVICE_NAME,
    DOMAIN,
)
from custom_components.cremalink_ha.coordinator import CremalinkCoordinator


def _run(coro):
    return asyncio.run(coro)


class _FakeEmbeddedServer:
    """Controllable stand-in for cremalink.EmbeddedLocalServer."""

    instances: list["_FakeEmbeddedServer"] = []
    next_port = 10280

    def __init__(
        self, dsn, device_ip, lan_key, device_map_path=None, advertised_ip=None
    ):
        self.dsn = dsn
        self.device_ip = device_ip
        self.lan_key = lan_key
        self.advertised_ip = advertised_ip or "192.168.1.100"
        self.bound_port = _FakeEmbeddedServer.next_port
        _FakeEmbeddedServer.next_port += 1
        self.state = "stopped"
        _FakeEmbeddedServer.instances.append(self)

    async def start(self):
        self.state = "running"

    async def stop(self):
        self.state = "stopped"


class _FakeEntry:
    """Minimal ConfigEntry stand-in that actually runs on_unload callbacks."""

    def __init__(self, data, entry_id="entry1", title=""):
        self.data = data
        self.options = {}
        self.entry_id = entry_id
        self.title = title
        self._unload_callbacks = []

    def async_on_unload(self, callback):
        self._unload_callbacks.append(callback)

    async def fire_unload_callbacks(self):
        for cb in reversed(self._unload_callbacks):
            result = cb()
            if asyncio.iscoroutine(result):
                await result


class _FakeDevice:
    def __init__(self):
        self.configure = MagicMock()

    def get_monitor(self):
        return MagicMock(parsed={"status": 1})


def _make_hass():
    hass = MagicMock()

    async def _executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    hass.async_add_executor_job = _executor
    hass.config.path = lambda *parts: "/".join(parts)
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.data = {}
    return hass


def _local_entry_data(dsn="DSN1"):
    return {
        CONF_CONNECTION_TYPE: CONNECTION_LOCAL,
        DEVICE_NAME: "My Machine",
        CONF_DSN: dsn,
        CONF_DEVICE_MAP: "ECAM452",
        CONF_CONNECTION_MODE: CONNECTION_MODE_EMBEDDED,
        CONF_LAN_KEY: "key",
        CONF_DEVICE_IP: "192.168.1.5",
    }


@pytest.fixture(autouse=True)
def _patch_collaborators(monkeypatch):
    _FakeEmbeddedServer.instances = []
    _FakeEmbeddedServer.next_port = 10280
    monkeypatch.setattr(init_mod, "EmbeddedLocalServer", _FakeEmbeddedServer)
    monkeypatch.setattr(init_mod, "device_map", lambda name: f"/maps/{name}.json")
    monkeypatch.setattr(init_mod, "create_local_device", lambda **kwargs: _FakeDevice())
    yield


class TestEmbeddedModeSetup:
    def test_new_entry_starts_embedded_server_no_addon(self):
        hass = _make_hass()
        entry = _FakeEntry(_local_entry_data())

        ok = _run(init_mod.async_setup_entry(hass, entry))

        assert ok is True
        assert len(_FakeEmbeddedServer.instances) == 1
        server = _FakeEmbeddedServer.instances[0]
        assert server.state == "running"
        assert CONF_ADDON_URL not in entry.data

        stored = hass.data[DOMAIN][entry.entry_id]
        assert stored["embedded_server"] is server
        coordinator = stored["coordinator"]
        _run(coordinator._async_update_data())  # should not raise


class TestLifecycle:
    def test_unload_stops_embedded_server_and_releases_registration(self):
        hass = _make_hass()
        entry = _FakeEntry(_local_entry_data())
        _run(init_mod.async_setup_entry(hass, entry))
        server = _FakeEmbeddedServer.instances[0]

        _run(entry.fire_unload_callbacks())

        assert server.state == "stopped"

    def test_reload_stops_old_server_before_new_one_starts(self):
        hass = _make_hass()
        entry = _FakeEntry(_local_entry_data())
        _run(init_mod.async_setup_entry(hass, entry))
        old_server = _FakeEmbeddedServer.instances[0]

        # Simulate a reload: HA fires unload callbacks, then calls setup again.
        _run(entry.fire_unload_callbacks())
        entry._unload_callbacks = []
        _run(init_mod.async_setup_entry(hass, entry))
        new_server = _FakeEmbeddedServer.instances[-1]

        assert old_server.state == "stopped"
        assert new_server.state == "running"
        assert old_server is not new_server

    def test_two_entries_get_independent_embedded_servers(self):
        hass = _make_hass()
        entry1 = _FakeEntry(_local_entry_data(dsn="DSN1"), entry_id="entry1")
        entry2 = _FakeEntry(_local_entry_data(dsn="DSN2"), entry_id="entry2")

        _run(init_mod.async_setup_entry(hass, entry1))
        _run(init_mod.async_setup_entry(hass, entry2))

        server1 = hass.data[DOMAIN]["entry1"]["embedded_server"]
        server2 = hass.data[DOMAIN]["entry2"]["embedded_server"]
        assert server1 is not server2
        assert server1.bound_port != server2.bound_port
        assert server1.state == server2.state == "running"


class TestLegacyEntryReconfigureRequired:
    def test_legacy_entry_does_not_auto_start_embedded_server(self, monkeypatch):
        created_issues = []
        monkeypatch.setattr(
            init_mod.ir,
            "async_create_issue",
            lambda hass, domain, issue_id, **kwargs: created_issues.append(issue_id),
        )

        hass = _make_hass()
        legacy_data = _local_entry_data()
        legacy_data.pop(CONF_CONNECTION_MODE)
        legacy_data[CONF_ADDON_URL] = "http://localhost:10280"
        entry = _FakeEntry(legacy_data)

        from homeassistant.exceptions import ConfigEntryNotReady

        with pytest.raises(ConfigEntryNotReady):
            _run(init_mod.async_setup_entry(hass, entry))

        assert _FakeEmbeddedServer.instances == []
        assert created_issues == [f"reconfigure_{entry.entry_id}"]


class TestCoordinatorFailureSurfacing:
    def test_failed_embedded_server_state_raises_update_failed(self):
        hass = _make_hass()
        device = _FakeDevice()
        server = _FakeEmbeddedServer("dsn", "ip", "key")
        server.state = "failed"
        coordinator = CremalinkCoordinator(hass, device, embedded_server=server)

        from homeassistant.helpers.update_coordinator import UpdateFailed

        with pytest.raises(UpdateFailed):
            _run(coordinator._async_update_data())


class TestBoundedStop:
    """Covers research.md #7 / tasks.md Phase 9: a stuck stop() must never
    block a reload/unload/removal past the bounded timeout."""

    def test_stuck_stop_does_not_block_unload_past_bounded_timeout(self, monkeypatch):
        monkeypatch.setattr(init_mod, "EMBEDDED_SERVER_STOP_TIMEOUT", 0.1)
        hass = _make_hass()
        entry = _FakeEntry(_local_entry_data())
        _run(init_mod.async_setup_entry(hass, entry))
        server = _FakeEmbeddedServer.instances[0]

        async def _hang_forever():
            await asyncio.sleep(3600)

        server.stop = _hang_forever

        started = time.monotonic()
        _run(entry.fire_unload_callbacks())
        elapsed = time.monotonic() - started

        assert elapsed < 2.0
