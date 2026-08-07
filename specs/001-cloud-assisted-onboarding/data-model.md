# Phase 1 Data Model: Cloud-Assisted Device Onboarding

Entities introduced or extended by this feature. None of these are new
persistent database tables — they are in-memory shapes passed between the
`cremalink` library and `cremalink_ha`'s config flow, plus small additions
to the existing HA config-entry `data` dict.

## CloudLoginCredentials *(transient, config-flow-scoped only)*

Held only for the duration of the login + discovery steps; never persisted
as-is (only the resulting refresh token is saved, per existing convention).

| Field | Type | Notes |
|---|---|---|
| `email` | str | Required. Cloud account identifier. |
| `password` | str | Required. Never logged; redacted from diagnostics (FR-013). |
| `region` | str | Fixed to `"EU"` for v1 (Research #1). Not user-selectable yet. |

## DiscoveredDevice

Returned by `Client.list_account_devices()` (Research #2). One entry per
appliance on the account; the config flow filters to `is_coffee_device ==
True` before presenting choices to the user.

| Field | Type | Notes |
|---|---|---|
| `dsn` | str | Device Serial Number. Unique identifier (FR-011). |
| `product_name` | str \| None | Friendly/display name reported by the cloud account (FR-003). |
| `oem_model` | str \| None | OEM identifier from Ayla device metadata; input to model detection (FR-004). |
| `raw_serial` | str \| None | Raw serial-number string; input to model detection (FR-004). |
| `is_coffee_device` | bool | Result of the coffee-machine classifier; non-coffee appliances are excluded (FR-002). |
| `lan_enabled` | bool | From `Client.get_lan_config()` (FR-006). |
| `lan_key` | str \| None | AES LAN key, only present when `lan_enabled` (FR-006). |
| `lan_ip` | str \| None | Local IP address, only present when `lan_enabled` (FR-006). |
| `connection_status` | str \| None | e.g. `"Online"`/`"Offline"`, informational only. |

## ModelDetectionResult

Internal return value of `domain.model_detection.detect_model_id()`
(Research #3); not persisted, but its `device_map_id` (or lack thereof)
drives whether the config flow proceeds automatically or falls back to the
in-flow manual picker (FR-005).

| Field | Type | Notes |
|---|---|---|
| `device_map_id` | str \| None | One of the existing `device_map()` ids (e.g. `"ECAM452"`, `"ECAM612"`), or `None` if unresolved. |
| `source` | enum | One of `plaintext_serial`, `binary_serial_sku`, `cloud_metadata`, `oem_table`, `unresolved` — records which precedence step matched, for logging/diagnostics only. |

## ConfigEntryData *(extension of the existing HA config-entry `data` dict)*

No fields are removed; the following are added to support the cloud-assisted
path. Manually-created entries (via the advanced/manual path) are unaffected
and keep their current shape.

| Field | Type | Notes |
|---|---|---|
| `CONF_TOKEN_FILE` | str | *(existing)* Reused as-is for the cloud-assisted path's refresh token. |
| `CONF_DSN` | str | *(existing)* Populated automatically from the selected `DiscoveredDevice`. |
| `CONF_DEVICE_MAP` | str | *(existing)* Populated automatically from `ModelDetectionResult.device_map_id`, or from the user's explicit choice in the in-flow manual fallback picker. |
| `oem_model` | str \| None | *(new, optional)* Persisted for diagnostics/troubleshooting context (redacted only if it proves identifying; classified alongside DSN in `diagnostics.py`). |

## Device Map *(existing, unchanged)*

`cremalink/cremalink/devices/*.json` — `command_map` + `support.{local,
cloud}`. This feature only *resolves to* one of these existing ids; it does
not add, remove, or restructure any device map file.
