# Implementation Plan: Cloud-Assisted Device Onboarding

**Branch**: `001-cloud-assisted-onboarding` | **Date**: 2026-08-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-cloud-assisted-onboarding/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Replace `cremalink_ha`'s manual first config-flow step (device-map picker +
hand-typed DSN/LAN key/IP) with a cloud email/password login that discovers
the account's coffee machines, auto-detects each one's exact model (serial
decoding + OEM table, ported from `delonghi_coffee`), auto-fetches LAN
connection details, and completes setup as local or cloud automatically. Per
the constitution's Library-First and Cloud Auth & Discovery Reuse
principles, the auth/discovery/detection logic is added to the `cremalink`
library; `cremalink_ha`'s config flow only consumes it through the library's
public API. The existing manual device-map/DSN/LAN-key/refresh-token flow is
preserved behind an "advanced setup" link, and an in-flow manual device-map
picker acts as the fallback when auto-detection can't resolve a model.

## Technical Context

**Language/Version**: Python >= 3.13 (`cremalink`), >= 3.13.2 (`cremalink-ha`).

**Primary Dependencies**: `requests` (synchronous HTTP, existing pattern for
Ayla/Gigya calls); `homeassistant` >= 2026.2.3 and `voluptuous` for the
config flow; no new third-party dependency is required — the new logic
reuses `cremalink`'s existing `requests`-based HTTP stack.

**Storage**: JSON device maps (`cremalink/cremalink/devices/*.json`,
unchanged); JSON API resource config (`cremalink/cremalink/resources/
api_config.json`, unchanged for v1 — single EU region); refresh tokens
persisted as JSON under the HA config directory (`cremalink_tokens/`,
existing convention, reused as-is).

**Testing**: `pytest` under `cremalink/tests/` for the new library-level
discovery/model-detection/LAN-lookup logic (matching `cremalink/tests/
test_api.py` conventions); a new `cremalink-ha/tests/` suite (none exists
today) for the config-flow changes, using the same `unittest.mock`
HA-module-stubbing pattern already proven in `delonghi-ha/tests/
conftest.py`.

**Target Platform**: Home Assistant custom integration (HACS) +
companion Supervisor add-on (`cremalink-ha/addons/cremalink-server`,
unaffected by this feature) + the standalone `cremalink` Python library.

**Project Type**: Multi-repo, library-first (per constitution): shared logic
lives in `cremalink/`, `cremalink_ha` stays a thin HA adapter.

**Performance Goals**: Cloud-assisted onboarding completes in under 2
minutes end-to-end (spec SC-001); each discovery/LAN-lookup HTTP call has an
explicit timeout and a small bounded retry (matching existing
`delonghi_coffee` `RETRY_COUNT`/`RETRY_DELAY` conventions) rather than
hanging indefinitely.

**Constraints**: v1 supports only the cloud region for which `cremalink`
already holds valid application credentials (EU / `DeLonghiComfort2` app);
no region credentials are fabricated. Model detection MUST NOT create a
config entry on an unresolved model (falls back to in-flow manual picker,
per Clarifications). All blocking I/O MUST run via
`hass.async_add_executor_job`. New sensitive fields (email, password,
tokens, LAN key) MUST be redacted from diagnostics and never logged.

**Scale/Scope**: Single-user HA installations; typically one, occasionally a
handful of coffee machines per cloud account. No concurrency/multi-tenant
concerns.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Library-First Architecture | New cloud login, discovery, LAN-lookup, and model-detection logic is added to `cremalink` (`clients/cloud.py`, `clients/auth.py`, new `domain/model_detection.py`); `cremalink_ha`'s `config_flow.py` only calls the library's public API. | PASS |
| II. Device-Map-Driven Compatibility | Model detection resolves only to existing `device_map()` ids (`ECAM452`, `ECAM612`); unresolved models never auto-create an entry — they fall back to the existing manual picker (no ad hoc schema, no silent default). | PASS |
| III. Dual Connection Modes | Config flow still reads each device map's `support.local`/`support.cloud` flags to decide whether to offer local, cloud, or both after discovery. | PASS |
| IV. Cloud Auth & Discovery Reuse | Login, discovery, LAN-lookup, and model-detection patterns are ported from `delonghi_coffee`'s `clients/auth.py`-equivalent, `api.py`, and `const.py`/`coordinator.py` logic into `cremalink`, not reimplemented ad hoc or duplicated in `cremalink_ha`. | PASS |
| V. HA Integration Conventions | All new HTTP calls (login, discovery, LAN lookup) run via `hass.async_add_executor_job`; config entry unique ID stays keyed on DSN; no coordinator/polling changes. | PASS |
| VI. Secrets & Credential Handling | Refresh tokens/LAN keys keep using `cremalink_tokens/` storage; new `diagnostics.py` redacts email/password/tokens/LAN key; all new HTTP calls set explicit timeouts; no region credentials are fabricated for regions `cremalink` doesn't already support. | PASS |

No violations identified; Complexity Tracking is not needed.

**Post-Design re-check (after Phase 1)**: `data-model.md` and
`contracts/` confirm the design keeps all new state (`CloudLoginCredentials`,
`DiscoveredDevice`, `ModelDetectionResult`) either transient/in-memory or
mapped onto the existing config-entry `data` shape — no new persistent
storage, no new region tables, and no logic duplicated into `cremalink_ha`
was introduced during design. All six gates remain PASS; no re-justification
needed.

## Project Structure

### Documentation (this feature)

```text
specs/001-cloud-assisted-onboarding/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
cremalink/                              # library-first: new logic lands here
├── cremalink/
│   ├── clients/
│   │   ├── auth.py                     # existing authenticate_cloud() — reused as-is
│   │   └── cloud.py                    # Client: + list_account_devices(), + get_lan_config(), + retry helper
│   ├── domain/
│   │   └── model_detection.py          # NEW: ported _detect_contentstack_pattern-style precedence chain
│   └── devices/                        # existing ECAM452.json / ECAM612.json — unchanged
└── tests/
    ├── test_cloud_client.py            # NEW: discovery, coffee-device filter, LAN lookup, retry
    └── test_model_detection.py         # NEW: serial/OEM/SKU precedence chain

cremalink-ha/
└── custom_components/cremalink_ha/
    ├── config_flow.py                  # cloud login becomes step "user"; existing flow becomes "manual"/advanced
    ├── const.py                        # + CONF_EMAIL, CONF_PASSWORD, new step ids
    ├── diagnostics.py                  # NEW: REDACT_KEYS ported from delonghi_coffee
    └── strings.json                    # + new step labels/errors

cremalink-ha/tests/                     # NEW test directory (none exists today)
└── test_config_flow.py                 # cloud login, discovery, fallback-to-manual, diagnostics redaction
```

**Structure Decision**: Multi-repo layout is unchanged. All new
authentication/discovery/detection logic is added inside the existing
`cremalink/cremalink/` package (library-first, per Principle I);
`cremalink-ha/custom_components/cremalink_ha/` only gains the config-flow
wiring, constants, and a new `diagnostics.py` to consume it. No new
top-level directories or projects are introduced.

## Complexity Tracking

*No Constitution Check violations — this section is intentionally empty.*
