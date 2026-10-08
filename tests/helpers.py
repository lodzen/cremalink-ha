"""Shared test harness for entity-level tests (fakes hass/device/entry)."""

import asyncio
from types import SimpleNamespace

from cremalink.ecam.statistics import interpret
from cremalink.parsing.monitor.profile import MonitorProfile
from custom_components.cremalink_ha.const import DOMAIN
from custom_components.cremalink_ha.coordinator import CremalinkCoordinator


class FakeHass:
    """Minimal hass: data store + executor job support."""

    def __init__(self):
        self.data = {DOMAIN: {}}
        self.tasks = []

    def async_create_task(self, coro):
        """Collect scheduled coroutines; tests run them explicitly."""
        self.tasks.append(coro)

    async def async_add_executor_job(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


class FakeEntry:
    """Minimal config entry."""

    def __init__(self, entry_id="entry1", title="Soul", data=None, options=None):
        self.entry_id = entry_id
        self.title = title
        self.data = data or {}
        self.options = options or {}


class FakeMonitorData:
    """Stand-in for the MonitorView returned by ``device.get_monitor()``."""

    def __init__(self, **fields):
        self.parsed = fields.get("parsed", {})
        self.raw_b64 = fields.get("raw_b64")
        for key, value in fields.items():
            setattr(self, key, value)


def make_device(**overrides):
    """A duck-typed Device good enough for the entity layer."""
    device = SimpleNamespace(
        statistics_source=overrides.get("statistics_source", "native"),
        statistics_datapoints=overrides.get("statistics_datapoints"),
        capabilities=overrides.get("capabilities", {}),
        monitor_profile=overrides.get(
            "monitor_profile",
            MonitorProfile.from_dict(
                {
                    "enums": {
                        "status": {0: "in_standby", 1: "waking_up", 7: "ready"},
                        "accessory": {0: "none", 2: "latte_crema_hot"},
                    }
                }
            ),
        ),
        current_profile=overrides.get("current_profile", 0),
        get_monitor=overrides.get("get_monitor", lambda: FakeMonitorData()),
        get_statistics=overrides.get(
            "get_statistics", lambda: interpret([], source="native", complete=True)
        ),
        get_profiles=overrides.get("get_profiles", list),
        select_profile=overrides.get("select_profile", lambda index: True),
        get_settings=overrides.get("get_settings", dict),
        set_setting=overrides.get("set_setting", lambda key, idx: True),
        do=overrides.get("do", lambda name: None),
        configure=overrides.get("configure", lambda: None),
    )
    return device


def make_coordinator(hass, device, monitor=None, **kwargs):
    """Coordinator wired to a fake device, preloaded with monitor data."""
    if monitor is not None:
        device.get_monitor = lambda: monitor
    coordinator = CremalinkCoordinator(hass, device, **kwargs)
    return coordinator


def setup_entities(hass, entry, device, platform_module, monitor=None):
    """Run a platform's async_setup_entry; returns the entity list."""
    coordinator = make_coordinator(hass, device, monitor=monitor)
    coordinator.data = monitor
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "device": device,
        "embedded_server": None,
    }
    entities = []

    async def _setup():
        await platform_module.async_setup_entry(hass, entry, entities.extend)

    asyncio.run(_setup())
    return coordinator, entities
