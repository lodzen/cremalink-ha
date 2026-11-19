"""Statistics sensors: native-source LAN gating + cloud-counter path (T022)."""

import time

from cremalink.ecam.statistics import (
    interpret,
    resolve_cloud_breakdowns,
    resolve_cloud_counters,
)
from custom_components.cremalink_ha import coordinator as coordinator_mod
from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_CLOUD,
    CONNECTION_LOCAL,
)

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


async def _setup(
    hass, *, connection=CONNECTION_LOCAL, statistics_source="native", **dev
):
    entry = make_entry(data={CONF_CONNECTION_TYPE: connection})
    device = make_device(statistics_source=statistics_source, **dev)
    monitor = FakeMonitorData(status_name="ready")
    return await setup_entities(hass, entry, device, sensor_mod, monitor)


def _stat_entities(entities):
    return [
        e
        for e in entities
        if isinstance(
            e,
            (
                sensor_mod.CremalinkStatisticSensor,
                sensor_mod.CremalinkCloudCounterSensor,
            ),
        )
    ]


class TestNativeSource:
    async def test_local_entry_creates_statistics_sensors(self, hass):
        _, entities = await _setup(hass)
        stats = _stat_entities(entities)
        assert len(stats) == len(sensor_mod.STAT_LABELS)
        by_uid = {e.unique_id: e for e in stats}
        assert "entry1_stat_total_beverages" in by_uid
        assert "entry1_stat_descales" in by_uid
        water = by_uid["entry1_stat_water_total"]
        assert water._attr_native_unit_of_measurement == "L"

    async def test_statistics_are_total_increasing(self, hass):
        _, entities = await _setup(hass)
        stats = _stat_entities(entities)
        assert stats
        for entity in stats:
            assert entity.state_class == "total_increasing", entity.unique_id
        # The live monitor readings are not lifetime counters.
        monitor = [e for e in entities if e not in stats]
        assert all(e.state_class is None for e in monitor)

    async def test_cloud_entry_native_map_creates_none(self, hass):
        _, entities = await _setup(hass, connection=CONNECTION_CLOUD)
        assert _stat_entities(entities) == []

    async def test_native_sensor_reads_report_values(self, hass):
        coordinator, entities = await _setup(hass)
        coordinator.statistics = interpret(
            [(43010, 42), (106, 414414)], source="native", complete=True
        )
        by_uid = {e.unique_id: e for e in entities}
        assert by_uid["entry1_stat_total_beverages"].native_value == 42
        assert by_uid["entry1_stat_water_total"].native_value == 207.207

    async def test_native_sensor_unknown_without_report(self, hass):
        _, entities = await _setup(hass)
        by_uid = {e.unique_id: e for e in entities}
        assert by_uid["entry1_stat_descales"].native_value is None

    async def test_counters_stay_available_on_outage(self, hass):
        """Once a report exists, a fetch outage must not flap the counter —
        a lifetime value can only grow while the machine brews."""
        coordinator, entities = await _setup(hass)
        coordinator.statistics = interpret(
            [(43010, 42)], source="native", complete=True
        )
        by_uid = {e.unique_id: e for e in entities}
        sensor = by_uid["entry1_stat_total_beverages"]
        # Monitor data gone + failures past the availability threshold.
        coordinator.data = None
        coordinator.consecutive_failures = coordinator.failure_threshold
        assert sensor.available is True
        assert sensor.native_value == 42
        # Monitor sensors still follow the normal availability rules.
        assert by_uid["entry1_status_name"].available is False

    async def test_counters_unavailable_until_first_report(self, hass):
        coordinator, entities = await _setup(hass)
        coordinator.data = None
        by_uid = {e.unique_id: e for e in entities}
        assert by_uid["entry1_stat_total_beverages"].available is False

    async def test_missing_entry_keeps_last_value(self, hass):
        """A report without the id must not flap the counter back to the
        startup-restored state — the machine drops ids while rewriting
        its statistics table after a brew (observed: 625 ↔ 624 dips)."""
        coordinator, entities = await _setup(hass)
        coordinator.statistics = interpret(
            [(43010, 625)], source="native", complete=True
        )
        sensor = {e.unique_id: e for e in entities}["entry1_stat_total_beverages"]
        assert sensor.native_value == 625
        coordinator.statistics = interpret([(106, 999)], source="native", complete=True)
        assert sensor.native_value == 625

    async def test_cloud_counter_missing_keeps_last_value(self, hass):
        from cremalink.ecam.statistics import StatisticsReport

        coordinator, entities = await _setup(
            hass,
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d701_tot_bev_b"],
        )
        sensor = next(
            e for e in entities if e.unique_id == "entry1_stat_total_beverages"
        )
        report = StatisticsReport(source="cloud_counters", complete=True)
        report.cloud_counters = {"total_beverages": 7}
        coordinator.statistics = report
        assert sensor.native_value == 7
        report2 = StatisticsReport(source="cloud_counters", complete=True)
        report2.cloud_counters = {}
        coordinator.statistics = report2
        assert sensor.native_value == 7


class TestCloudCounters:
    async def test_cloud_entry_creates_counter_sensors(self, hass):
        _, entities = await _setup(
            hass,
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d701_tot_bev_b", "d705_tot_id1_espr"],
        )
        stats = _stat_entities(entities)
        assert stats
        assert all(e.unique_id.startswith("entry1_stat_") for e in stats)
        assert all(e.state_class == "total_increasing" for e in stats)

    async def test_absent_candidates_produce_no_entity(self, hass):
        _, entities = await _setup(
            hass,
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d999_unrelated"],
        )
        assert _stat_entities(entities) == []

    async def test_counter_state_and_breakdown(self, hass):
        props = {"d701_tot_bev_b": '{"1": 3, "2": 4}'}
        coordinator, entities = await _setup(
            hass,
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d701_tot_bev_b"],
        )
        stats = _stat_entities(entities)
        sensor = next(e for e in stats if e.unique_id == "entry1_stat_total_beverages")
        # Feed a cloud_counters report straight into the coordinator.
        from cremalink.ecam.statistics import StatisticsReport

        report = StatisticsReport(source="cloud_counters", complete=True)
        report.cloud_counters = resolve_cloud_counters(props)
        report.breakdowns = resolve_cloud_breakdowns(props)
        sensor.coordinator.statistics = report
        assert sensor.native_value == 7
        assert sensor.extra_state_attributes == {"breakdown": {"1": 3, "2": 4}}

    async def test_unparseable_counter_value_unknown(self, hass):
        props = {"d701_tot_bev_b": "not-a-number"}
        coordinator, entities = await _setup(
            hass,
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d701_tot_bev_b"],
        )
        sensor = next(
            e for e in entities if e.unique_id == "entry1_stat_total_beverages"
        )
        from cremalink.ecam.statistics import StatisticsReport

        report = StatisticsReport(source="cloud_counters", complete=True)
        report.cloud_counters = resolve_cloud_counters(props)
        sensor.coordinator.statistics = report
        assert sensor.native_value is None


class TestCoordinatorSlowLane:
    async def test_statistics_fetched_on_coordinator_refresh(self, hass):
        calls = []
        report = interpret([(43010, 5)], source="native", complete=True)
        device = make_device(
            get_statistics=lambda: calls.append(1) or report,
        )
        monitor = FakeMonitorData(status_name="ready", parsed={"status": 7})
        coordinator, _ = await setup_entities(
            hass, make_entry(), device, sensor_mod, monitor
        )
        await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert calls == [1]
        assert coordinator.statistics is report
        assert coordinator.statistics_supported is True

    async def test_not_implemented_marks_unsupported_once(self, hass):
        def _raise():
            raise NotImplementedError("no mailbox")

        calls = []

        def _count():
            calls.append(1)
            return _raise()

        device = make_device(get_statistics=_count)
        monitor = FakeMonitorData(status_name="ready", parsed={"status": 7})
        coordinator, _ = await setup_entities(
            hass, make_entry(), device, sensor_mod, monitor
        )
        coordinator._statistics_fetched_at = -(10**9)  # force "due"
        await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert coordinator.statistics_supported is False
        coordinator._statistics_fetched_at = -(10**9)
        await coordinator._async_update_data()
        await hass.async_block_till_done()
        # No retry storm — unsupported transports are probed once.
        assert calls == [1]

    async def test_ready_transition_schedules_a_statistics_fetch(self, hass):
        """Brew end (status → ready) refreshes statistics after the settle
        delay instead of waiting out the 5-minute lane."""
        calls = []
        report = interpret([(43010, 1)], source="native", complete=True)
        device = make_device(
            get_statistics=lambda: calls.append(1) or report,
        )
        busy = FakeMonitorData(status_name="preparing_milk", parsed={"status": 10})
        ready = FakeMonitorData(status_name="ready", parsed={"status": 7})
        coordinator, _ = await setup_entities(
            hass, make_entry(), device, sensor_mod, busy
        )
        await coordinator._async_update_data()  # status: preparing_milk
        await hass.async_block_till_done()
        assert coordinator._statistics_due_at is None
        device.get_monitor = lambda: ready
        await coordinator._async_update_data()  # transition → ready
        await hass.async_block_till_done()
        assert coordinator._statistics_due_at is not None
        # Interval would skip (just fetched), but the due fires anyway.
        coordinator._statistics_due_at = 0
        calls.clear()
        await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert calls == [1]
        # Staying at ready does not retrigger.
        assert coordinator._statistics_due_at is None
        calls.clear()
        coordinator._statistics_fetched_at = (
            time.monotonic() - coordinator_mod.STATISTICS_INTERVAL.total_seconds() - 1
        )  # past the lane cadence
        await coordinator._async_update_data()
        await hass.async_block_till_done()
        assert calls == [1]  # normal cadence only
        assert coordinator._statistics_due_at is None
