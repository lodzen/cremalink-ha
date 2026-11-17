"""Firmware sensor: Wi-Fi module version, machine firmware on the device."""

from custom_components.cremalink_ha import sensor as sensor_mod
from custom_components.cremalink_ha.const import DOMAIN
from homeassistant.helpers import device_registry as dr

from tests.helpers import FakeMonitorData, make_device, make_entry, setup_entities

INFO = {
    "machine": "Striker_cb_demo 1.1.0 Oct 18 2022 10:44:21",
    "wifi_module": "ADA 1.6 esp-idf-v3.3.1",
    "wifi_module_updated_at": "2023-02-07T19:08:11Z",
}


async def test_shows_versions_and_sets_device_firmware(hass):
    device = make_device()
    device.firmware_info = lambda: dict(INFO)
    entry = make_entry()
    entry.add_to_hass(hass)
    # The entity platform creates the device before adding the entity.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}
    )
    _, entities = await setup_entities(
        hass, entry, device, sensor_mod, FakeMonitorData(status_name="ready")
    )
    sensor = next(
        e for e in entities if isinstance(e, sensor_mod.CremalinkFirmwareSensor)
    )

    assert sensor.native_value == "ADA 1.6 esp-idf-v3.3.1"
    assert sensor.extra_state_attributes == {
        "updated_at": "2023-02-07T19:08:11Z",
        "machine_firmware": "Striker_cb_demo 1.1.0 Oct 18 2022 10:44:21",
    }
    device_entry = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device_entry is not None
    assert device_entry.sw_version == INFO["machine"]


async def test_no_sensor_without_firmware_support(hass):
    _, entities = await setup_entities(
        hass,
        make_entry(),
        make_device(),
        sensor_mod,
        FakeMonitorData(status_name="ready"),
    )
    assert not any(isinstance(e, sensor_mod.CremalinkFirmwareSensor) for e in entities)
