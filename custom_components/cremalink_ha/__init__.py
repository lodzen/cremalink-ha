"""The Cremalink Home Assistant integration."""

import asyncio
import logging
from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from cremalink import Client, EmbeddedLocalServer, create_local_device, device_map

from .const import *
from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.BUTTON, Platform.SENSOR, Platform.BINARY_SENSOR]

#: Belt-and-suspenders bound on top of embedded.py's own site shutdown_timeout --
#: a stuck teardown must never block a reload/unload/removal indefinitely
#: (research.md #7, tasks.md Phase 9).
EMBEDDED_SERVER_STOP_TIMEOUT = 10.0


async def _async_bounded_stop(embedded_server: EmbeddedLocalServer, dsn: str) -> None:
    """Stop the embedded server, never blocking the caller past the bound."""
    try:
        async with asyncio.timeout(EMBEDDED_SERVER_STOP_TIMEOUT):
            await embedded_server.stop()
    except TimeoutError:
        _LOGGER.warning(
            "Embedded local server for %s did not stop within %.0fs; continuing anyway",
            dsn,
            EMBEDDED_SERVER_STOP_TIMEOUT,
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

    except Exception as e:
        _LOGGER.error("Could not resolve device map '%s': %s", map_selection, e)
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
            advertised_ip = entry.data.get(CONF_ADVERTISED_IP)

            embedded_server = EmbeddedLocalServer(
                dsn=dsn,
                device_ip=device_ip,
                lan_key=lan_key,
                device_map_path=str(map_path),
                advertised_ip=advertised_ip,
            )
            await embedded_server.start()

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
                )
            )
        elif connection_type == CONNECTION_CLOUD:
            token_file = entry.data[CONF_TOKEN_FILE]

            def _create_cloud_device():
                client = Client(token_file)
                return client.get_device(dsn, device_map_path=str(map_path))

            device = await hass.async_add_executor_job(_create_cloud_device)

            if device is None:
                raise ConfigEntryNotReady(f"Could not find cloud device with DSN {dsn}")

        else:
            _LOGGER.error("Unknown connection type: %s", connection_type)
            return False
        # Configure the device
        await hass.async_add_executor_job(device.configure)

    except ConfigEntryNotReady:
        raise
    except Exception as e:
        if embedded_server is not None:
            await _async_bounded_stop(embedded_server, dsn)
        raise ConfigEntryNotReady(f"Could not connect to Cremalink device: {e}") from e

    coordinator = CremalinkCoordinator(hass, device, embedded_server=embedded_server)
    await coordinator.async_config_entry_first_refresh()

    if embedded_server is not None:
        entry.async_on_unload(partial(_async_bounded_stop, embedded_server, dsn))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "device": device,
        "embedded_server": embedded_server,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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
