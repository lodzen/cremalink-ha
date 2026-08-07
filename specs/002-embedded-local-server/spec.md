# Feature Specification: Embedded Local Server (No Add-on Required)

**Feature Branch**: `[002-embedded-local-server]`

**Created**: 2026-08-07

**Status**: Draft

**Input**: User description: "the delonghi-ha/custom_components/delonghi_coffee is spawning an lan server in the component itself withouth the need to create an addon for Homeassistant. i want to apply the same feature for the cremalink library to run the component withouth the need to install an homeassistant addon."

## Clarifications

### Session 2026-08-07

- Q: If the embedded server's background task crashes or raises an unhandled exception mid-session, should the integration automatically try to restart it, or should the config entry just go unavailable until Home Assistant reloads it? → A: Let it fail — mark the entry/coordinator unavailable and rely on Home Assistant's existing reload/retry mechanics (no custom auto-restart logic).
- Q: Should the embedded server automatically detect the IP address it advertises to the coffee machine, or should the user still manually enter an "advertised IP" during setup? → A: Auto-detect the advertised IP (e.g. via the OS route to the device IP), with an optional manual override in advanced settings.
- Q: If a user has both the legacy add-on/CLI server and a new embedded-mode config entry pointed at the same physical coffee machine at the same time, should the system actively prevent/detect that conflict, or is it explicitly the user's responsibility to avoid it? → A: Explicitly unsupported/user responsibility — document that only one local-mode consumer (embedded or external) should target a given device at a time; no runtime detection built.
- Q: Should embedded mode be offered alongside the add-on/external-server connection option, or should it fully replace it? → A: Fully replace it — `cremalink_ha` MUST NOT offer or require the separate Supervisor add-on/external server at all; local mode is embedded-only. (See the next clarification for how existing add-on-based entries transition.)
- Q: Should existing add-on-based config entries be migrated to embedded mode silently/automatically, or should the user be asked to reconfigure them after upgrading? → A: Ask the user to reconfigure — existing local-mode entries were set up under two different prior flows (very old manual DSN/LAN-key/IP entry, and the newer cloud-account-based discovery that never re-verifies the add-on connection), so their stored data isn't reliable enough to reuse silently. On upgrade, prompt the user (e.g. via Home Assistant's repair/reconfigure mechanism) to redo local setup; already-known values (DSN, device name) MAY be pre-filled to minimize re-entry, but the switch to embedded mode MUST be explicit and user-confirmed, not silent.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Local mode works without installing any add-on (Priority: P1)

A user setting up a coffee machine in local (LAN) mode configures the
integration entirely from Home Assistant — DSN, device IP, LAN key, device
map — and the integration itself starts talking to the machine on the LAN.
They never install, start, or configure the separate "Cremalink for
Home-Assistant" Supervisor add-on, and they never need Supervisor at all
(so the integration also works on Home Assistant Core / non-Supervisor
installs).

**Why this priority**: This is the entire point of the feature — it removes
a mandatory extra install step (and a Supervisor-only requirement) for the
most common connection mode. Without this, local mode remains unusable for
any non-Supervisor Home Assistant installation.

**Independent Test**: Can be fully tested by adding a config entry in local
mode on a Home Assistant instance with no Cremalink add-on installed, and
confirming the coordinator successfully receives monitor/property updates
from a real or simulated coffee machine.

**Acceptance Scenarios**:

1. **Given** a user has DSN, device IP, and LAN key for their machine,
   **When** they complete the local-mode config flow without ever
   installing the add-on, **Then** the integration starts talking to the
   machine directly and the config entry becomes ready.
2. **Given** the config entry is set up in embedded local mode, **When**
   the coffee machine performs its key exchange and starts polling for
   commands, **Then** the integration (not a separate process) answers the
   handshake and command-poll requests directly.
3. **Given** Home Assistant is not running the Supervisor (Home Assistant
   Core install), **When** the user sets up local mode, **Then** setup
   succeeds without any reference to or requirement for the Supervisor
   add-on.

---

### User Story 2 - Embedded server lifecycle matches the config entry (Priority: P1)

The embedded local server for a device starts when its config entry is set
up and stops cleanly when the entry is unloaded, reloaded, or removed, and
when Home Assistant shuts down — leaving no orphaned listening sockets or
background tasks behind.

**Why this priority**: Home Assistant integrations are expected to clean up
after themselves; a server that keeps listening after its config entry is
gone would leak resources, block ports on reload, and could let a stale
process keep talking to the machine after the user removed it from HA.

**Independent Test**: Can be fully tested by adding, reloading, and then
removing a local-mode config entry, and verifying (e.g. via port-bind
checks or task inspection) that the embedded server's listening socket and
background tasks are gone after each unload/removal.

**Acceptance Scenarios**:

1. **Given** a local-mode config entry is loaded, **When** the entry is
   reloaded (e.g. after an options change), **Then** the old embedded
   server instance is stopped before the new one starts, with no leftover
   listening socket on the old port.
2. **Given** a local-mode config entry is loaded, **When** the entry is
   removed or Home Assistant shuts down, **Then** the embedded server stops
   and its port is released.
3. **Given** two local-mode config entries for two different coffee
   machines exist, **When** both are loaded, **Then** each runs its own
   independent embedded server instance without interfering with the
   other's state, keys, or command queue.

---

### User Story 3 - Existing add-on-based entries are reconfigured after upgrade (Priority: P2)

A user who previously set up local mode against the standalone
`cremalink-server` Supervisor add-on upgrades the integration and is
clearly prompted (not left guessing) that their local-mode device needs to
be reconfigured to keep working. Already-known details (DSN, device name)
are pre-filled where possible so they don't have to look them up again, but
they explicitly confirm/complete the switch to embedded mode. Once
reconfigured, they can uninstall the add-on entirely.

**Why this priority**: The goal of this feature is to eliminate the add-on
requirement completely, not merely make embedded mode the default for new
setups. Existing users must not be silently switched onto a connection
mode built from data captured under a different, unverified setup flow —
but they also must not be left stuck depending on the add-on forever with
no clear path off it.

**Independent Test**: Can be fully tested by taking a pre-existing
add-on-based config entry, upgrading the integration, and confirming the
user is presented with a clear reconfigure step (pre-filled where
possible) that results in a working embedded-mode entry once completed.

**Acceptance Scenarios**:

1. **Given** a user has an existing config entry pointing at the add-on,
   **When** they upgrade to a version of the integration that includes
   this feature, **Then** the entry is flagged as needing reconfiguration
   rather than silently switched to embedded mode.
2. **Given** the reconfigure step is presented, **When** the user completes
   it, **Then** already-known values (DSN, device name) are pre-filled and
   the entry starts running in embedded mode without the user needing to
   rediscover that information from scratch.
3. **Given** a config entry has been reconfigured to embedded mode, **When**
   the user stops or uninstalls the Supervisor add-on, **Then** the
   integration continues to operate normally.
4. **Given** a brand-new user is setting up local mode for the first time,
   **When** they go through the config flow, **Then** no option to connect
   to an external add-on/CLI server is presented — embedded mode is the
   only local connection path.

---

### User Story 4 - Port conflicts are handled automatically (Priority: P3)

When the embedded server's preferred port is already taken (by another
config entry's embedded server, a leftover add-on, or an unrelated process),
the integration automatically picks a different free port instead of
failing setup, and this is visible to the user if they need to debug it.

**Why this priority**: Users are not expected to manually manage port
numbers across multiple devices or coexisting deployments; automatic
recovery avoids a confusing, hard-to-diagnose setup failure.

**Independent Test**: Can be fully tested by occupying the default port
with a dummy listener, then adding a local-mode config entry and confirming
it starts successfully on an alternate port, with the chosen port visible
in logs/diagnostics.

**Acceptance Scenarios**:

1. **Given** the default local server port is already in use, **When** a
   new local-mode config entry is set up, **Then** the embedded server
   binds to the next available port instead of failing.
2. **Given** two config entries both use embedded local mode, **When**
   both are loaded, **Then** each is automatically assigned a distinct
   port with no manual configuration required.
3. **Given** a port fallback occurred, **When** the user inspects
   diagnostics or logs, **Then** the actual bound port is clearly reported.

### Edge Cases

- What happens if the coffee machine's key-exchange or command-poll
  requests arrive before the embedded server has finished starting (race
  between config entry setup and the machine's first LAN request)?
- What happens if a user dismisses or ignores the reconfigure prompt for an
  existing add-on-based entry — does it keep failing to update indefinitely,
  or is there a grace period / clear ongoing indication that action is
  needed?
- If the embedded server's task crashes mid-session, the coordinator MUST
  surface this as a failed update (entry becomes unavailable) rather than
  silently restarting it in-place; recovery happens via Home Assistant's
  existing reload/retry mechanics.
- What happens if the auto-detected advertised/callback IP is not reachable
  from the device (multi-NIC or containerized HA setups) — is the manual
  override (FR-013) the only recourse, and how does the user discover they
  need it?
- How does the system behave if a user manually keeps the legacy add-on
  installed and running *after* reconfiguring to embedded mode, targeting
  the same device the now-embedded config entry also targets? This is
  explicitly unsupported and left as a user responsibility (documented,
  not runtime-detected) — the device will only reliably register with
  whichever controller it last handshook with. Since the config flow no
  longer offers the add-on for new setups, this can only happen if the
  user manually keeps it running post-reconfiguration.
- What happens when Home Assistant restarts abruptly (crash, not clean
  shutdown) — are stale keys/session state from the previous run discarded
  cleanly on the next embedded server start?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `cremalink` library MUST expose a public, asyncio-native
  API to start and stop an in-process local server for a single device
  (DSN, device IP, LAN key, device map) without requiring a separate OS
  process, Supervisor add-on, or manual `cremalink-server` invocation.
- **FR-002**: The embedded server MUST implement the same on-the-wire local
  LAN protocol (key exchange, command polling, property/datapoint ingestion)
  as the existing standalone server, so a coffee machine cannot distinguish
  between embedded and external-process deployments.
- **FR-003**: `cremalink_ha`'s local connection mode MUST use the embedded
  server exclusively for all new setups. The config flow MUST NOT present
  connecting to an external add-on/CLI server as an option, and MUST NOT
  require the user to install, configure, or run the separate Supervisor
  add-on at any point.
- **FR-004**: Existing config entries previously configured against the
  external add-on/CLI server MUST be flagged as needing reconfiguration
  after upgrade (e.g. via Home Assistant's repair/reconfigure mechanism)
  rather than silently switched to embedded mode. Already-known values
  (DSN, device name) MAY be pre-filled to reduce re-entry, but the user
  MUST explicitly complete the reconfiguration before the entry runs in
  embedded mode.
- **FR-005**: The embedded server's lifecycle MUST be tied to its owning
  config entry: it MUST start during config entry setup and MUST stop
  (releasing its listening socket and any background tasks) during config
  entry unload, reload, or removal, and on Home Assistant shutdown.
- **FR-006**: When multiple config entries use embedded local mode
  simultaneously, each MUST run an independent server instance with its own
  state (keys, command queue, IV chains) and MUST NOT share state with
  other entries.
- **FR-007**: Each embedded server instance MUST automatically select an
  available network port, starting from the existing default port and
  falling back to alternate free ports on conflict, without requiring the
  user to manually enter or manage port numbers.
- **FR-008**: On port conflict, the system MUST log a clear warning
  indicating the conflict and the fallback port chosen, and MUST make the
  actual bound port visible via existing diagnostics/logging conventions.
- **FR-009**: Sensitive data handled by the embedded server (LAN key,
  derived session keys) MUST follow the same secrets-handling and
  diagnostics-redaction conventions already used elsewhere in
  `cremalink_ha` (no plaintext secrets in logs or diagnostics).
- **FR-010**: All blocking or long-running operations of the embedded
  server MUST run cooperatively within Home Assistant's asyncio event loop
  (or a clearly isolated executor/task) and MUST NOT block the event loop.
- **FR-011**: The `cremalink-ha` Supervisor add-on MUST be deprecated as a
  connection path for `cremalink_ha`: it MUST NOT be required, installed,
  or referenced by the config flow after this feature ships. The
  underlying `cremalink` library MAY continue to offer its standalone
  `cremalink-server` CLI entry point for non-Home-Assistant use, but that
  usage is independent of, and not required by, `cremalink_ha`.
- **FR-012**: If the embedded server's background task terminates
  unexpectedly, the integration MUST surface this as a coordinator update
  failure (config entry becomes unavailable) rather than silently
  auto-restarting the server task; recovery MUST follow Home Assistant's
  standard reload/retry mechanics, not a custom supervision loop.
- **FR-013**: The embedded server MUST automatically determine the IP
  address it advertises to the coffee machine (e.g. via the local route to
  the device's IP) without requiring the user to enter it manually, while
  still allowing an optional manual override for edge cases (multi-NIC or
  containerized Home Assistant hosts).

### Key Entities

- **Embedded Local Server**: An in-process, asyncio-managed server instance
  bound to one coffee machine (DSN, device IP, LAN key) that speaks the
  local LAN protocol; owned and lifecycle-managed by a single config entry.
  This is the only local connection path `cremalink_ha` offers after this
  feature ships.
- **Legacy External Server (deprecated)**: The prior out-of-process
  deployment form (Supervisor add-on or standalone CLI), reached over HTTP
  by host/port. No longer offered by `cremalink_ha`; existing config
  entries that used it are flagged for user-driven reconfiguration to the
  Embedded Local Server. Retained only as a reference for the
  reconfigure path and as an independent, non-HA use of the `cremalink`
  library itself.
- **Port Assignment**: The runtime-resolved network port an embedded server
  instance is actually bound to, which may differ from the configured
  default when a conflict is detected.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from "no add-on installed" to "local mode
  device successfully polling data" using only steps inside the Home
  Assistant UI, with zero Supervisor add-on installation steps.
- **SC-002**: Reloading or removing a local-mode config entry releases its
  server's listening port within a few seconds, verifiable by immediately
  reusing that port without a conflict.
- **SC-003**: Running two local-mode config entries simultaneously results
  in both devices reporting live data concurrently, with no cross-entry
  interference in commands or monitored properties.
- **SC-004**: When the default port is occupied, a new local-mode config
  entry still completes setup successfully on the first attempt, on a
  different port, with no user-visible failure.
- **SC-005**: 100% of existing add-on-based config entries are clearly
  flagged as needing reconfiguration after upgrading, and a user who
  completes the prompted reconfigure step ends up with a working
  embedded-mode entry with no continued dependency on the Supervisor
  add-on.

## Assumptions

- The embedded server reuses the existing local LAN protocol implementation
  in `cremalink` (`local_server_app` internals — state, protocol, device
  adapter) rather than reimplementing the wire protocol; only the
  process/transport boundary (in-process asyncio server vs. a separate
  uvicorn/FastAPI OS process) changes.
- "Embedded" means the server runs as asyncio task(s) inside the same
  Python process and event loop as Home Assistant (via
  `hass.loop`/`async_add_executor_job` conventions), not as a subprocess
  spawned by the integration.
- One embedded server instance corresponds to exactly one config entry
  (one coffee machine); multi-device-per-server configurations are out of
  scope, consistent with the current server's single-device state model.
- Automatic port selection is scoped to the local machine/network
  namespace Home Assistant runs in; no coordination across separate Home
  Assistant instances is required.
- This feature targets `cremalink` + `cremalink_ha` only; `delonghi-ha` is
  the existing reference implementation and is not modified by this
  feature.
- The Supervisor add-on is deprecated as far as `cremalink_ha` is
  concerned: the config flow no longer offers or requires it for new
  setups, and existing entries are flagged for user-driven reconfiguration
  rather than silently switched over. Physically deleting the add-on
  package/repo files is a separate housekeeping decision and out of scope
  for this feature.
- The `cremalink` library's standalone CLI server remains available for
  non-Home-Assistant use cases (e.g. manual/dev usage, other consumers of
  the library); this feature does not require removing it, only removing
  `cremalink_ha`'s dependency on it.
- Existing security/credential-handling conventions (no plaintext secrets
  in logs, diagnostics redaction) extend to the embedded server without
  needing new mechanisms.
- Running more than one local-mode consumer (embedded or external) against
  the same physical device at the same time is explicitly unsupported and
  is the user's responsibility to avoid; the system does not detect or
  block this cross-entry conflict at runtime.
