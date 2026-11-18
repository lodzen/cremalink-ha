"""Per-entry brew-parameter session state.

One ``RecipeSession`` per config entry, shared by the recipe select, the
parameter number entities, and the brew button. Holds the selected
beverage, the loaded :class:`~cremalink.domain.device.RecipeParams`, and
the user's pending raw overrides — all transient per spec (no persistence,
cleared on recipe/profile change so nothing leaks across recipes).

Machine I/O never happens here directly: ``async_ensure_params`` schedules
the library's blocking ``recipe_params`` read on the executor exactly
once per (recipe, profile) pair; entities watch ``loading``/``params``.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from .const import STANDBY_STATUSES

if TYPE_CHECKING:
    from cremalink.domain.device import Device, RecipeParams
    from homeassistant.core import HomeAssistant

    from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)

#: Minimum seconds between failed param-load attempts — a standby or
#: otherwise unanswering machine must not be flooded with republish
#: requests on every coordinator poll.
LOAD_RETRY_INTERVAL = 60.0


@dataclass
class RecipeSession:
    """Selected beverage + loaded params + pending overrides for one entry."""

    device: "Device"
    selected_beverage: int | None = None
    params: "RecipeParams | None" = None
    overrides: dict[int, int] = field(default_factory=dict)
    loading: bool = False
    _profile_seen: int = 0
    _load_task: asyncio.Task | None = field(default=None, repr=False)
    _last_attempt: float | None = field(default=None, repr=False)

    def select(self, beverage_id: int) -> None:
        """Select a recipe — discards the previous recipe's values/overrides."""
        if beverage_id != self.selected_beverage:
            self.selected_beverage = beverage_id
        self.params = None
        self.overrides.clear()
        self._last_attempt = None  # a new selection retries immediately

    def clear(self) -> None:
        """Drop the selection entirely (values and overrides with it)."""
        self.selected_beverage = None
        self.params = None
        self.overrides.clear()

    def set_override(self, param_id: int, raw_value: int) -> None:
        """Record a pending override (raw machine units)."""
        self.overrides[param_id] = raw_value

    def _profile_changed(self) -> bool:
        """True once, when the device's active profile differs from the last
        successful load's scope — stale values/overrides are discarded."""
        current = int(getattr(self.device, "current_profile", 0) or 0)
        if current == self._profile_seen:
            return False
        self._profile_seen = current
        return True

    @property
    def ready(self) -> bool:
        """Params loaded for the *current* ``(beverage, profile)`` pair.

        ``_profile_changed`` only clears ``params`` when
        ``async_ensure_params`` next runs — between a profile change and
        the next coordinator cycle the stale values would otherwise stay
        brewable/editable. ``ready`` is instantaneous: it compares the
        loaded params' scope to the live selection and profile. The
        profile comparison mirrors the brew-side resolution
        (``current_profile or 1`` in ``Device.recipe_params``/``brew``)
        so an unasserted profile (0) means slot 1, not "never ready".
        """
        if self.loading or self.params is None or self.selected_beverage is None:
            return False
        if self.params.beverage_id != self.selected_beverage:
            return False
        current = int(getattr(self.device, "current_profile", 0) or 0) or 1
        return self.params.profile_slot == current

    async def async_ensure_params(
        self, hass: "HomeAssistant", coordinator: "CremalinkCoordinator"
    ) -> None:
        """Load the selected recipe's params once on the executor.

        Re-arms on recipe or profile change (params cleared → reload).
        While a load is in flight ``loading`` stays True — controls and
        the brew action are blocked until the machine confirms values
        (spec clarification Q3).
        """
        if self._profile_changed() and self.selected_beverage is not None:
            self.params = None
            self.overrides.clear()
        if self.selected_beverage is None or self.params is not None or self.loading:
            return
        data = coordinator.data
        status = getattr(data, "status_name", None)
        if status is None or status in STANDBY_STATUSES:
            # A standby machine serves no datapoint republishes — defer
            # the load instead of flooding it with doomed GETs.
            return
        if (
            self._last_attempt is not None
            and time.monotonic() - self._last_attempt < LOAD_RETRY_INTERVAL
        ):
            return  # backoff after a failed attempt — no per-poll retries
        self.loading = True
        self._load_task = hass.async_create_task(self._load(coordinator))

    async def _load(self, coordinator: "CremalinkCoordinator") -> None:
        beverage_id = self.selected_beverage
        if beverage_id is None:  # unselected between ensure() and task start
            self.loading = False
            return
        try:
            params = await coordinator.hass.async_add_executor_job(
                partial(self.device.recipe_params, beverage_id)
            )
            # A recipe switch mid-flight must not accept stale values.
            if beverage_id == self.selected_beverage:
                self.params = params
        except (OSError, ValueError, RuntimeError) as err:
            _LOGGER.debug("recipe params load failed for %s: %s", beverage_id, err)
            self._last_attempt = time.monotonic()
        finally:
            self.loading = False
            await coordinator.async_request_refresh()
