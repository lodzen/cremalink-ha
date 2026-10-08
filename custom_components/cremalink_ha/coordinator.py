"""Data update coordinator for the Cremalink integration."""

import logging
import time
from datetime import timedelta

from cremalink.domain.device import Device
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_FAST = timedelta(seconds=1)
SCAN_INTERVAL_SLOW = timedelta(seconds=30)

#: Slow-lane statistics fetch cadence (minutes-scale per spec R10 — the
#: 0xA2 paging session and cloud property snapshots do not need fast polls).
STATISTICS_INTERVAL = timedelta(minutes=5)

#: Consecutive failed refreshes tolerated before entities go unavailable
#: (FR-035 — a single transient LAN/transport failure must not flap state).
DEFAULT_FAILURE_THRESHOLD = 3


class CremalinkCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Cremalink device."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: Device,
        embedded_server=None,
        monitor_poll_interval: float | None = None,
    ):
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
            update_interval=(
                timedelta(seconds=monitor_poll_interval)
                if monitor_poll_interval is not None
                else SCAN_INTERVAL_FAST
            ),
        )
        self.device = device
        self.embedded_server = embedded_server
        self._adaptive_interval = monitor_poll_interval is None
        # Slow-lane statistics state (T025) — fetched at STATISTICS_INTERVAL
        # cadence, not on every monitor poll.
        self.statistics = None
        self._statistics_fetched_at: float | None = None
        # None = unknown yet, True/False once the first fetch resolved.
        self.statistics_supported: bool | None = None
        # Read-failure retention (T045/FR-035).
        self.consecutive_failures = 0
        self.failure_threshold = DEFAULT_FAILURE_THRESHOLD

    async def _async_fetch_statistics(self) -> None:
        """Refresh the slow-lane statistics report when due.

        Paced per R10: at most one fetch per STATISTICS_INTERVAL. A
        transport that cannot serve the source (`NotImplementedError`)
        marks the feature unsupported permanently — no retry storms.
        Other errors keep the previous report.
        """
        now = time.monotonic()
        if (
            self._statistics_fetched_at is not None
            and now - self._statistics_fetched_at < STATISTICS_INTERVAL.total_seconds()
        ):
            return
        self._statistics_fetched_at = now
        if self.statistics_supported is False:
            return
        get_statistics = getattr(self.device, "get_statistics", None)
        if get_statistics is None:
            # Devices/transports without the statistics API are treated
            # as unsupported — probe once, never retry.
            self.statistics_supported = False
            return
        try:
            self.statistics = await self.hass.async_add_executor_job(get_statistics)
            self.statistics_supported = True
        except NotImplementedError:
            self.statistics_supported = False
        except (OSError, ValueError, RuntimeError) as err:
            # keep the previous report on transient fetch failures
            _LOGGER.debug("Statistics fetch failed: %s", err)

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

            if (
                self.embedded_server is not None
                and data
                and getattr(data, "raw_b64", None)
            ):
                snapshot = getattr(data, "snapshot", None)
                self.embedded_server.log_telemetry(
                    "decoded_local_monitor",
                    {
                        "received_at": getattr(data, "received_at", None),
                        "raw_b64": data.raw_b64,
                        "parsed": data.parsed,
                        "warnings": getattr(snapshot, "warnings", []),
                        "errors": getattr(snapshot, "errors", []),
                    },
                )

            if (
                self._adaptive_interval
                and data
                and hasattr(data, "parsed")
                and isinstance(data.parsed, dict)
            ):
                status = data.parsed.get("status")
                if status == 0:  # if in standby, poll slowly
                    self.update_interval = SCAN_INTERVAL_SLOW
                elif status is not None:
                    self.update_interval = SCAN_INTERVAL_FAST

            self.consecutive_failures = 0
            await self._async_fetch_statistics()
            return data
        except Exception as err:
            self.consecutive_failures += 1
            raise UpdateFailed(f"Error communicating with device: {err}") from err
