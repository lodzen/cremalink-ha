"""Cloud responsiveness and per-model entities (Eletta Explore over the cloud)."""

import threading
import time

from custom_components.cremalink_ha import binary_sensor as binary_sensor_mod
from custom_components.cremalink_ha import switch as switch_mod

from tests.helpers import (
    FakeMonitorData,
    make_coordinator,
    make_device,
    make_entry,
    setup_entities,
)


def _standby():
    return FakeMonitorData(status_name="in_standby", parsed={"status": 0})


class TestMonitorBitPolicy:
    async def test_excluded_bits_are_not_created(self, hass):
        device = make_device(
            monitor_bits={
                "exclude": ["choco_tank_present", "beans_empty_hopper_2"],
                "disabled_by_default": ["motor_up"],
            }
        )
        _, entities = await setup_entities(
            hass, make_entry(), device, binary_sensor_mod, monitor=_standby()
        )
        ids = {e.unique_id for e in entities}
        assert "entry1_switch_choco_tank_present" not in ids
        assert "entry1_alarm_beans_empty_hopper_2" not in ids
        assert "entry1_switch_milk_carafe_present" in ids

    async def test_unverified_bits_are_registered_disabled(self, hass):
        device = make_device(monitor_bits={"disabled_by_default": ["motor_up"]})
        _, entities = await setup_entities(
            hass, make_entry(), device, binary_sensor_mod, monitor=_standby()
        )
        by_id = {e.unique_id: e for e in entities}
        assert by_id["entry1_switch_motor_up"].entity_registry_enabled_default is False
        assert (
            by_id["entry1_switch_milk_carafe_present"].entity_registry_enabled_default
            is True
        )

    async def test_maps_without_policy_keep_every_bit(self, hass):
        _, entities = await setup_entities(
            hass, make_entry(), make_device(), binary_sensor_mod, monitor=_standby()
        )
        assert "entry1_switch_choco_tank_present" in {e.unique_id for e in entities}


class TestPowerSwitchPendingState:
    async def _switch(self, hass):
        sent = []
        device = make_device(do=sent.append)
        _, entities = await setup_entities(
            hass, make_entry(), device, switch_mod, monitor=_standby()
        )
        power = next(e for e in entities if e.unique_id == "entry1_power")
        return power, sent

    async def test_turn_on_shows_on_until_the_machine_reports(self, hass):
        power, sent = await self._switch(hass)
        assert power.is_on is False
        await power.async_turn_on()
        assert sent == ["wakeup"]
        # The monitor still says standby — the switch must not snap back.
        assert power.is_on is True

    async def test_pending_state_expires(self, hass, monkeypatch):
        power, _ = await self._switch(hass)
        await power.async_turn_on()
        later = time.monotonic() + switch_mod.POWER_PENDING_SECONDS + 1
        monkeypatch.setattr(switch_mod.time, "monotonic", lambda: later)
        assert power.is_on is False

    async def test_command_errors_surface_as_ha_errors(self, hass):
        from homeassistant.exceptions import HomeAssistantError

        def fail(_name):
            raise ConnectionError("Could not set app_id")

        device = make_device(do=fail)
        _, entities = await setup_entities(
            hass, make_entry(), device, switch_mod, monitor=_standby()
        )
        power = next(e for e in entities if e.unique_id == "entry1_power")
        try:
            await power.async_turn_on()
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("expected HomeAssistantError")
        assert power.is_on is False


class TestSlowLanesDoNotBlockTheMonitor:
    async def test_monitor_returns_before_slow_lanes_finish(self, hass):
        release = threading.Event()

        def slow_profile_read():
            release.wait(5)

        device = make_device(refresh_current_profile=slow_profile_read)
        monitor = FakeMonitorData(status_name="ready", parsed={"status": 7})
        coordinator = make_coordinator(hass, device, monitor=monitor)

        started = time.monotonic()
        data = await coordinator._async_update_data()
        assert data is monitor
        assert time.monotonic() - started < 1.0
        assert coordinator._slow_lanes_task is not None
        assert not coordinator._slow_lanes_task.done()

        release.set()
        await coordinator._slow_lanes_task
        await hass.async_block_till_done()
