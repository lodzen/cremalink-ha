"""Shared test harness for entity-level tests on real Home Assistant."""

from types import SimpleNamespace

from pytest_homeassistant.common import MockConfigEntry, MockEntityPlatform

from cremalink.ecam.statistics import interpret
from cremalink.parsing.monitor.profile import MonitorProfile
from custom_components.cremalink_ha.const import DOMAIN
from custom_components.cremalink_ha.coordinator import CremalinkCoordinator


class FakeMonitorData:
    """Stand-in for the MonitorView returned by ``device.get_monitor()``."""

    def __init__(self, **fields):
        self.parsed = fields.get("parsed", {})
        self.raw_b64 = fields.get("raw_b64")
        # Availability attributes the entity layer reads unconditionally.
        self.is_busy = fields.get("is_busy", False)
        for key, value in fields.items():
            setattr(self, key, value)


def make_entry(**overrides) -> MockConfigEntry:
    """A Cremalink config entry carrying the given data/options."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=overrides.get("entry_id", "entry1"),
        title=overrides.get("title", "Soul"),
        data=overrides.get("data", {}),
        options=overrides.get("options", {}),
        unique_id=overrides.get("unique_id"),
    )


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
        refresh_current_profile=overrides.get("refresh_current_profile", lambda: None),
        get_monitor=overrides.get("get_monitor", lambda: FakeMonitorData()),
        get_statistics=overrides.get(
            "get_statistics", lambda: interpret([], source="native", complete=True)
        ),
        get_profiles=overrides.get("get_profiles", list),
        select_profile=overrides.get("select_profile", lambda index: True),
        get_settings=overrides.get("get_settings", lambda **_: {}),
        set_setting=overrides.get("set_setting", lambda key, idx: True),
        get_setting_bits=overrides.get("get_setting_bits", lambda *, refresh=True: {}),
        set_setting_bit=overrides.get("set_setting_bit", lambda key, on: True),
        do=overrides.get("do", lambda name: None),
        configure=overrides.get("configure", lambda: None),
    )
    return device


def make_coordinator(hass, device, monitor=None, **kwargs):
    """Coordinator wired to a fake device, preloaded with monitor data."""
    if monitor is not None:
        device.get_monitor = lambda: monitor
    coordinator = CremalinkCoordinator(hass, device, **kwargs)
    # Execute request_refresh() as an immediate task — the default 10 s
    # debounce timer would linger past test teardown.
    coordinator._debounced_refresh.immediate = True
    coordinator._debounced_refresh.cooldown = 0
    # Tests drive refresh cycles explicitly via `_async_update_data()` —
    # a live interval would fire background refreshes mid-assertion.
    coordinator.update_interval = None
    # Tests model a running coordinator: skip the monitor-only first
    # cycle so single `_async_update_data()` calls exercise steady state.
    coordinator._first_update_done = True
    return coordinator


async def setup_entities(hass, entry, device, platform_module, monitor=None):
    """Run a platform's async_setup_entry and attach entities for real.

    Entities are added through a MockEntityPlatform so `entity.hass`,
    `entity_id` and `async_write_ha_state` work — coordinator-update
    handlers and state writes behave exactly as under a live entry.
    """
    coordinator = make_coordinator(hass, device, monitor=monitor)
    coordinator.data = monitor
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "device": device,
        "embedded_server": None,
    }
    entities = []
    await platform_module.async_setup_entry(hass, entry, entities.extend)
    platform = MockEntityPlatform(
        hass,
        domain=platform_module.__name__.rsplit(".", 1)[-1],
        platform_name=DOMAIN,
    )
    await platform.async_add_entities(entities)
    # Platform priming is backgrounded (§14.12); let scheduled tasks land.
    await hass.async_block_till_done()
    return coordinator, entities
