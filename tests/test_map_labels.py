"""Tests for the device-map picker labels in the config flow."""

from custom_components.cremalink_ha import config_flow as cf_mod


def test_map_labels_include_model_name(hass, monkeypatch):
    monkeypatch.setattr(cf_mod, "get_device_maps", lambda: ["ECAM612", "ECAM452"])
    names = {"ECAM452": "Eletta Explore"}
    monkeypatch.setattr(
        cf_mod,
        "get_map_data",
        lambda hass, name: {"model_name": names[name]} if name in names else {},
    )

    labels = cf_mod.get_available_maps(hass)

    assert labels == {"ECAM452": "ECAM452 – Eletta Explore", "ECAM612": "ECAM612"}
    assert list(labels) == ["ECAM452", "ECAM612"]


def test_bundled_maps_name_their_model(hass):
    labels = cf_mod.get_available_maps(hass)

    assert labels["ECAM452"] == "ECAM452 – Eletta Explore"
    assert labels["ECAM612"] == "ECAM612 – PrimaDonna Soul"
