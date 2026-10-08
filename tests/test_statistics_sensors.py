"""Statistics sensors: native-source LAN gating + cloud-counter path (T022)."""

import asyncio

from cremalink.ecam.statistics import (
    interpret,
    resolve_cloud_breakdowns,
    resolve_cloud_counters,
)
from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_CLOUD,
    CONNECTION_LOCAL,
)

from tests.helpers import (
    FakeEntry,
    FakeHass,
    FakeMonitorData,
    make_device,
    setup_entities,
)


def _setup(*, connection=CONNECTION_LOCAL, statistics_source="native", **dev):
    hass = FakeHass()
    entry = FakeEntry(data={CONF_CONNECTION_TYPE: connection})
    device = make_device(statistics_source=statistics_source, **dev)
    monitor = FakeMonitorData(status_name="ready")
    return setup_entities(hass, entry, device, sensor_mod, monitor)


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
    def test_local_entry_creates_statistics_sensors(self):
        _, entities = _setup()
        stats = _stat_entities(entities)
        assert len(stats) == len(sensor_mod.STAT_LABELS)
        by_uid = {e.unique_id: e for e in stats}
        assert "entry1_stat_total_beverages" in by_uid
        assert "entry1_stat_descales" in by_uid
        water = by_uid["entry1_stat_water_total"]
        assert water._attr_native_unit_of_measurement == "L"

    def test_cloud_entry_native_map_creates_none(self):
        _, entities = _setup(connection=CONNECTION_CLOUD)
        assert _stat_entities(entities) == []

    def test_native_sensor_reads_report_values(self):
        coordinator, entities = _setup()
        coordinator.statistics = interpret(
            [(43010, 42), (106, 414414)], source="native", complete=True
        )
        by_uid = {e.unique_id: e for e in entities}
        assert by_uid["entry1_stat_total_beverages"].native_value == 42
        assert by_uid["entry1_stat_water_total"].native_value == 207.207

    def test_native_sensor_unknown_without_report(self):
        _, entities = _setup()
        by_uid = {e.unique_id: e for e in entities}
        assert by_uid["entry1_stat_descales"].native_value is None


class TestCloudCounters:
    def test_cloud_entry_creates_counter_sensors(self):
        _, entities = _setup(
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d701_tot_bev_b", "d705_tot_id1_espr"],
        )
        stats = _stat_entities(entities)
        assert stats
        assert all(e.unique_id.startswith("entry1_stat_") for e in stats)

    def test_absent_candidates_produce_no_entity(self):
        _, entities = _setup(
            connection=CONNECTION_CLOUD,
            statistics_source="cloud_counters",
            statistics_datapoints=["d999_unrelated"],
        )
        assert _stat_entities(entities) == []

    def test_counter_state_and_breakdown(self):
        props = {"d701_tot_bev_b": '{"1": 3, "2": 4}'}
        _, entities = _setup(
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

    def test_unparseable_counter_value_unknown(self):
        props = {"d701_tot_bev_b": "not-a-number"}
        _, entities = _setup(
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
    def test_statistics_fetched_on_coordinator_refresh(self):
        calls = []
        report = interpret([(43010, 5)], source="native", complete=True)
        hass = FakeHass()
        device = make_device(
            get_statistics=lambda: calls.append(1) or report,
        )
        monitor = FakeMonitorData(status_name="ready", parsed={"status": 7})
        coordinator, _ = setup_entities(hass, FakeEntry(), device, sensor_mod, monitor)

        async def _refresh():
            await coordinator._async_update_data()

        asyncio.run(_refresh())
        assert calls == [1]
        assert coordinator.statistics is report
        assert coordinator.statistics_supported is True

    def test_not_implemented_marks_unsupported_once(self):
        def _raise():
            raise NotImplementedError("no mailbox")

        calls = []

        def _count():
            calls.append(1)
            return _raise()

        hass = FakeHass()
        device = make_device(get_statistics=_count)
        monitor = FakeMonitorData(status_name="ready", parsed={"status": 7})
        coordinator, _ = setup_entities(hass, FakeEntry(), device, sensor_mod, monitor)
        coordinator._statistics_fetched_at = -(10**9)  # force "due"

        async def _refresh():
            await coordinator._async_update_data()

        asyncio.run(_refresh())
        assert coordinator.statistics_supported is False
        coordinator._statistics_fetched_at = -(10**9)
        asyncio.run(_refresh())
        # No retry storm — unsupported transports are probed once.
        assert calls == [1]
