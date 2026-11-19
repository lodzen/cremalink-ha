"""Preload/blocked lifecycle: pending reads, fallback, rescoping (T019/US3)."""

from cremalink.domain.device import RecipeParams
from custom_components.cremalink_ha import number as number_mod
from custom_components.cremalink_ha.recipe_session import MAX_DEFAULT_RETRIES

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)


async def _setup(hass, platform, **dev):
    entry = make_entry()
    device = make_device(**dev)
    monitor = FakeMonitorData(status_name="ready")
    coordinator, entities = await setup_entities(hass, entry, device, platform, monitor)
    session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
    return coordinator, entities, session


class TestStandbyAndBackoff:
    async def test_no_load_while_standby(self, hass):
        """A standby machine gets zero recipe reads (no flood)."""
        calls = []
        entry = make_entry()
        device = make_device(recipe_params=lambda bid, **_: calls.append(bid))
        monitor = FakeMonitorData(status_name="in_standby")
        coordinator, entities = await setup_entities(
            hass, entry, device, number_mod, monitor
        )
        session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
        session.select(0x01)
        for _ in range(3):
            await session.async_ensure_params(hass, coordinator)
            await hass.async_block_till_done()
        assert calls == []
        assert session.loading is False

    async def test_failed_attempt_backs_off(self, hass):
        """After a failed load the next attempt waits LOAD_RETRY_INTERVAL."""
        calls = []

        def _boom(bid, **_):
            calls.append(bid)
            raise RuntimeError("transport down")

        entry = make_entry()
        device = make_device(recipe_params=_boom)
        monitor = FakeMonitorData(status_name="ready")
        coordinator, entities = await setup_entities(
            hass, entry, device, number_mod, monitor
        )
        session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        # Immediate retry is suppressed by the backoff.
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert calls == [0x01]
        # Simulated elapsed backoff re-arms a retry.
        session._last_attempt -= 61.0
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert calls == [0x01, 0x01]

    async def test_load_fires_once_awake(self, hass):
        """The deferred load lands on the first awake cycle."""
        params = RecipeParams(
            beverage_id=0x01,
            profile_slot=1,
            values={1: 60},
            bounds={1: (30, 40, 60)},
            source="stored",
        )
        calls = []
        entry = make_entry()
        device = make_device(recipe_params=lambda bid, **_: calls.append(bid) or params)
        monitor = FakeMonitorData(status_name="ready")
        coordinator, entities = await setup_entities(
            hass, entry, device, number_mod, monitor
        )
        session = hass.data["cremalink_ha"][entry.entry_id]["recipe_session"]
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert calls == [0x01]
        assert session.params is params


class TestPendingBlocksControls:
    async def test_loading_blocks_number_entities(self, hass):
        _, entities, session = await _setup(
            hass, number_mod, recipe_params=lambda *a, **k: None
        )
        session.select(0x01)
        await session.async_ensure_params(hass, entities[0].coordinator)
        # load in flight or failed → params None → unavailable
        assert next(iter(entities)).available is False

    async def test_failed_load_leaves_params_none(self, hass):
        def _boom(bid, **_):
            raise RuntimeError("transport down")

        _, entities, session = await _setup(hass, number_mod, recipe_params=_boom)
        session.select(0x01)
        await session.async_ensure_params(hass, entities[0].coordinator)
        await hass.async_block_till_done()
        assert session.loading is False
        assert session.params is None


class TestFallbackSource:
    async def test_default_source_surfaced_in_attributes(self, hass):
        params = RecipeParams(
            beverage_id=0x01,
            profile_slot=1,
            values={1: 40},
            bounds={1: (30, 40, 60), 24: (0, 1, 1)},
            source="default",
        )
        _, entities, session = await _setup(hass, number_mod)
        session.selected_beverage = 0x01
        session.params = params
        num = next(e for e in entities if e.unique_id.endswith("_param_1"))
        assert num.available is True  # fallback allows controls
        assert num.native_value == 40.0  # descriptor default (raw 40 = 40 ml)
        assert num.extra_state_attributes["values_source"] == "default"


class TestProfileRescope:
    async def test_profile_change_clears_and_reloads(self, hass):
        loads = []

        def _params(bid, **_):
            loads.append(bid)
            return RecipeParams(
                beverage_id=bid,
                profile_slot=2,
                values={1: 55},
                bounds={1: (30, 40, 60)},
                source="stored",
            )

        coordinator, entities, session = await _setup(
            hass,
            number_mod,
            recipe_params=_params,
            current_profile=1,
        )
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert session.params is not None
        session.set_override(1, 50)

        # Profile switch on the device → next ensure reloads.
        coordinator.device.current_profile = 2
        await session.async_ensure_params(hass, coordinator)
        assert session.overrides == {}  # dropped with the scope
        await hass.async_block_till_done()
        assert loads == [0x01, 0x01]  # reloaded once for the new profile
        assert session.params.values == {1: 55}

    async def test_ensure_does_not_reload_when_unchanged(self, hass):
        loads = []

        def _params(bid, **_):
            loads.append(bid)
            return RecipeParams(
                beverage_id=bid,
                profile_slot=1,
                values={},
                bounds={},
                source="stored",
            )

        coordinator, entities, session = await _setup(
            hass, number_mod, recipe_params=_params, current_profile=1
        )
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert loads == [0x01]  # one load per (recipe, profile)


class TestDefaultFallbackRetry:
    @staticmethod
    def _params(source):
        return RecipeParams(
            beverage_id=0x01,
            profile_slot=1,
            values={1: 60},
            bounds={1: (30, 40, 60)},
            source=source,
        )

    async def test_default_fallback_is_retried_until_profile_values(self, hass):
        """A fallback read (machine not answering yet) must not stick."""
        results = [self._params("default"), self._params("profile")]
        calls = []

        def _load(bid, **_):
            calls.append(bid)
            return results[len(calls) - 1]

        coordinator, _, session = await _setup(hass, number_mod, recipe_params=_load)
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert session.params.source == "default"
        # Backoff: no retry right away.
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert len(calls) == 1
        # After the backoff the profile values replace the fallback.
        session._last_attempt -= 61.0
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert len(calls) == 2
        assert session.params.source == "profile"
        # And then they stay: no further loads.
        session._last_attempt -= 61.0
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert len(calls) == 2

    async def test_fallback_stays_while_retry_fails(self, hass):
        calls = []

        def _load(bid, **_):
            calls.append(bid)
            if len(calls) == 1:
                return self._params("default")
            raise RuntimeError("transport down")

        coordinator, _, session = await _setup(hass, number_mod, recipe_params=_load)
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        session._last_attempt -= 61.0
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert len(calls) == 2
        assert session.params.source == "default"

    async def test_fallback_retries_stop_after_the_cap(self, hass):
        calls = []

        def _load(bid, **_):
            calls.append(bid)
            return self._params("default")

        coordinator, _, session = await _setup(hass, number_mod, recipe_params=_load)
        session.select(0x01)
        for _ in range(MAX_DEFAULT_RETRIES + 4):
            await session.async_ensure_params(hass, coordinator)
            await hass.async_block_till_done()
            if session._last_attempt is not None:
                session._last_attempt -= 61.0
        # First read plus MAX_DEFAULT_RETRIES retries, then no more.
        assert len(calls) == MAX_DEFAULT_RETRIES + 1
        # A new selection starts over.
        session.select(0x01)
        await session.async_ensure_params(hass, coordinator)
        await hass.async_block_till_done()
        assert len(calls) == MAX_DEFAULT_RETRIES + 2
