"""Tests for embedded-server lifecycle wiring in __init__.py / coordinator.py.

Covers spec 002-embedded-local-server US1 (new setups run embedded, no
add-on), US2 (lifecycle tied to config entry: start/stop/reload/removal,
per-entry isolation), and the legacy-entry reconfigure-required path (US3).
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import custom_components.cremalink_ha as init_mod
import pytest
from custom_components.cremalink_ha.const import (
    CONF_ADDON_URL,
    CONF_ADVERTISED_IP,
    CONF_CONNECTION_MODE,
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_IP,
    CONF_DEVICE_MAP,
    CONF_DSN,
    CONF_LAN_KEY,
    CONNECTION_LOCAL,
    CONNECTION_MODE_EMBEDDED,
    DEFAULT_MONITOR_POLL_INTERVAL,
    DEFAULT_NUDGER_POLL_INTERVAL,
    DEVICE_NAME,
    DOMAIN,
)
from custom_components.cremalink_ha.coordinator import CremalinkCoordinator

from tests.helpers import make_entry


class _FakeEmbeddedServer:
    """Controllable stand-in for cremalink.EmbeddedLocalServer."""

    instances: list["_FakeEmbeddedServer"] = []
    next_port = 10280

    def __init__(
        self,
        dsn,
        device_ip,
        lan_key,
        device_map_path=None,
        advertised_ip=None,
        monitor_poll_interval=5.0,
        nudger_poll_interval=1.0,
        event_logger=None,
    ):
        self.dsn = dsn
        self.device_ip = device_ip
        self.lan_key = lan_key
        self.advertised_ip = advertised_ip or "192.168.1.100"
        self.monitor_poll_interval = monitor_poll_interval
        self.nudger_poll_interval = nudger_poll_interval
        self.session_keepalive_seconds = 20.0
        self.event_logger = event_logger
        self.telemetry_events = []
        self.bound_port = _FakeEmbeddedServer.next_port
        _FakeEmbeddedServer.next_port += 1
        self.state = "stopped"
        _FakeEmbeddedServer.instances.append(self)

    async def start(self):
        self.state = "running"

    async def stop(self):
        self.state = "stopped"

    def get_recent_events(self):
        return []

    def log(self, event, details=None, *, level=logging.INFO):
        logging.getLogger("custom_components.cremalink_ha").log(
            level, "%s details=%s", event, details
        )

    def log_telemetry(self, event, details):
        self.telemetry_events.append((event, details))


class _FakeDevice:
    def __init__(self):
        self.configure = MagicMock()

    def get_monitor(self):
        return MagicMock(parsed={"status": 1})


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
def _patch_collaborators(monkeypatch, hass):
    _FakeEmbeddedServer.instances = []
    _FakeEmbeddedServer.next_port = 10280
    monkeypatch.setattr(init_mod, "EmbeddedLocalServer", _FakeEmbeddedServer)
    monkeypatch.setattr(init_mod, "device_map", lambda name: f"/maps/{name}.json")
    monkeypatch.setattr(init_mod, "create_local_device", lambda **kwargs: _FakeDevice())
    # Platform forwarding is exercised by the platform test files; here it
    # would create real entities against partially-seeded state.
    monkeypatch.setattr(
        hass.config_entries, "async_forward_entry_setups", AsyncMock(return_value=True)
    )
    yield


class TestEmbeddedModeSetup:
    async def test_new_entry_starts_embedded_server_no_addon(self, hass):
        entry = make_entry(data=_local_entry_data())
        entry.add_to_hass(hass)

        ok = await init_mod.async_setup_entry(hass, entry)

        assert ok is True
        assert len(_FakeEmbeddedServer.instances) == 1
        server = _FakeEmbeddedServer.instances[0]
        assert server.state == "running"
        assert CONF_ADDON_URL not in entry.data

        stored = hass.data[DOMAIN][entry.entry_id]
        assert stored["embedded_server"] is server
        coordinator = stored["coordinator"]
        assert server.monitor_poll_interval == DEFAULT_MONITOR_POLL_INTERVAL
        assert server.nudger_poll_interval == DEFAULT_NUDGER_POLL_INTERVAL
        assert server.session_keepalive_seconds == 20.0
        assert coordinator.update_interval == timedelta(
            seconds=DEFAULT_MONITOR_POLL_INTERVAL
        )
        await coordinator._async_update_data()  # should not raise

    async def test_legacy_interval_option_is_ignored(self, hass):
        entry = make_entry(
            data=_local_entry_data(),
            options={
                "monitor_poll_interval": 17,
                CONF_ADVERTISED_IP: "192.168.178.96",
            },
        )
        entry.add_to_hass(hass)

        await init_mod.async_setup_entry(hass, entry)

        stored = hass.data[DOMAIN][entry.entry_id]
        assert stored["embedded_server"].monitor_poll_interval == 5
        assert stored["embedded_server"].nudger_poll_interval == 1
        assert stored["embedded_server"].advertised_ip == "192.168.178.96"
        assert stored["coordinator"].update_interval == timedelta(seconds=5)
        assert init_mod._async_options_updated in entry.update_listeners

    async def test_docker_setup_warns_when_advertised_ip_is_auto_detected(
        self, monkeypatch, caplog, hass
    ):
        monkeypatch.setattr(init_mod, "_is_docker_container", lambda: True)
        entry = make_entry(data=_local_entry_data())
        entry.add_to_hass(hass)

        await init_mod.async_setup_entry(hass, entry)

        assert "advertised_ip_auto_detected_in_docker" in caplog.text
        assert "192.168.1.100" in caplog.text

    async def test_options_update_reloads_entry(self, hass, monkeypatch):
        reload_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(hass.config_entries, "async_reload", reload_mock)
        entry = make_entry(data=_local_entry_data())

        await init_mod._async_options_updated(hass, entry)

        reload_mock.assert_awaited_once_with(entry.entry_id)


class TestLifecycle:
    async def test_unload_stops_embedded_server_and_releases_registration(self, hass):
        entry = make_entry(data=_local_entry_data())
        entry.add_to_hass(hass)
        await init_mod.async_setup_entry(hass, entry)
        server = _FakeEmbeddedServer.instances[0]

        await entry._async_process_on_unload(hass)

        assert server.state == "stopped"

    async def test_reload_stops_old_server_before_new_one_starts(self, hass):
        entry = make_entry(data=_local_entry_data())
        entry.add_to_hass(hass)
        await init_mod.async_setup_entry(hass, entry)
        old_server = _FakeEmbeddedServer.instances[0]

        # Simulate a reload: HA fires unload callbacks, then calls setup again.
        await entry._async_process_on_unload(hass)
        await init_mod.async_setup_entry(hass, entry)
        new_server = _FakeEmbeddedServer.instances[-1]

        assert old_server.state == "stopped"
        assert new_server.state == "running"
        assert old_server is not new_server

    async def test_two_entries_get_independent_embedded_servers(self, hass):
        entry1 = make_entry(data=_local_entry_data(dsn="DSN1"), entry_id="entry1")
        entry2 = make_entry(data=_local_entry_data(dsn="DSN2"), entry_id="entry2")
        entry1.add_to_hass(hass)
        entry2.add_to_hass(hass)

        await init_mod.async_setup_entry(hass, entry1)
        await init_mod.async_setup_entry(hass, entry2)

        server1 = hass.data[DOMAIN]["entry1"]["embedded_server"]
        server2 = hass.data[DOMAIN]["entry2"]["embedded_server"]
        assert server1 is not server2
        assert server1.bound_port != server2.bound_port
        assert server1.state == server2.state == "running"


class TestLegacyEntryReconfigureRequired:
    async def test_legacy_entry_does_not_auto_start_embedded_server(
        self, monkeypatch, hass
    ):
        created_issues = []
        ir_mock = MagicMock()
        ir_mock.async_create_issue = (
            lambda hass, domain, issue_id, **kwargs: created_issues.append(issue_id)
        )
        # Patch the binding, not the shared `ir` mock child — pytest>=9.2
        # undoes child-attr patches via delattr, poisoning the mock.
        monkeypatch.setattr(init_mod, "ir", ir_mock)

        legacy_data = _local_entry_data()
        legacy_data.pop(CONF_CONNECTION_MODE)
        legacy_data[CONF_ADDON_URL] = "http://localhost:10280"
        entry = make_entry(data=legacy_data)
        entry.add_to_hass(hass)

        from homeassistant.exceptions import ConfigEntryNotReady

        with pytest.raises(ConfigEntryNotReady):
            await init_mod.async_setup_entry(hass, entry)

        assert _FakeEmbeddedServer.instances == []
        assert created_issues == [f"reconfigure_{entry.entry_id}"]


class TestCoordinatorFailureSurfacing:
    async def test_failed_embedded_server_state_raises_update_failed(self, hass):
        device = _FakeDevice()
        server = _FakeEmbeddedServer("dsn", "ip", "key")
        server.state = "failed"
        coordinator = CremalinkCoordinator(hass, device, embedded_server=server)

        from homeassistant.helpers.update_coordinator import UpdateFailed

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    async def test_cloud_coordinator_keeps_adaptive_cadence(self, hass):
        from custom_components.cremalink_ha.coordinator import (
            SCAN_INTERVAL_FAST,
            SCAN_INTERVAL_SLOW,
        )

        device = _FakeDevice()
        coordinator = CremalinkCoordinator(hass, device)

        await coordinator._async_update_data()
        assert coordinator.update_interval == SCAN_INTERVAL_FAST

        device.get_monitor = lambda: MagicMock(parsed={"status": 0})
        await coordinator._async_update_data()
        assert coordinator.update_interval == SCAN_INTERVAL_SLOW

    async def test_local_coordinator_logs_decoded_monitor_data(self, caplog, hass):
        device = _FakeDevice()
        device.get_monitor = lambda: SimpleNamespace(
            raw_b64="base64-monitor-frame",
            parsed={"status": 2, "progress": 45},
            received_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
            snapshot=SimpleNamespace(warnings=[], errors=[]),
        )
        server = _FakeEmbeddedServer("dsn", "ip", "key")
        caplog.set_level("INFO", logger="custom_components.cremalink_ha.coordinator")
        coordinator = CremalinkCoordinator(
            hass, device, embedded_server=server, monitor_poll_interval=5
        )

        await coordinator._async_update_data()

        assert len(server.telemetry_events) == 1
        event, details = server.telemetry_events[0]
        assert event == "decoded_local_monitor"
        assert details["raw_b64"] == "base64-monitor-frame"
        assert details["parsed"] == {"status": 2, "progress": 45}


class TestBoundedStop:
    """Covers research.md #7 / tasks.md Phase 9: a stuck stop() must never
    block a reload/unload/removal past the bounded timeout."""

    async def test_stuck_stop_does_not_block_unload_past_bounded_timeout(
        self, monkeypatch, hass
    ):
        monkeypatch.setattr(init_mod, "EMBEDDED_SERVER_STOP_TIMEOUT", 0.1)
        entry = make_entry(data=_local_entry_data())
        entry.add_to_hass(hass)
        await init_mod.async_setup_entry(hass, entry)
        server = _FakeEmbeddedServer.instances[0]

        async def _hang_forever():
            await asyncio.sleep(3600)

        server.stop = _hang_forever

        started = time.monotonic()
        await entry._async_process_on_unload(hass)
        elapsed = time.monotonic() - started

        assert elapsed < 2.0
