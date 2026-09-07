"""Data update coordinator for the Cremalink integration."""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from cremalink.domain.device import Device

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_FAST = timedelta(seconds=1)
SCAN_INTERVAL_SLOW = timedelta(seconds=30)

class CremalinkCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Cremalink device."""

    def __init__(self, hass: HomeAssistant, device: Device, embedded_server=None):
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            device: The Cremalink device instance.
            embedded_server: The device's `EmbeddedLocalServer` handle, if
                running in embedded local mode (`None` for cloud mode or
                the legacy external-server path).
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Poll the device every second for updates
            update_interval=SCAN_INTERVAL_FAST,
        )
        self.device = device
        self.embedded_server = embedded_server

    async def _async_update_data(self):
        """Fetch data from the device.

        Returns:
            The monitoring data from the device.

        Raises:
            UpdateFailed: If there is an error communicating with the device,
                or if the embedded local server has stopped unexpectedly
                (spec: 002-embedded-local-server, FR-012 — no custom
                auto-restart; recovery follows Home Assistant's own
                reload/retry mechanics).
        """
        if self.embedded_server is not None and self.embedded_server.state == "failed":
            raise UpdateFailed(
                f"Embedded local server for {getattr(self.device, 'dsn', '')} "
                "stopped unexpectedly"
            )

        try:
            data = await self.hass.async_add_executor_job(self.device.get_monitor)

            if data and hasattr(data, 'parsed') and isinstance(data.parsed, dict):
                status = data.parsed.get("status")
                if status == 0:  # if in standby, poll slowly
                    self.update_interval = SCAN_INTERVAL_SLOW
                elif status is not None:
                    self.update_interval = SCAN_INTERVAL_FAST

            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err
