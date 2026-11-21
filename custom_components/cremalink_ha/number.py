"""Number platform — per-recipe parameter sliders (spec FR-008..010).

One entity per user-adjustable recipe parameter (``cremalink.ecam.params
.PARAMS``). Bounds, labels, units, and steps come from the machine's
``0xB0`` descriptor; the shown value is the pending override if set,
else the loaded profile-stored value — machine defaults only when the
read fell back (``values_source`` attribute).

Setting a value only records a raw override in the recipe session —
nothing is written to the machine until ``button.brew_recipe`` merges
the overrides into one ``0x83`` brew frame (transient; spec Q2).
"""

import logging

from cremalink.ecam.params import PARAMS, adjustable_params, to_display, to_raw
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUTTON_UNAVAILABLE_STATUSES,
    DOMAIN,
    NOT_BREWING_STATUSES,
    device_info,
)
from .coordinator import CremalinkCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the recipe-parameter number platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    session = data.get("recipe_session")
    if session is None:
        return

    # Sweep orphaned param registry entries: params dropped from PARAMS
    # (blend/inversion/temp — never brew-sheet controls on the Soul,
    # research.md R12) would otherwise linger as unavailable rows.
    ent_reg = er.async_get(hass)
    keep_uids = {f"{entry.entry_id}_recipe_param_{pid}" for pid in PARAMS}
    for reg in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg.domain == "number" and reg.unique_id not in keep_uids:
            _LOGGER.info("Removing stale recipe-param entity %s", reg.entity_id)
            ent_reg.async_remove(reg.entity_id)

    async_add_entities(
        CremalinkParamNumber(
            data["coordinator"], data["device"], session, entry, param_id
        )
        for param_id in PARAMS
    )


class CremalinkParamNumber(CoordinatorEntity[CremalinkCoordinator], NumberEntity):
    """One adjustable parameter of the currently selected recipe."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, device, session, entry, param_id):
        super().__init__(coordinator)
        self.device = device
        self.session = session
        self._param_id = param_id
        self._meta = PARAMS[param_id]
        self._attr_translation_key = f"param_{self._meta.key}"
        self._attr_unique_id = f"{entry.entry_id}_recipe_param_{param_id}"
        self._attr_device_info = device_info(entry, device)

    @property
    def _params(self):
        return self.session.params

    @property
    def _bound(self):
        params = self._params
        if params is None:
            return None
        return params.bounds.get(self._param_id)

    @property
    def _raw_value(self):
        """Pending override, else loaded stored/default value (raw units)."""
        if self._param_id in self.session.overrides:
            return self.session.overrides[self._param_id]
        params = self._params
        if params is None:
            return None
        return params.values.get(self._param_id)

    @property
    def native_min_value(self):
        bound = self._bound
        return to_display(self._param_id, bound[0]) if bound else 0

    @property
    def native_max_value(self):
        bound = self._bound
        return to_display(self._param_id, bound[2]) if bound else 0

    @property
    def native_step(self):
        """One raw machine unit in display units (1 ml, 0.1 s, 1 step)."""
        return self._meta.to_display

    @property
    def native_unit_of_measurement(self):
        return self._meta.unit

    @property
    def native_value(self):
        raw = self._raw_value
        return to_display(self._param_id, raw) if raw is not None else None

    @property
    def extra_state_attributes(self):
        params = self._params
        raw = self._raw_value
        if params is None:
            return {"param_id": self._param_id}
        return {
            "param_id": self._param_id,
            "beverage_id": params.beverage_id,
            "values_source": params.source,
            "overridden": self._param_id in self.session.overrides,
            **({"raw_value": raw} if raw is not None else {}),
        }

    @property
    def available(self):
        """Only while the recipe enables this parameter (app rules).

        ``adjustable_params`` mirrors the app's brew-sheet builder
        (``MainBeveragesFragment.E1`` — research.md R12): hidden while a
        load is pending (spec Q3), while brewing, and in standby-like
        states — same matrix as the drink buttons.
        """
        data = self.coordinator.data
        if not super().available or not data or data.status_name is None:
            return False
        # `ready` also covers the stale-data window between a recipe/
        # profile change and the next ensure cycle (US5).
        if not self.session.ready:
            return False
        params = self._params
        if self._param_id not in adjustable_params(
            params.bounds, params.values, params.beverage_id
        ):
            return False
        brewing = data.status_name not in NOT_BREWING_STATUSES and bool(data.is_busy)
        return data.status_name not in BUTTON_UNAVAILABLE_STATUSES and not brewing

    async def async_set_native_value(self, value: float) -> None:
        """Record a raw override — no machine write until brew (spec Q2)."""
        # `available` is UI-only — a service call could otherwise write
        # an override onto params scoped to a stale recipe/profile.
        if not self.session.ready:
            raise HomeAssistantError(
                "Recipe parameters are not loaded yet for the selected "
                "recipe/profile — wait for them to appear first."
            )
        raw = to_raw(self._param_id, value)
        bound = self._bound
        if bound is not None:
            raw = max(bound[0], min(bound[2], raw))
        self.session.set_override(self._param_id, raw)
        self.async_write_ha_state()
