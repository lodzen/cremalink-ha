"""The Cremalink Home Assistant integration."""

import asyncio
import logging
from functools import partial
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from cremalink import (
    Client,
    EmbeddedLocalServer,
    create_local_device,
    device_map,
    log_event,
)

from .const import *
from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]

#: Belt-and-suspenders bound on top of embedded.py's own site shutdown_timeout --
#: a stuck teardown must never block a reload/unload/removal indefinitely
#: (research.md #7, tasks.md Phase 9).
EMBEDDED_SERVER_STOP_TIMEOUT = 10.0


def _is_docker_container() -> bool:
    """Return whether the integration appears to run in a Docker container."""
    return Path("/.dockerenv").is_file()


async def _async_bounded_stop(embedded_server: EmbeddedLocalServer, dsn: str) -> None:
    """Stop the embedded server, never blocking the caller past the bound."""
    try:
        async with asyncio.timeout(EMBEDDED_SERVER_STOP_TIMEOUT):
            await embedded_server.stop()
    except TimeoutError:
        embedded_server.log(
            "embedded_server_stop_timeout",
            {"dsn": dsn, "timeout_seconds": EMBEDDED_SERVER_STOP_TIMEOUT},
            level=logging.WARNING,
        )


def _needs_reconfigure(entry: ConfigEntry) -> bool:
    """True for local-mode entries set up before the embedded server existed.

    Such entries were created against the (now deprecated) Supervisor
    add-on and carry ``CONF_ADDON_URL`` but no embedded-mode marker; their
    stored data must not be silently reused (spec: 002-embedded-local-server,
    FR-004 — explicit, user-confirmed reconfiguration only).
    """
    return (
        CONF_ADDON_URL in entry.data
        and entry.data.get(CONF_CONNECTION_MODE) != CONNECTION_MODE_EMBEDDED
    )


def _async_create_reconfigure_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Flag a legacy local-mode entry as needing reconfiguration (FR-004)."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"reconfigure_{entry.entry_id}",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REPAIR_RECONFIGURE_REQUIRED,
        translation_placeholders={
            "device_name": entry.data.get(DEVICE_NAME) or entry.data.get(CONF_DSN, ""),
            "dsn": entry.data.get(CONF_DSN, ""),
        },
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cremalink from a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry.

    Returns:
        True if the setup was successful, False otherwise.
    """
    connection_type = entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_LOCAL)

    dsn = entry.data[CONF_DSN]

    map_selection = entry.data[CONF_DEVICE_MAP]

    try:
        # Resolve the device map path
        if map_selection.startswith("custom:"):
            filename = map_selection.split(":", 1)[1]
            map_path = hass.config.path(CUSTOM_MAP_DIR, filename)
        else:
            map_path = await hass.async_add_executor_job(device_map, map_selection)

    except (OSError, ValueError, RuntimeError) as e:
        log_event(
            _LOGGER,
            "device_map_resolve_failed",
            {"device_map": map_selection, "error_type": type(e).__name__},
            level=logging.ERROR,
        )
        return False

    embedded_server: EmbeddedLocalServer | None = None
    try:
        if connection_type == CONNECTION_LOCAL:
            if _needs_reconfigure(entry):
                _async_create_reconfigure_issue(hass, entry)
                raise ConfigEntryNotReady(
                    f"{entry.title or dsn} was set up with the Cremalink Server "
                    "add-on, which is no longer used. Reconfigure this device "
                    "(see Settings > Repairs) to switch to the built-in local "
                    "server."
                )

            lan_key = entry.data[CONF_LAN_KEY]
            device_ip = entry.data[CONF_DEVICE_IP]
            advertised_ip = entry.options.get(
                CONF_ADVERTISED_IP, entry.data.get(CONF_ADVERTISED_IP)
            )
            if isinstance(advertised_ip, str):
                advertised_ip = advertised_ip.strip() or None

            embedded_server = EmbeddedLocalServer(
                dsn=dsn,
                device_ip=device_ip,
                lan_key=lan_key,
                device_map_path=str(map_path),
                advertised_ip=advertised_ip,
                monitor_poll_interval=DEFAULT_MONITOR_POLL_INTERVAL,
                nudger_poll_interval=DEFAULT_NUDGER_POLL_INTERVAL,
                event_logger=_LOGGER,
            )
            await embedded_server.start()
            if advertised_ip is None and _is_docker_container():
                embedded_server.log(
                    "advertised_ip_auto_detected_in_docker",
                    {
                        "advertised_ip": embedded_server.advertised_ip,
                        "bridge_networking_may_be_unreachable": True,
                    },
                    level=logging.WARNING,
                )

            # Create the local device instance, pointed at our own
            # in-process server instead of an external add-on/CLI process.
            device = await hass.async_add_executor_job(
                partial(
                    create_local_device,
                    dsn=dsn,
                    server_host="127.0.0.1",
                    server_port=embedded_server.bound_port,
                    device_ip=device_ip,
                    lan_key=lan_key,
                    device_map_path=str(map_path),
                    event_logger=embedded_server.event_logger,
                )
            )
        elif connection_type == CONNECTION_CLOUD:
            token_file = entry.data[CONF_TOKEN_FILE]

            def _create_cloud_device():
                client = Client(token_file, logger=_LOGGER)
                return client.get_device(dsn, device_map_path=str(map_path))

            device = await hass.async_add_executor_job(_create_cloud_device)

            if device is None:
                raise ConfigEntryNotReady(f"Could not find cloud device with DSN {dsn}")

        else:
            log_event(
                _LOGGER,
                "unknown_connection_type",
                {"connection_type": connection_type},
                level=logging.ERROR,
            )
            return False
        # Configure the device
        await hass.async_add_executor_job(device.configure)

    except ConfigEntryNotReady:
        raise
    except Exception as e:
        if embedded_server is not None:
            await _async_bounded_stop(embedded_server, dsn)
        raise ConfigEntryNotReady(f"Could not connect to Cremalink device: {e}") from e

    coordinator = CremalinkCoordinator(
        hass,
        device,
        embedded_server=embedded_server,
        monitor_poll_interval=(
            DEFAULT_MONITOR_POLL_INTERVAL if embedded_server is not None else None
        ),
    )
    await coordinator.async_config_entry_first_refresh()

    if embedded_server is not None:
        entry.async_on_unload(partial(_async_bounded_stop, embedded_server, dsn))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "device": device,
        "embedded_server": embedded_server,
    }
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after its local options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry.

    Returns:
        True if unload was successful.
    """
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
