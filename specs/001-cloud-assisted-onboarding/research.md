# Phase 0 Research: Cloud-Assisted Device Onboarding

All items below were resolved from the existing codebase (`cremalink`,
`cremalink-ha`, `delonghi-ha/custom_components/delonghi_coffee`) and the
spec's Clarifications session. No Technical Context items remain marked
`NEEDS CLARIFICATION`.

## 1. Region-aware cloud login

- **Decision**: Keep `cremalink`'s login single-region (EU) for v1, reusing
  the existing `authenticate_cloud(email, password, language)` in
  `clients/auth.py` and `resources/api_config.json` as-is. Do not add a
  region dropdown to the new config-flow login step.
- **Rationale**: `cremalink`'s Ayla application (`DeLonghiComfort2-mw-id`)
  is a **different app** than `delonghi_coffee`'s (`DLonghiCoffeeIdKit-*`).
  `delonghi_coffee`'s `REGIONS` table holds per-region app id/secret pairs
  for *its own* app only — there is no legitimate source for
  `DeLonghiComfort2`'s US/CN app credentials in this repo, and fabricating
  them would violate the "never guess secrets" constraint and the
  constitution's Secrets & Credential Handling principle. This matches the
  spec's Assumptions section (region scope limited to EU for v1).
- **Alternatives considered**: Copying `delonghi_coffee`'s `REGIONS` dict
  wholesale — rejected, it contains the wrong app's credentials and would
  authenticate against the wrong Ayla application or fail outright.
- **Extension point for later**: `authenticate_cloud()` already accepts a
  `language` parameter; a future `region` parameter can be added the same
  way once real `DeLonghiComfort2` regional credentials are obtained —
  out of scope for this feature.

## 2. Device discovery & coffee-machine filtering

- **Decision**: Add a new `Client.list_account_devices()` method to
  `cremalink/cremalink/clients/cloud.py` that calls the existing
  `/devices.json` Ayla endpoint (already used internally by
  `Client.__init__`) and returns enriched dicts (`dsn`, `product_name`,
  `oem_model`, `lan_enabled`, `connection_status`), then filters to
  coffee-machine devices only via a ported `is_coffee_device()` classifier
  (equivalent to `delonghi_coffee`'s `is_coffee_oem_model`).
- **Rationale**: The existing `Client.get_devices()` returns
  `list[str]` (DSNs only) and is used by the current cloud-auth config-flow
  step; changing its return type in place would be a breaking change for
  any existing caller. Adding a new method preserves backward compatibility
  while giving the config flow what it needs (friendly name + classification
  + LAN flag) in one call.
- **Alternatives considered**: Mutating `get_devices()`'s return shape —
  rejected (breaking change); doing the coffee-machine filtering in
  `cremalink_ha` instead of the library — rejected (violates Principle I,
  Library-First Architecture).

## 3. Model detection (serial decoding + OEM/SKU mapping)

- **Decision**: Add `cremalink/cremalink/domain/model_detection.py` with a
  pure function `detect_model_id(raw_serial, cloud_metadata, oem_model) ->
  str | None` implementing the same precedence chain as
  `delonghi_coffee`'s `coordinator._detect_contentstack_pattern`: (1)
  plaintext model pattern in the raw serial, (2) decoded binary-serial SKU
  lookup, (3) cloud metadata fields (product/model code), (4) static
  OEM-identifier table — but returning one of `cremalink`'s own
  `device_map()` ids (`ECAM452`, `ECAM612`) instead of `delonghi_coffee`'s
  ECAM-family strings.
- **Rationale**: Constitution Principle II requires detection to resolve
  only to existing device map ids; Principle IV requires the precedence
  logic itself to be ported rather than reinvented.
- **Open follow-up (not fabricated here)**: The concrete OEM-identifier and
  SKU values that map to `ECAM452` and `ECAM612` specifically are **not
  yet confirmed** against real hardware/serial samples in this repo (unlike
  `delonghi_coffee`'s tables, which were built from confirmed hardware in
  GitHub issues). Task breakdown (`/speckit-tasks`) MUST include a step to
  populate these two mapping tables from verified serial/OEM samples (from
  existing users' diagnostics or hardware access) before relying on
  detection in production; until populated, detection safely falls back to
  the in-flow manual picker (per Clarifications) rather than guessing.
- **Alternatives considered**: A live/remote lookup service (like
  ContentStack) — rejected, adds an external dependency and network round
  trip for no benefit; `delonghi_coffee`'s local-table approach is cheaper
  and already proven.

## 4. Automatic LAN connection detail discovery

- **Decision**: Add `Client.get_lan_config(dsn)` to `clients/cloud.py`,
  ported directly from `delonghi_coffee`'s `api.get_lan_config` — same Ayla
  platform, same account, calling `/dsns/{dsn}.json` then
  `/devices/{dsn}/lan.json` for `lan_enabled`, `lanip_key`, `lan_ip`,
  `connection_status`.
- **Rationale**: Same cloud platform (Ayla) already backs `cremalink`'s
  existing cloud transport; the endpoints and response shape are already
  validated in production by `delonghi_coffee`.
- **Alternatives considered**: None — direct port of a proven, working
  integration.

## 5. Retry behavior for transient cloud failures

- **Decision**: Port a small bounded-retry helper (matching
  `delonghi_coffee`'s `_retry` decorator plus `RETRY_COUNT`/`RETRY_DELAY`
  constants) into `cremalink/cremalink/clients/cloud.py`, applied to
  `list_account_devices()` and `get_lan_config()` only.
  All calls keep explicit timeouts (constitution Principle VI).
- **Rationale**: Matches the accepted Clarification (bounded auto-retry
  before surfacing an error) and existing proven conventions.
- **Alternatives considered**: No retry (immediate failure) — rejected per
  Clarifications; unbounded/backoff-forever retry — rejected, would block
  the config flow step indefinitely, conflicting with SC-001's 2-minute
  budget.

## 6. Diagnostics redaction

- **Decision**: Add `cremalink-ha/custom_components/cremalink_ha/
  diagnostics.py` with a `REDACT_KEYS` set covering the newly-introduced
  sensitive fields (`email`, `password`, `access_token`, `refresh_token`,
  `lan_key`, `device_ip`), modeled directly on `delonghi_coffee`'s existing
  `diagnostics.py`.
- **Rationale**: `cremalink_ha` currently has no diagnostics support at
  all; this feature is the first to introduce cloud email/password and
  auto-fetched LAN keys into its config entries, so redaction must ship
  alongside them (accepted Clarification).
- **Alternatives considered**: Deferring diagnostics to a later feature —
  rejected per Clarifications (in scope now, to avoid a window where these
  fields could leak via a diagnostics export before redaction exists).

## 7. Config-flow entry point restructuring

- **Decision**: `async_step_user` becomes the new cloud-login step (email +
  password only; region fixed to EU). A "manual setup" link/menu option on
  that same screen leads to `async_step_manual`, which is today's existing
  device-map-picker-first flow, otherwise unchanged.
- **Rationale**: Matches the accepted Clarification (cloud login replaces
  the first step; manual flow moves to an advanced/secondary path).
- **Alternatives considered**: Keeping the device-map picker as step one
  with cloud login as a secondary option — rejected per Clarifications.

## 8. Testing strategy for `cremalink-ha` (currently untested)

- **Decision**: Introduce `cremalink-ha/tests/` using the same
  `unittest.mock`-based Home Assistant module stubbing already proven in
  `delonghi-ha/tests/conftest.py` (stub `homeassistant.*` modules at import
  time, real-redact stand-in for `homeassistant.components.diagnostics`),
  rather than adopting a new test-harness dependency.
- **Rationale**: Keeps the two sibling integrations' test conventions
  consistent and avoids introducing `pytest-homeassistant-custom-component`
  (a much larger dependency) for this feature alone.
- **Alternatives considered**: `pytest-homeassistant-custom-component` —
  rejected for this feature (bigger new dependency, not used by either
  existing sibling integration); can be revisited separately.
