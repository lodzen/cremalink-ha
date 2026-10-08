"""Button platform for the Cremalink integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTION_TYPE, DOMAIN, NOT_READY_STATUSES, STANDBY_STATUSES


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
        self._attr_name = f"{'Brew' if self._title not in ['Stop'] else ''} {self._title} {'brewing' if self._title in ['Stop'] else ''}"
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
        """Reachable and awake (drinks also need the machine fully woken up).

        Availability follows only the machine status, never the monitor's
        action byte: that byte flips while the machine goes to sleep or
        brews, and every unavailable -> available flip of a button shows up
        in Home Assistant as if it had been pressed. A busy machine is
        rejected in :meth:`async_press` instead.
        """
        data = self.coordinator.data
        if not super().available or not data:
            return False
        status = data.status_name
        if status is None:
            # No monitor reading yet (startup): do not claim availability
            # that the first real reading may withdraw seconds later.
            return False
        blocked = STANDBY_STATUSES if self._title == "Stop" else NOT_READY_STATUSES
        return status not in blocked

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
