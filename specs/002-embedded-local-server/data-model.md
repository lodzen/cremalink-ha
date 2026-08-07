# Data Model: Embedded Local Server (No Add-on Required)

This feature adds no persistent database; "data model" here means the
runtime/config-entry-shaped entities involved.

## EmbeddedServerHandle

Runtime-only object (not persisted), one per config entry, owned by
`cremalink_ha` and returned by `cremalink`'s new embedded-hosting API.

| Field | Type | Notes |
|---|---|---|
| `dsn` | str | Device serial identifying the coffee machine (unique key, matches config entry unique ID). |
| `device_ip` | str | LAN IP of the coffee machine, as already stored in config entry data. |
| `lan_key` | str | AES/HMAC key material for the LAN protocol; treated as a secret (redacted in diagnostics/logs). |
| `advertised_ip` | str | Resolved (auto-detected or manually overridden) IP this server advertises to the device. Resolved at start, not a secret. |
| `bound_port` | int | The actual port the embedded server is listening on after fallback resolution (may differ from the configured default). Not a secret; surfaced in diagnostics/logs. |
| `state` | one of `starting` \| `running` \| `stopped` \| `failed` | Lifecycle state, drives coordinator behavior (FR-012). |

**Lifecycle**: `starting` → `running` on successful bind + registration;
→ `failed` on unhandled task exit (surfaces as `UpdateFailed`, no
auto-restart); → `stopped` on config entry unload/reload/removal or HA
shutdown (FR-005). Exactly one handle exists per loaded config entry at a
time (FR-006).

## ConfigEntryData (local mode) — new shape

Existing local-mode config entries store (already present today,
regardless of whether set up manually or via cloud discovery — see
Clarifications):

- `connection_type` = `"local"`
- `dsn`, `device_name`
- `device_map`
- `device_ip`, `lan_key`
- `addon_url` *(legacy field — presence signals a pre-embedded-mode entry)*

New/changed for this feature:

- A new marker distinguishing "embedded-mode" entries from legacy
  add-on-based ones (e.g. absence of `addon_url` combined with a new
  explicit `connection_mode: "embedded"` field written by the reconfigure
  flow and by all new local-mode setups). Exact field name/shape is an
  implementation decision for `/speckit-tasks`, not re-litigated here —
  the requirement (FR-004) is only that legacy entries are
  distinguishable and require the explicit reconfigure step.
- No new secret fields; `lan_key` continues to be the only secret already
  present.

## Reconfigure Flow State (transient, config-flow only)

Not persisted — exists only for the duration of a `SOURCE_RECONFIGURE`
config-flow run, mirroring the existing `_cloud_*` transient attributes
pattern in `config_flow.py`:

| Field | Type | Notes |
|---|---|---|
| `existing_entry` | ConfigEntry | The legacy entry being reconfigured; supplies pre-fill values (DSN, device name, device map). |
| `advertised_ip_override` | str \| None | Optional manual override collected in the reconfigure form (FR-013). |

## Relationships

- One `ConfigEntry` (Home Assistant) ↔ one `EmbeddedServerHandle` (runtime)
  ↔ one physical coffee machine (`dsn`). No sharing across entries
  (FR-006); no relationship to the deprecated Legacy External Server
  entity beyond the one-time reconfigure transition.
