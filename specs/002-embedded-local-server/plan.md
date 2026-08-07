# Implementation Plan: Embedded Local Server (No Add-on Required)

**Branch**: `002-embedded-local-server` | **Date**: 2026-08-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-embedded-local-server/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Replace the mandatory `cremalink-ha` Supervisor add-on for local (LAN)
connectivity with an embedded, asyncio-native local server implemented and
owned by the `cremalink` library, which `cremalink_ha` starts and stops
in-process (inside Home Assistant's own event loop) — the integration
controls the server's lifecycle but never implements server/protocol logic
itself. `cremalink`'s existing `local_server_app` (FastAPI application,
protocol, crypto, jobs, device adapter) already implements the local LAN
protocol and is already fully asyncio-based — this feature adds a new
public, in-process hosting API around that existing app (via a
programmatically driven `uvicorn.Server`, not `uvicorn.run()`/a subprocess),
plus automatic port selection, automatic advertised-IP detection, and
lifecycle management tied to the Home Assistant config entry. New setups
only ever see embedded mode; pre-existing add-on-based config entries are
flagged for an explicit, user-confirmed reconfigure step rather than
silently migrated (per the Clarifications in spec.md).

## Technical Context

**Language/Version**: Python >= 3.13 (`cremalink`), >= 3.13.2 (`cremalink-ha`)

**Primary Dependencies**: `fastapi`==0.136.1, `uvicorn`==0.46.0 (run
programmatically via `uvicorn.Server`/`uvicorn.Config`, not the CLI/`run()`
entrypoint), `starlette`, `httpx` (device-facing HTTP client, already
async), `pydantic`/`pydantic-settings` (existing `ServerSettings`);
`homeassistant` >= 2026.2.3 for the integration side.

**Storage**: Home Assistant config entry data (`entry.data`) for DSN,
device IP, LAN key, and connection-mode/schema markers; no new database or
file storage.

**Testing**: `pytest` + `pytest-asyncio` under `cremalink/tests/`; `pytest`
with mocked `homeassistant.*` modules under `cremalink-ha/tests/`
(existing pattern from `test_config_flow.py`/`test_diagnostics.py`).

**Target Platform**: Home Assistant Core and Home Assistant OS/Supervisor
installs alike (Linux, containers); embedded mode specifically must not
depend on Supervisor being present.

**Project Type**: Library (`cremalink`) + Home Assistant custom
integration (`cremalink_ha`) — existing two-project structure, no new
projects added.

**Performance Goals**: Embedded server must sustain the existing polling
cadence (nudger ~1s, monitor ~5s per `ServerSettings` defaults) with no
event-loop blocking; port/IP resolution at startup must complete in low
single-digit seconds so config entry setup doesn't time out.

**Constraints**: Must run cooperatively on Home Assistant's single asyncio
event loop (no blocking I/O outside executor jobs, per Constitution
Principle V); one embedded server instance per config entry with fully
independent state; automatic port fallback within a bounded range; no
silent migration of existing add-on-based entries.

**Scale/Scope**: Household-scale — a handful of coffee machines per Home
Assistant instance, each with its own embedded server instance and port;
not designed for high device counts or multi-tenant/internet-scale
deployments.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution (`.specify/memory/constitution.md`) was amended as part of
this plan — **v1.0.1 → v1.1.0** — because Principle III previously
hard-coded local mode as "via the companion Cremalink Server add-on"; this
feature's entire purpose is to remove that requirement. Principle III, the
Technology Stack section, and the Project Structure section were updated
to describe the embedded local server as the primary local-mode mechanism
and the Supervisor add-on as deprecated for `cremalink_ha` (see the
Sync Impact Report prepended to the constitution file). This is a MINOR
version bump: the principle's intent (local-first, cloud-fallback) is
unchanged, only the stated mechanism was materially updated.

| Principle | Check | Result |
|---|---|---|
| I. Library-First Architecture | Embedded server hosting logic (uvicorn/FastAPI lifecycle, port/IP resolution) is added to `cremalink`'s public API; `cremalink_ha` only calls it (start/stop) from the coordinator/`__init__.py`. | PASS |
| II. Device-Map-Driven Compatibility | Unaffected — no new device identification logic; existing device maps and `support.local` flags continue to drive availability of local mode. | PASS |
| III. Dual Connection Modes (amended) | Local mode is now explicitly embedded-only, matching the amended principle: `cremalink` implements/owns the embedded server; `cremalink_ha` only starts/stops it (control, not ownership). Cloud mode remains the fallback path, unchanged. | PASS (post-amendment) |
| IV. Cloud Auth & Discovery Reuse | Unaffected — no changes to cloud auth, discovery, or model-detection logic. | PASS |
| V. Home Assistant Integration Conventions | Embedded server start/stop MUST run via `hass.async_add_executor_job`/asyncio tasks scheduled on `hass.loop`, never blocking; lifecycle tied to config entry setup/unload via `entry.async_on_unload`, consistent with `DataUpdateCoordinator` conventions. | PASS (design must enforce this in Phase 1) |
| VI. Secrets & Credential Handling | LAN key and derived session keys follow existing redaction conventions (`diagnostics.py` `REDACT_KEYS`); no new secret types introduced (resolved advertised IP/port are not secrets). | PASS |

No unresolved violations. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/002-embedded-local-server/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── embedded-server-api.md
│   └── reconfigure-flow.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
cremalink/
└── cremalink/
    └── local_server_app/
        ├── api.py            # existing FastAPI app factory (create_app) — reused as-is
        ├── config.py         # existing ServerSettings — reused
        ├── device_adapter.py # existing async device-facing HTTP client — reused
        ├── jobs.py           # existing JobManager/nudger/monitor/rekey jobs — reused
        ├── logging.py        # existing ring-buffer logger — reused
        ├── models.py         # existing request/response models — reused
        ├── protocol.py       # existing crypto/protocol helpers — reused
        ├── state.py          # existing LocalServerState — reused
        └── embedded.py       # NEW: in-process server hosting (uvicorn.Server
                               #   wrapper), port fallback, advertised-IP
                               #   auto-detection, start()/stop() lifecycle API
    └── tests/
        └── test_embedded_server.py  # NEW

cremalink-ha/
└── custom_components/cremalink_ha/
    ├── __init__.py       # MODIFIED: start/stop embedded server per entry;
    │                     #   detect legacy add-on entries needing reconfigure
    ├── config_flow.py    # MODIFIED: remove "local via add-on" step for new
    │                     #   setups; add reconfigure flow for legacy entries
    ├── coordinator.py     # MODIFIED: surface embedded-server task failure
    │                      #   as UpdateFailed (no custom auto-restart)
    ├── const.py          # MODIFIED: new constants (connection schema
    │                     #   marker, port-fallback range, etc.)
    ├── diagnostics.py     # MODIFIED (if new fields need redaction/exposure)
    └── strings.json       # MODIFIED: reconfigure-flow strings
└── tests/
    ├── test_init.py                 # NEW/MODIFIED: embedded server lifecycle
    └── test_config_flow_reconfigure.py  # NEW
```

**Structure Decision**: No new top-level projects. The feature is
implemented almost entirely inside `cremalink/cremalink/local_server_app/`
(one new module, `embedded.py`, reusing every existing internal
component) and `cremalink-ha/custom_components/cremalink_ha/` (lifecycle
wiring + config-flow changes), matching the existing Library-First
Architecture (Principle I): all new local-server-hosting logic lives in
the library, the HA integration only consumes it.

## Complexity Tracking

*No violations — table intentionally omitted.*

