# Phase 0 Research: Embedded Local Server (No Add-on Required)

All items below were unknowns or implicit decisions in the Technical
Context; no `NEEDS CLARIFICATION` markers remain.

## 1. Hosting the existing FastAPI app in-process (no separate OS process)

**Decision**: Add a new `cremalink/cremalink/local_server_app/embedded.py`
module that wraps the existing `create_app()` FastAPI application with
`uvicorn.Config` + `uvicorn.Server`, driven programmatically (`await
server.serve()` scheduled as an asyncio task on the *caller's* event loop —
i.e. Home Assistant's `hass.loop`), instead of `uvicorn.run()` (which is a
blocking, process-owning entrypoint that installs its own signal handlers
and creates its own event loop). `Server.install_signal_handlers` is
disabled/no-op'd since Home Assistant, not uvicorn, owns process-level
signal handling.

**Rationale**: `local_server_app`'s internals (`LocalServerState`,
`DeviceAdapter`, `JobManager`, `protocol.py`) are already fully
asyncio-native (`httpx.AsyncClient`, `asyncio.Lock`, `asyncio.create_task`)
— none of that needs to change. The only thing tying the local server to a
separate OS process today is *how* the ASGI app is hosted
(`local_server.py`'s `uvicorn.run(...)` call, or the Supervisor add-on
wrapping that same CLI). Reusing uvicorn's programmatic `Server` API avoids
re-implementing the protocol a second time (which the pre-existing
`delonghi_coffee/lan.py` had to do because it started from a raw aiohttp
server with no prior async implementation to reuse).

**Alternatives considered**:
- *Rewrite as a raw aiohttp server* (mirroring `delonghi_coffee/lan.py`
  exactly). Rejected: `cremalink` already has a working, tested LAN
  protocol implementation in `local_server_app`; rewriting it in aiohttp
  would duplicate crypto/protocol logic and double the test surface for no
  functional benefit. Kept as a documented fallback if embedding uvicorn's
  `Server` inside another framework's loop proves unreliable in practice
  (verify during implementation with an integration test that starts/stops
  it repeatedly inside a real asyncio loop).
- *Subprocess-per-entry* (integration spawns `python -m
  cremalink.local_server` as a child process it manages). Rejected: this
  reintroduces the separate-process model the constitution amendment and
  this feature explicitly move away from, plus adds IPC/lifecycle
  complexity (process supervision, port handoff) with no benefit over
  in-process asyncio tasks.

## 2. Automatic port selection with fallback

**Decision**: Attempt to bind the existing default port
(`ServerSettings.server_port`, currently `10280`); on `OSError`
(`EADDRINUSE`), retry on the next port in a small bounded range (e.g. up to
+50) until a free port is found or the range is exhausted, logging a
warning identifying the conflict and the chosen fallback port (FR-008).
Exhausting the range is a setup failure surfaced to the user like any other
`ConfigEntryNotReady`.

**Rationale**: Matches FR-007/FR-008 and SC-004 directly; a small bounded
range is enough for realistic household device counts (Scale/Scope) and
avoids scanning the entire ephemeral port space.

**Alternatives considered**: Ask the OS for an ephemeral port (bind to
port 0). Rejected for the *default* port specifically, because keeping the
existing well-known default (`10280`) for the common single-device case
preserves compatibility with any existing firewall rules/network ACLs
users may have already set up around that port; ephemeral fallback is only
used once the default (and its small increment range) is unavailable is
not needed — the bounded-increment approach already covers that case.

## 3. Automatic advertised-IP detection

**Decision**: Determine the IP to advertise to the coffee machine using the
"UDP connect" trick: open a `SOCK_DGRAM` socket, `connect()` it to
`(device_ip, 1)` (no packets are actually sent), and read back
`getsockname()[0]` — this returns the local interface IP the OS would use
to route toward the device, without needing routing-table parsing or
external dependencies. An optional manual override field is available in
advanced settings for the reconfigure flow.

**Rationale**: Directly resolves FR-013; is a standard, dependency-free,
synchronous-but-fast (no actual network I/O) technique already reachable
via the Python standard library `socket` module, run in an executor job
per Constitution Principle V.

**Alternatives considered**: Parsing `/proc/net/route` or the host's
network interfaces. Rejected: Linux-specific / more fragile across the
various OSes Home Assistant Core can run on; the UDP-connect trick is
portable.

## 4. Reconfigure UX for legacy add-on-based entries

**Decision**: On integration setup, detect legacy local-mode entries by
the presence of the old `CONF_ADDON_URL` key (and/or the absence of a new
schema/version marker) in `entry.data`. For such entries, do not start an
embedded server automatically; instead raise a Home Assistant repair issue
(`homeassistant.helpers.issue_registry`) that is fixable and links to the
integration's `SOURCE_RECONFIGURE` config-flow step. The reconfigure step
pre-fills already-known values (DSN, device name) from the existing entry
data and, once completed, replaces the entry's data with the new
embedded-mode shape.

**Rationale**: Matches the Clarifications decision (explicit,
user-confirmed switch, not silent) and follows Home Assistant's own
idiomatic mechanism for "this integration needs your attention after an
update" (repairs + reconfigure flow), rather than inventing a bespoke
in-integration migration prompt.

**Alternatives considered**: A one-time "migration" banner/persistent
notification. Rejected: repairs + reconfigure is the standard, already
localized/UI-integrated HA mechanism for exactly this kind of
breaking-change-requires-user-action scenario.

## 5. Crash/failure handling

**Decision**: The embedded server's hosting task is wrapped with a
done-callback that records failure state; the coordinator's
`_async_update_data` checks this state and raises `UpdateFailed` when the
task has exited unexpectedly, per FR-012. No custom supervision/backoff
loop is added — recovery follows Home Assistant's existing coordinator
retry/backoff and entry reload mechanics.

**Rationale**: Directly resolves the crash-recovery Clarification; keeps
the implementation minimal per Constitution Principle V
(`DataUpdateCoordinator` pattern is mandatory for all polling/failure
signaling).

**Alternatives considered**: Custom auto-restart with backoff inside the
embedded server wrapper. Rejected per Clarifications (explicitly decided
against to avoid a second, bespoke supervision system next to HA's own).

## 6. Per-entry isolation for multiple simultaneous embedded servers

**Decision**: Each config entry owns exactly one embedded-server handle
(port, advertised IP, `LocalServerState`, `JobManager`, uvicorn `Server`
instance), stored in `hass.data[DOMAIN][entry.entry_id]`, created in
`async_setup_entry` and torn down via `entry.async_on_unload`.

**Rationale**: Directly resolves FR-006 and User Story 2's independence
requirement; matches the existing per-entry `hass.data` storage pattern
already used in `cremalink_ha/__init__.py`.

**Alternatives considered**: A single shared multi-device server process.
Rejected: `local_server_app`'s state model (`LocalServerState`) is
single-device by design (Assumptions in spec.md); multiplexing many
devices through one server instance would require a state-model rewrite
out of scope for this feature.
