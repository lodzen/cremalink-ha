# Contract: `cremalink` Embedded Local Server API

This is the new public Python API surface `cremalink` exposes so
`cremalink_ha` (or any other consumer) can host the local LAN server
in-process, without a separate OS process or Supervisor add-on.

Location: `cremalink/cremalink/local_server_app/embedded.py`, re-exported
from `cremalink.local_server_app` (and optionally from the top-level
`cremalink` package, matching the existing pattern for
`create_local_device`/`create_cloud_device`).

## `EmbeddedLocalServer`

```python
class EmbeddedLocalServer:
    """In-process host for the cremalink local LAN protocol server.

    Wraps the existing `local_server_app.create_app()` FastAPI application
    with a programmatically driven uvicorn `Server`, running as asyncio
    task(s) on the caller's event loop. No subprocess, no CLI invocation.
    """

    def __init__(
        self,
        dsn: str,
        device_ip: str,
        lan_key: str,
        device_map_path: str,
        *,
        advertised_ip: str | None = None,   # None => auto-detect (FR-013)
        preferred_port: int = 10280,         # FR-007 default
        port_fallback_range: int = 50,       # FR-007 bounded fallback
    ) -> None: ...

    async def start(self) -> None:
        """Resolve advertised IP/port, start the embedded server, and start
        its background jobs (nudger/monitor/rekey). Raises `OSError` if no
        port in `port_fallback_range` could be bound (FR-007/FR-008).
        Idempotent-safe: calling start() twice without an intervening
        stop() raises `RuntimeError`.
        """

    async def stop(self) -> None:
        """Stop background jobs, close the listening socket, and release
        all resources. Safe to call multiple times (FR-005).
        """

    @property
    def bound_port(self) -> int:
        """The actual port in use after fallback resolution (FR-008)."""

    @property
    def advertised_ip(self) -> str:
        """The resolved (auto-detected or overridden) advertised IP."""

    @property
    def state(self) -> str:
        """One of "starting" | "running" | "stopped" | "failed"."""
```

### Behavioral contract

- **FR-001/FR-002**: `start()` results in a server that speaks the exact
  same on-the-wire protocol (`/local_lan/key_exchange.json`,
  `/local_lan/commands.json`, `/local_lan/property/datapoint.json`) as the
  existing standalone server — no protocol changes, only hosting changes.
- **FR-005**: `stop()` MUST fully release the listening socket and cancel
  all background tasks such that a subsequent `start()` (same or new
  instance) can immediately rebind the same port.
- **FR-006**: Each `EmbeddedLocalServer` instance is fully independent —
  no shared module-level/global state with any other instance.
- **FR-007/FR-008**: `start()` performs the bounded port-fallback search
  itself; the caller (integration) only reads `bound_port` afterward for
  logging/diagnostics.
- **FR-012**: If the underlying server task exits unexpectedly, `state`
  becomes `"failed"`; `EmbeddedLocalServer` does **not** auto-restart
  itself — the caller (coordinator) is responsible for surfacing this as
  an update failure.
- **FR-013**: When `advertised_ip` is not supplied, it is auto-detected
  via a UDP-connect-to-`device_ip` trick at `start()` time; a supplied
  value is used as-is (manual override).

### Consumer usage (illustrative only — not implementation code)

```python
server = EmbeddedLocalServer(dsn=dsn, device_ip=device_ip, lan_key=lan_key,
                              device_map_path=map_path)
await server.start()
# ... integration runs normally, entry.async_on_unload(server.stop) ...
await server.stop()
```
