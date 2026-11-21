"""Cloud catalogue seed: one request, LAN lazy reads stay the backup.

Follows research.md R11 (the app's single ``properties.json`` store sync)
and protocol.md §14.12 (every machine GET costs a lane slot).
"""

from custom_components.cremalink_ha import _async_preload_catalog
from custom_components.cremalink_ha import select as select_mod
from custom_components.cremalink_ha.const import (
    CONF_TOKEN_FILE,
    DOMAIN,
    catalog_ready_signal,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from tests.helpers import FakeMonitorData, make_device, make_entry, setup_entities


class _Client:
    """Stands in for cremalink.Client — records construction and fetches."""

    instances: list = []
    props = {"d001_rec_espresso": "AAA="}
    error: Exception | None = None

    def __init__(self, token_file, logger=None):
        if _Client.error:
            raise _Client.error
        self.token_file = token_file
        _Client.instances.append(self)
        self.fetched = []

    def fetch_properties(self, dsn):
        self.fetched.append(dsn)
        return _Client.props


def _device(seeded=1):
    calls = []
    device = make_device()
    device.seed_catalog_from_properties = lambda props: calls.append(props) or seeded
    return device, calls


async def _run(hass, entry, device):
    signals = []
    async_dispatcher_connect(
        hass, catalog_ready_signal(entry.entry_id), lambda: signals.append(1)
    )
    await _async_preload_catalog(hass, entry, device, "DSN1")
    await hass.async_block_till_done()
    return signals


class TestPreload:
    async def test_without_token_nothing_is_requested(self, hass, monkeypatch):
        monkeypatch.setattr("custom_components.cremalink_ha.Client", _Client)
        _Client.instances, _Client.error = [], None
        device, calls = _device()
        signals = await _run(hass, make_entry(data={}), device)
        assert _Client.instances == [] and calls == [] and signals == []

    async def test_token_seeds_catalogue_with_one_fetch_and_signals(
        self, hass, monkeypatch
    ):
        monkeypatch.setattr("custom_components.cremalink_ha.Client", _Client)
        _Client.instances, _Client.error = [], None
        device, calls = _device()
        entry = make_entry(data={CONF_TOKEN_FILE: "/t/DSN1.json"})
        signals = await _run(hass, entry, device)
        assert len(_Client.instances) == 1
        assert _Client.instances[0].fetched == ["DSN1"]  # ONE bulk request
        assert calls == [_Client.props]
        assert signals == [1]

    async def test_options_token_wins_over_entry_data(self, hass, monkeypatch):
        monkeypatch.setattr("custom_components.cremalink_ha.Client", _Client)
        _Client.instances, _Client.error = [], None
        device, _ = _device()
        entry = make_entry(
            data={CONF_TOKEN_FILE: "/old.json"},
            options={CONF_TOKEN_FILE: "/new.json"},
        )
        await _run(hass, entry, device)
        assert _Client.instances[0].token_file == "/new.json"

    async def test_cloud_failure_falls_back_silently(self, hass, monkeypatch):
        monkeypatch.setattr("custom_components.cremalink_ha.Client", _Client)
        _Client.instances, _Client.error = [], OSError("cloud down")
        device, calls = _device()
        entry = make_entry(data={CONF_TOKEN_FILE: "/t/DSN1.json"})
        signals = await _run(hass, entry, device)  # must not raise
        assert calls == [] and signals == []
        _Client.error = None

    async def test_empty_seed_sends_no_signal(self, hass, monkeypatch):
        monkeypatch.setattr("custom_components.cremalink_ha.Client", _Client)
        _Client.instances, _Client.error = [], None
        device, _ = _device(seeded=0)
        entry = make_entry(data={CONF_TOKEN_FILE: "/t/DSN1.json"})
        assert await _run(hass, entry, device) == []


class TestSwVersion:
    """``sw_version`` on the device registry: cloud store first, the
    machine's ``software_version`` datapoint as the no-token fallback
    (protocol.md §14.7, captures/lan_software_version.json)."""

    async def test_cloud_software_version_sets_sw_version(self, hass, monkeypatch):
        monkeypatch.setattr("custom_components.cremalink_ha.Client", _Client)
        _Client.instances, _Client.error = [], None
        _Client.props = {
            "d001_rec_espresso": "AAA=",
            "software_version": "Millcore_demo 2.0.0  Jun 18 2020 15:41:06",
        }
        try:
            device, _ = _device()
            entry = make_entry(data={CONF_TOKEN_FILE: "/t/DSN1.json"})
            entry.add_to_hass(hass)
            await _run(hass, entry, device)
            dev_reg = dr.async_get(hass)
            device_entry = dev_reg.async_get_device_by_identifier(
                (DOMAIN, entry.entry_id), entry.entry_id
            )
            assert device_entry is not None
            assert device_entry.sw_version == (
                "Millcore_demo 2.0.0 Jun 18 2020 15:41:06"
            )
        finally:
            _Client.props = {"d001_rec_espresso": "AAA="}

    async def test_no_token_falls_back_to_lan_software_version(self, hass):
        device, _ = _device()
        device.firmware_info = lambda: {
            "machine": "Millcore_demo 2.0.0 Jun 18 2020 15:41:06"
        }
        entry = make_entry(data={})
        entry.add_to_hass(hass)
        await _run(hass, entry, device)
        dev_reg = dr.async_get(hass)
        device_entry = dev_reg.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )
        assert device_entry is not None
        assert device_entry.sw_version == ("Millcore_demo 2.0.0 Jun 18 2020 15:41:06")


class TestSelectReordersOnSeed:
    async def test_signal_refreshes_recipe_options(self, hass):
        calls = []

        def _catalog(**kw):
            calls.append(kw)
            return []

        entry = make_entry()
        device = make_device(beverage_catalog=_catalog)
        monitor = FakeMonitorData(status_name="ready")
        _, entities = await setup_entities(hass, entry, device, select_mod, monitor)
        calls.clear()
        async_dispatcher_send(hass, catalog_ready_signal(entry.entry_id))
        await hass.async_block_till_done()
        assert calls == [{"fetch_priority": True}]  # cached order, no machine GET
