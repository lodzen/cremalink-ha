"""Bean-system select entity: user-named options + 0xB9 selection (T047).

The entity only exists when the device map advertises
``d25X_beansystem_[1-6]`` in ``catalog_datapoints``; options carry the
user-assigned bean names from ``Device.bean_systems`` (the ``ba f0``
blobs), and the selection issues the session-gated ``0xB9`` frame via
``Device.select_bean_system`` (§13 untested-write path).
"""

import pytest
from cremalink.domain.device import BeanSystem
from homeassistant.exceptions import HomeAssistantError

from custom_components.cremalink_ha import select as select_mod

from tests.helpers import (
    FakeMonitorData,
    make_device,
    make_entry,
    setup_entities,
)

BEAN_DATAPOINTS = ["d251_beansystem_1", "d252_beansystem_2"]


def _beans():
    return [
        BeanSystem(slot=1, name="Crema", selected=True),
        BeanSystem(slot=2, name="Bohnen 2", selected=False),
    ]


async def _setup(hass, **dev):
    entry = make_entry()
    device = make_device(catalog_datapoints=BEAN_DATAPOINTS, **dev)
    monitor = FakeMonitorData(status_name="ready")
    return await setup_entities(hass, entry, device, select_mod, monitor)


def _bean(entities):
    return next(e for e in entities if e.unique_id == "entry1_bean_system")


class TestBeanSelect:
    async def test_options_from_machine_bean_names(self, hass):
        _, entities = await _setup(hass, bean_systems=_beans)
        bean = _bean(entities)
        assert bean.options == ["Crema", "Bohnen 2"]
        # current option follows the machine's selected flag
        assert bean.current_option == "Crema"

    async def test_no_bean_datapoints_no_entity(self, hass):
        entry = make_entry()
        device = make_device(catalog_datapoints=[])  # non-BeanAdapt map
        monitor = FakeMonitorData(status_name="ready")
        _, entities = await setup_entities(hass, entry, device, select_mod, monitor)
        assert all(e.unique_id != "entry1_bean_system" for e in entities)

    async def test_empty_bean_systems_no_options(self, hass):
        # Map advertises the datapoints but the machine has none
        # configured — entity exists (datapoints are a static map fact)
        # with empty options until a fetch lands names.
        _, entities = await _setup(hass, bean_systems=list)
        bean = _bean(entities)
        assert bean.options == []
        assert bean.current_option is None

    async def test_select_option_sends_b9_slot_and_rereads(self, hass):
        sent = []
        state = {"selected": 1}

        def _select(slot):
            sent.append(slot)
            state["selected"] = slot
            return True

        def _systems():
            return [
                BeanSystem(1, "Crema", state["selected"] == 1),
                BeanSystem(2, "Bohnen 2", state["selected"] == 2),
            ]

        _, entities = await _setup(
            hass, bean_systems=_systems, select_bean_system=_select
        )
        bean = _bean(entities)
        await bean.async_select_option("Bohnen 2")
        assert sent == [2]
        # current option re-read from the machine flags, not cached
        assert bean.current_option == "Bohnen 2"

    async def test_nack_raises_homeassistant_error(self, hass):
        _, entities = await _setup(
            hass,
            bean_systems=_beans,
            select_bean_system=lambda slot: False,
        )
        bean = _bean(entities)
        with pytest.raises(HomeAssistantError):
            await bean.async_select_option("Bohnen 2")

    async def test_unknown_option_raises(self, hass):
        _, entities = await _setup(hass, bean_systems=_beans)
        bean = _bean(entities)
        with pytest.raises(ValueError):
            await bean.async_select_option("Nope")

    @pytest.mark.parametrize(
        "status", ["in_standby", "going_to_sleep", "sleeping", "waking_up"]
    )
    async def test_unavailable_in_not_ready_states(self, status, hass):
        # A 0xB9 selection is a session-gated write — gated like the
        # profile select while the machine is asleep.
        device = make_device(catalog_datapoints=BEAN_DATAPOINTS, bean_systems=_beans)
        monitor = FakeMonitorData(status_name=status)
        _, entities = await setup_entities(
            hass, make_entry(), device, select_mod, monitor
        )
        bean = _bean(entities)
        assert bean.available is False
        monitor.status_name = "ready"
        bean._handle_coordinator_update()
        assert bean.available is True
