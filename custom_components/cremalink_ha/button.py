"""Button platform for the Cremalink integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUTTON_UNAVAILABLE_STATUSES,
    CONF_CONNECTION_TYPE,
    DOMAIN,
    NOT_BREWING_STATUSES,
    NOT_READY_STATUSES,
    TRANSLATED_COMMANDS,
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the button platform.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry.
        async_add_entities: Function to add entities.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device = data["device"]

    # Get available commands from the device
    cmds = await hass.async_add_executor_job(device.get_commands)

    entities = []
    for cmd in cmds:
        # Filter out power commands as they might be handled elsewhere
        if cmd.lower() not in ["wakeup", "standby", "refresh"]:
            entities.append(CremalinkButton(coordinator, device, cmd, entry))
    async_add_entities(entities)


class CremalinkButton(CoordinatorEntity, ButtonEntity):
    """Representation of a Cremalink button."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device, cmd, entry):
        """Initialize the button.

        Args:
            coordinator: The data update coordinator.
            device: The Cremalink device instance.
            cmd: The command associated with this button.
            entry: The config entry.
        """
        super().__init__(coordinator)
        self.device = device
        self._cmd = cmd
        self._title = cmd.replace("_", " ").title()
        if cmd in TRANSLATED_COMMANDS:
            self._attr_translation_key = f"cmd_{cmd}"
        else:
            # A command of a custom device map: no translation shipped.
            self._attr_name = f"Brew {self._title}"
        self._attr_unique_id = f"{entry.entry_id}_cmd_{cmd}"
        self._attr_icon = "mdi:coffee"
        self._connection_type = entry.data.get(CONF_CONNECTION_TYPE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="cremalink",
        )

    @property
    def available(self):
        """Stop only while a brew runs; drinks unless asleep, waking or brewing.

        The transition into standby (``going_to_sleep``) does not make any
        button unavailable; standby itself does. A press during the
        transition is rejected in :meth:`async_press`. ``is_busy`` (the
        monitor's action byte, latched in standby) only counts as a running
        brew while the status says so.
        """
        data = self.coordinator.data
        if not super().available or not data:
            return False
        status = data.status_name
        if status is None:
            # No monitor reading yet (startup): do not claim availability
            # that the first real reading may withdraw seconds later.
            return False
        brewing = status not in NOT_BREWING_STATUSES and bool(data.is_busy)
        if self._title == "Stop":
            return brewing
        return status not in BUTTON_UNAVAILABLE_STATUSES and not brewing

    async def async_press(self):
        """Handle the button press."""
        data = self.coordinator.data
        # Stop is always sent (harmless when idle); drinks need a ready machine.
        if self._title != "Stop" and data:
            if data.status_name in NOT_READY_STATUSES:
                raise HomeAssistantError("The machine is not ready; turn it on first.")
            if data.is_busy:
                raise HomeAssistantError("The machine is busy; wait until it is ready.")
        await self.hass.async_add_executor_job(self.device.do, self._cmd)
        await self.coordinator.async_request_refresh()
