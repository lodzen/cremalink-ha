"""Tests for the cloud-assisted onboarding config flow (config_flow.py).

Covers spec US1 (cloud login replaces manual device-map/DSN entry), US2
(automatic model detection + manual fallback), US3 (automatic LAN
discovery -> local connection), and US4 (graceful cloud-only fallback).
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from custom_components.cremalink_ha import config_flow as cf_mod
from custom_components.cremalink_ha.config_flow import CremalinkConfigFlow
from custom_components.cremalink_ha.const import (
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_MAP,
    CONF_DSN,
    CONNECTION_CLOUD,
    CONNECTION_LOCAL,
)


def _run(coro):
    return asyncio.run(coro)


def _make_hass(tmp_path):
    hass = MagicMock()

    async def _executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    hass.async_add_executor_job = _executor
    hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    return hass


def _make_flow(hass) -> CremalinkConfigFlow:
    flow = CremalinkConfigFlow()
    flow.hass = hass
    flow.context = {}
    return flow


class _FakeToken:
    def save(self, path):
        with open(path, "w") as f:
            f.write("{}")
        return path


class _FakeClient:
    """Configurable fake cremalink.Client, controlled via class attrs."""

    raw_devices: list = []
    coffee_devices: list = []
    serial = None
    lan_config = {
        "lan_enabled": False,
        "lanip_key": None,
        "lan_ip": None,
        "status": None,
    }

    def __init__(self, token_path):
        self.token_path = token_path

    def get_devices(self):
        return _FakeClient.raw_devices

    def list_account_devices(self):
        return _FakeClient.coffee_devices

    def get_serial_number(self, dsn):
        return _FakeClient.serial

    def get_lan_config(self, dsn):
        return _FakeClient.lan_config


@pytest.fixture(autouse=True)
def _patch_cloud(monkeypatch):
    monkeypatch.setattr(
        cf_mod, "authenticate_cloud", lambda email, password: _FakeToken()
    )
    monkeypatch.setattr(cf_mod, "Client", _FakeClient)
    monkeypatch.setattr(
        cf_mod, "get_available_maps", lambda hass: ["ECAM452", "ECAM612"]
    )
    monkeypatch.setattr(
        cf_mod,
        "get_map_data",
        lambda hass, name: {"support": {"local": True, "cloud": True}},
    )
    _FakeClient.raw_devices = []
    _FakeClient.coffee_devices = []
    _FakeClient.serial = None
    _FakeClient.lan_config = {
        "lan_enabled": False,
        "lanip_key": None,
        "lan_ip": None,
        "status": None,
    }
    yield


class TestCloudLoginStep:
    def test_single_coffee_device_creates_entry_without_prompt(
        self, tmp_path, monkeypatch
    ):
        _FakeClient.raw_devices = ["DSN1"]
        _FakeClient.coffee_devices = [
            {
                "dsn": "DSN1",
                "product_name": "PrimaDonna",
                "oem_model": "DL-pd-soul",
                "lan_enabled": False,
            }
        ]
        monkeypatch.setattr(cf_mod, "detect_model_id", lambda *a, **k: "ECAM452")

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_DSN] == "DSN1"
        assert result["data"][CONF_DEVICE_MAP] == "ECAM452"

    def test_multi_device_account_shows_device_select(self, tmp_path):
        _FakeClient.raw_devices = ["DSN1", "DSN2"]
        _FakeClient.coffee_devices = [
            {"dsn": "DSN1", "product_name": "PrimaDonna", "oem_model": "DL-pd-soul"},
            {
                "dsn": "DSN2",
                "product_name": "Dinamica",
                "oem_model": "DL-dinamica-plus",
            },
        ]

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["type"] == "form"
        assert result["step_id"] == "device_select"

    def test_invalid_credentials_show_auth_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            cf_mod,
            "authenticate_cloud",
            lambda email, password: (_ for _ in ()).throw(ValueError("bad creds")),
        )

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "wrong", "manual_setup": False}
            )
        )

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "auth_failed"

    def test_zero_coffee_devices_shows_no_coffee_machine_error(self, tmp_path):
        _FakeClient.raw_devices = ["DSN1"]
        _FakeClient.coffee_devices = []

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["errors"]["base"] == "no_coffee_machine"

    def test_zero_devices_shows_no_devices_error(self, tmp_path):
        _FakeClient.raw_devices = []
        _FakeClient.coffee_devices = []

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["errors"]["base"] == "no_devices"

    def test_advanced_setup_checkbox_routes_to_manual_step_unchanged(self, tmp_path):
        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user({"email": "", "password": "", "manual_setup": True})
        )

        assert result["type"] == "form"
        assert result["step_id"] == "manual"


class TestModelDetectionFallback:
    def test_unresolved_model_routes_to_manual_map_prefilled(
        self, tmp_path, monkeypatch
    ):
        _FakeClient.raw_devices = ["DSN1"]
        _FakeClient.coffee_devices = [
            {
                "dsn": "DSN1",
                "product_name": "Mystery Machine",
                "oem_model": "DL-unknown",
            }
        ]
        monkeypatch.setattr(cf_mod, "detect_model_id", lambda *a, **k: None)

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["type"] == "form"
        assert result["step_id"] == "manual_map"
        assert result["description_placeholders"]["dsn"] == "DSN1"
        assert result["description_placeholders"]["device_name"] == "Mystery Machine"

        result2 = _run(flow.async_step_manual_map({CONF_DEVICE_MAP: "ECAM612"}))
        assert result2["type"] == "create_entry"
        assert result2["data"][CONF_DEVICE_MAP] == "ECAM612"


class TestLocalConnectionCompletion:
    def test_lan_enabled_and_local_supported_creates_local_entry(
        self, tmp_path, monkeypatch
    ):
        _FakeClient.raw_devices = ["DSN1"]
        _FakeClient.coffee_devices = [
            {"dsn": "DSN1", "product_name": "PrimaDonna", "oem_model": "DL-pd-soul"}
        ]
        _FakeClient.lan_config = {
            "lan_enabled": True,
            "lanip_key": "KEY123",
            "lan_ip": "192.168.1.5",
            "status": "Online",
        }
        monkeypatch.setattr(cf_mod, "detect_model_id", lambda *a, **k: "ECAM452")

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_LOCAL
        assert result["data"]["lan_key"] == "KEY123"
        assert result["data"]["device_ip"] == "192.168.1.5"
        # No add-on required (spec 002-embedded-local-server, FR-003/FR-004)
        assert "addon_url" not in result["data"]
        assert result["data"]["connection_mode"] == "embedded"


class TestManualLocalSetup:
    """Manual/advanced local setup no longer offers an add-on URL step."""

    def test_device_step_never_shows_or_collects_addon_url(self, tmp_path):
        flow = _make_flow(_make_hass(tmp_path))

        # Home Assistant's menu jumps straight to async_step_device() on
        # selection -- it never calls back through async_step_choose_connection.
        result = _run(flow.async_step_device())

        assert result["type"] == "form"
        assert result["step_id"] == "device"
        assert "addon_url" not in str(result["data_schema"])

    def test_device_step_creates_embedded_mode_entry(self, tmp_path):
        flow = _make_flow(_make_hass(tmp_path))
        _run(flow.async_step_device())

        result = _run(
            flow.async_step_device(
                {
                    "device_name": "My Machine",
                    "dsn": "DSN9",
                    "lan_key": "key9",
                    "device_ip": "192.168.1.9",
                    "device_map": "ECAM452",
                }
            )
        )

        assert result["type"] == "create_entry"
        assert "addon_url" not in result["data"]
        assert result["data"]["connection_mode"] == "embedded"

    def test_choose_connection_menu_step_exists_and_matches_option_keys(self, tmp_path):
        """Regression test: Home Assistant requires a menu's own step_id to
        be a real async_step_* method (raises UnknownStep otherwise), even
        though selecting an option never calls back into it -- it jumps
        straight to async_step_<chosen>. Every menu_options key must also
        be a real async_step_* method for the same reason.
        """
        flow = _make_flow(_make_hass(tmp_path))

        result = _run(flow.async_step_choose_connection())

        assert result["type"] == "menu"
        assert result["step_id"] == "choose_connection"
        assert hasattr(flow, "async_step_choose_connection")
        for option_key in result["menu_options"]:
            assert hasattr(flow, f"async_step_{option_key}")


class TestCloudFallbackCompletion:
    def test_lan_disabled_completes_as_cloud_automatically(self, tmp_path, monkeypatch):
        _FakeClient.raw_devices = ["DSN1"]
        _FakeClient.coffee_devices = [
            {"dsn": "DSN1", "product_name": "PrimaDonna", "oem_model": "DL-pd-soul"}
        ]
        _FakeClient.lan_config = {
            "lan_enabled": False,
            "lanip_key": None,
            "lan_ip": None,
            "status": None,
        }
        monkeypatch.setattr(cf_mod, "detect_model_id", lambda *a, **k: "ECAM452")

        flow = _make_flow(_make_hass(tmp_path))
        result = _run(
            flow.async_step_user(
                {"email": "a@b.com", "password": "pw", "manual_setup": False}
            )
        )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_CLOUD
        assert "token_file" in result["data"]
