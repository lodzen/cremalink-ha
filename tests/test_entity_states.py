"""Entity state reliability: enum translations, standby suppression,
read-failure retention (T042 — FR-033/034/035)."""

import asyncio
import json
from pathlib import Path

from custom_components.cremalink_ha import binary_sensor as bs_mod
from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha.coordinator import DEFAULT_FAILURE_THRESHOLD
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.update_coordinator import UpdateFailed

from tests.helpers import (
    FakeEntry,
    FakeHass,
    FakeMonitorData,
    make_device,
    setup_entities,
)

EN_JSON = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "cremalink_ha"
    / "translations"
    / "en.json"
)


def _setup(module, monitor=None, **dev):
    hass = FakeHass()
    entry = FakeEntry()
    device = make_device(**dev)
    return setup_entities(
        hass, entry, device, module, monitor or FakeMonitorData(status_name="ready")
    )


class TestEnumTranslations:
    def test_enum_sensors_declare_translation_key_and_options(self):
        _, entities = _setup(sensor_mod)
        by_key = {e.unique_id: e for e in entities}
        for uid, expected_options in (
            ("entry1_status_name", {"in_standby", "waking_up", "ready"}),
            ("entry1_accessory_name", {"none", "latte_crema_hot"}),
        ):
            entity = by_key[uid]
            assert entity._attr_device_class == SensorDeviceClass.ENUM
            assert entity._attr_translation_key
            assert expected_options.issubset(set(entity._attr_options))

    def test_every_enum_option_has_state_translation(self):
        translations = json.loads(EN_JSON.read_text())
        state_maps = translations["entity"]["sensor"]
        _, entities = _setup(sensor_mod)
        for entity in entities:
            options = getattr(entity, "_attr_options", None)
            if not options:
                continue
            key = entity._attr_translation_key
            states = state_maps[key]["state"]
            for option in options:
                assert option in states, f"{key}.{option} untranslated"

    def test_no_raw_token_surfaces_as_state(self):
        # A translated status label never looks like `in_standby` to the
        # user — the entity only carries the option key + translation.
        _, entities = _setup(sensor_mod)
        translations = json.loads(EN_JSON.read_text())
        for entity in entities:
            key = getattr(entity, "_attr_translation_key", None)
            if not key:
                continue
            for label in translations["entity"]["sensor"][key]["state"].values():
                assert "_" not in label


class TestStandbySuppression:
    def test_latched_alarm_bit_suppressed_in_standby(self):
        # A standby frame carries alarm bit 0 (empty tank latched) — the
        # problem sensor must keep reporting its last live value (OK).
        monitor = FakeMonitorData(status_name="in_standby", is_watertank_empty=True)
        _, entities = _setup(bs_mod, monitor)
        sensor = next(e for e in entities if e.unique_id == "entry1_is_watertank_empty")
        assert sensor.is_on is not True

    def test_live_alarm_still_reported_when_awake(self):
        monitor = FakeMonitorData(status_name="ready", is_watertank_empty=True)
        _, entities = _setup(bs_mod, monitor)
        sensor = next(e for e in entities if e.unique_id == "entry1_is_watertank_empty")
        assert sensor.is_on is True

    def test_accessory_retains_last_live_value_in_standby(self):
        coordinator, entities = _setup(
            sensor_mod,
            FakeMonitorData(status_name="ready", accessory_name="latte_crema_hot"),
        )
        sensor = next(e for e in entities if e.unique_id == "entry1_accessory_name")
        assert sensor.native_value == "latte_crema_hot"
        # Standby frame arrives with accessory flapped to none.
        coordinator.data = FakeMonitorData(
            status_name="in_standby", accessory_name="none"
        )
        assert sensor.native_value == "latte_crema_hot"

    def test_status_tracks_live_frame_even_in_standby(self):
        coordinator, entities = _setup(
            sensor_mod,
            FakeMonitorData(status_name="ready", accessory_name="latte_crema_hot"),
        )
        sensor = next(e for e in entities if e.unique_id == "entry1_status_name")
        coordinator.data = FakeMonitorData(status_name="in_standby")
        assert sensor.native_value == "in_standby"

    def test_busy_not_derived_from_stale_action_byte(self):
        monitor = FakeMonitorData(status_name="in_standby", is_busy=True)
        _, entities = _setup(bs_mod, monitor)
        sensor = next(e for e in entities if e.unique_id == "entry1_is_busy")
        assert sensor.is_on is not True


class TestFailureRetention:
    def _coordinator_with_failures(self, failures):
        coordinator, entities = _setup(sensor_mod)
        coordinator.consecutive_failures = failures
        return coordinator, entities

    def test_state_retained_below_threshold(self):
        _, entities = self._coordinator_with_failures(1)
        sensor = next(e for e in entities if e.unique_id == "entry1_status_name")
        assert sensor.available is True
        assert sensor.native_value == "ready"

    def test_unavailable_at_threshold(self):
        _, entities = self._coordinator_with_failures(DEFAULT_FAILURE_THRESHOLD)
        for entity in entities:
            assert entity.available is False

    def test_failed_refresh_increments_counter_and_keeps_data(self):
        def _fail():
            raise ConnectionError("lan timeout")

        hass = FakeHass()
        device = make_device(get_monitor=_fail)
        # monitor=None — setup must not override the failing get_monitor.
        coordinator, _ = setup_entities(hass, FakeEntry(), device, sensor_mod)
        monitor = FakeMonitorData(status_name="ready")
        coordinator.data = monitor
        coordinator.failure_threshold = DEFAULT_FAILURE_THRESHOLD

        async def _refresh():
            try:
                await coordinator._async_update_data()
            except UpdateFailed:
                pass

        for expected in (1, 2):
            asyncio.run(_refresh())
            assert coordinator.consecutive_failures == expected
            assert coordinator.data is monitor

    def test_successful_refresh_resets_counter(self):
        hass = FakeHass()
        monitor = FakeMonitorData(status_name="ready", parsed={"status": 7})
        device = make_device(get_monitor=lambda: monitor)
        coordinator, _ = setup_entities(hass, FakeEntry(), device, sensor_mod, monitor)
        coordinator.consecutive_failures = 2
        asyncio.run(coordinator._async_update_data())
        assert coordinator.consecutive_failures == 0
