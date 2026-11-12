"""Shared fixtures for Cremalink tests.

Runs on HA's real pytest harness (`pytest-homeassistant`) — the plugin
provides the `hass` fixture, `MockConfigEntry`, and the custom-integration
loader. Fixture/entity construction helpers live in `tests/helpers.py`.
"""

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.cremalink_ha.const import DOMAIN


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A Cremalink config entry with neutral data/options."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry1",
        title="Soul",
        data={},
        options={},
    )
