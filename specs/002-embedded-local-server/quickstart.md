# Quickstart: Embedded Local Server (No Add-on Required)

This is a validation guide, not an implementation guide — it proves the
feature works end-to-end. See [contracts/embedded-server-api.md](./contracts/embedded-server-api.md)
and [contracts/reconfigure-flow.md](./contracts/reconfigure-flow.md) for the
exact API/flow contracts, and [data-model.md](./data-model.md) for entity
shapes.

## Prerequisites

- `cremalink` installed in editable mode (`uv pip install -e cremalink[test]`).
- `cremalink-ha` test dependencies installed (`uv pip install -e cremalink-ha[test]`
  or per `requirements_test.txt`).
- A real or simulated coffee machine reachable on the LAN (DSN, device IP,
  LAN key), OR the existing mocked-device test fixtures for automated runs.

## 1. Library-level validation (`cremalink`)

```bash
cd cremalink
uv run pytest tests/test_embedded_server.py -v
```

Expected: an `EmbeddedLocalServer` instance can `start()` and immediately
answer a simulated device's key-exchange/command-poll requests exactly
like the existing standalone `local_server_app` tests already prove for
the FastAPI app itself; `stop()` releases the port such that a fresh
`EmbeddedLocalServer` can immediately rebind it (`SC-002`).

## 2. Port-conflict fallback

```bash
cd cremalink
uv run pytest tests/test_embedded_server.py -k port_fallback -v
```

Expected: occupying the default port with a dummy listener before calling
`start()` results in the server binding to a fallback port instead of
raising, with `bound_port` reflecting the actual port used (`FR-007`,
`FR-008`, `SC-004`).

## 3. Integration-level validation (`cremalink_ha`)

```bash
cd cremalink-ha
uv run pytest tests/test_init.py -k embedded -v
```

Expected:
- Setting up a new local-mode config entry starts an embedded server with
  no reference to `CONF_ADDON_URL` (`FR-003`, `SC-001`).
- Reloading/removing the entry stops the embedded server and releases its
  port (`FR-005`, `SC-002`).
- Two simultaneously loaded local-mode entries each get independent
  embedded servers on distinct ports (`FR-006`, `FR-007`, `SC-003`).

## 4. Reconfigure flow validation

```bash
cd cremalink-ha
uv run pytest tests/test_config_flow_reconfigure.py -v
```

Expected: a config entry seeded with legacy data (`CONF_ADDON_URL`
present) does **not** auto-start an embedded server on setup; a repair
issue is created; completing the reconfigure flow rewrites the entry data
and results in a running embedded server (`FR-004`, `SC-005`).

## 5. Manual end-to-end check (real hardware, optional)

1. Ensure the `cremalink-server` Supervisor add-on is **not** installed.
2. Add a new local-mode config entry via the Home Assistant UI, entering
   DSN/device IP/LAN key directly (or via the cloud-assisted flow from
   `specs/001-cloud-assisted-onboarding`).
3. Confirm entities report live data with no add-on running
   (`SC-001`, User Story 1).
4. Reload the config entry from the UI; confirm no port-bind errors on
   the reload and data resumes flowing (`SC-002`, User Story 2).
5. If you have a pre-existing add-on-based entry from before this
   feature: confirm a repair appears in Settings → Repairs, complete it,
   and confirm the entry keeps reporting data afterward with the add-on
   stopped (`SC-005`, User Story 3).
