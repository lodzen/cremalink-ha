---

description: "Task list template for feature implementation"
---

# Tasks: Embedded Local Server (No Add-on Required)

**Input**: Design documents from `/specs/002-embedded-local-server/`

**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (required for user stories), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. This repo has an established convention (see `001-cloud-assisted-onboarding`) of shipping test tasks alongside implementation, and `quickstart.md`/`contracts/` already name specific test files (`test_embedded_server.py`, `test_config_flow_reconfigure.py`) as part of the validation strategy.

**Organization**: Tasks are grouped by user story (from spec.md, priority order) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Multi-repo, library-first layout (per plan.md Project Structure):

- `cremalink/cremalink/local_server_app/` — shared library (embedded server hosting) + `cremalink/tests/`
- `cremalink-ha/custom_components/cremalink_ha/` — HA integration + `cremalink-ha/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Constants/strings shared across multiple user stories

- [X] T001 [P] Add new constants (embedded-mode connection marker, e.g. `CONF_CONNECTION_MODE`/`CONNECTION_MODE_EMBEDDED`, `DEFAULT_LOCAL_SERVER_PORT`, `LOCAL_SERVER_PORT_FALLBACK_RANGE`; keep existing `CONF_ADDON_URL` for legacy-entry detection) to `cremalink-ha/custom_components/cremalink_ha/const.py`
- [X] T002 [P] Add new translation/error strings (reconfigure step labels and description, `reconfigure_required` repair title/description, `advertised_ip` field label) to `cremalink-ha/custom_components/cremalink_ha/strings.json`

**Checkpoint**: Shared constants/strings exist; ready for Foundational library work.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The core embedded-server hosting capability every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Implement `EmbeddedLocalServer.__init__`/`start()`/`stop()` in `cremalink/cremalink/local_server_app/embedded.py` — wraps the existing `create_app()` FastAPI app with a programmatically driven `uvicorn.Config`/`uvicorn.Server` (not `uvicorn.run()`), scheduled as an asyncio task on the caller's event loop; binds a single fixed port for now (no fallback yet — see US4); starts/stops the existing `JobManager` background jobs on `start()`/`stop()` (research.md #1, contracts/embedded-server-api.md). **Note**: implemented with the bounded port-fallback loop (T032) already built in from the start (own bind-then-hand-to-uvicorn socket approach was required anyway to avoid uvicorn's `sys.exit(1)` on bind failure — see embedded.py docstring/comments), so US4's fallback behavior is already present here.
- [X] T004 Implement advertised-IP auto-detection (UDP-connect-to-`device_ip` trick, used whenever `advertised_ip=None`) in `cremalink/cremalink/local_server_app/embedded.py` (depends on T003, same file) (research.md #3, FR-013)
- [X] T005 Implement crash/failure detection — an asyncio task done-callback that sets `EmbeddedLocalServer.state = "failed"` on unexpected exit, exposed via a `.state` property — in `cremalink/cremalink/local_server_app/embedded.py` (depends on T003, same file) (research.md #5, FR-012)
- [X] T006 Export `EmbeddedLocalServer` from `cremalink/cremalink/local_server_app/__init__.py` and the top-level `cremalink/cremalink/__init__.py`, mirroring the existing `create_local_device` export pattern (depends on T003)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Local mode works without installing any add-on (Priority: P1) 🎯 MVP (part 1 of 2 — see US2)

**Goal**: New local-mode setups run entirely via an in-process embedded server; no add-on install/config step exists anywhere in the config flow.

**Independent Test**: Add a config entry in local mode on a Home Assistant instance with no Cremalink add-on installed, and confirm the coordinator receives monitor/property updates from a real or simulated coffee machine.

### Tests for User Story 1

- [X] T007 [P] [US1] Test that `EmbeddedLocalServer.start()` completes a simulated device's key-exchange/command-poll cycle exactly like the existing `local_server_app` protocol tests, in `cremalink/tests/test_embedded_server.py`
- [X] T008 [P] [US1] Test that new local-mode config-flow setups never write `CONF_ADDON_URL` and that no add-on URL/health-check step is shown, in `cremalink-ha/tests/test_config_flow.py`
- [X] T009 [US1] Test that `async_setup_entry` starts an `EmbeddedLocalServer` for a new-style local-mode entry and the coordinator receives monitor data, in `cremalink-ha/tests/test_init.py`

### Implementation for User Story 1

- [X] T010 [US1] Remove the add-on-URL entry/health-check step from the manual local setup path (`async_step_local`/`async_step_device`) in `cremalink-ha/custom_components/cremalink_ha/config_flow.py` so DSN/device IP/LAN key are collected directly, writing the new embedded-mode connection marker (depends on T001). **Note**: `async_step_local` was removed entirely; `async_step_choose_connection`'s "local" option now routes straight to `async_step_device`.
- [X] T011 [US1] Update `_async_complete_cloud_entry` (cloud-assisted onboarding path from `001-cloud-assisted-onboarding`) to create local entries with the embedded-mode marker instead of `CONF_ADDON_URL`, in `cremalink-ha/custom_components/cremalink_ha/config_flow.py` (depends on T010)
- [X] T012 [US1] In `async_setup_entry`, for embedded-mode local entries, construct and `await handle.start()` an `EmbeddedLocalServer` (dsn/device_ip/lan_key/device_map from `entry.data`), storing the handle in `hass.data[DOMAIN][entry.entry_id]`, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T006)
- [X] T013 [US1] Point the `CONNECTION_LOCAL` branch's existing `create_local_device(...)` call at `server_host="127.0.0.1", server_port=handle.bound_port` instead of parsing `CONF_ADDON_URL`, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T012)

**Checkpoint**: User Story 1 is independently testable — a brand-new local-mode entry works with zero add-on installed.

---

## Phase 4: User Story 2 - Embedded server lifecycle matches the config entry (Priority: P1) 🎯 MVP (part 2 of 2)

**Goal**: The embedded server starts/stops exactly in step with its config entry's setup/unload/reload/removal/HA-shutdown, with full isolation between simultaneously loaded entries.

**Independent Test**: Add, reload, and then remove a local-mode config entry, verifying (via port-bind checks or task inspection) that the embedded server's listening socket and background tasks are gone after each unload/removal.

### Tests for User Story 2

- [X] T014 [P] [US2] Test that unloading/removing a local-mode entry stops its `EmbeddedLocalServer` and immediately releases the port, in `cremalink-ha/tests/test_init.py`
- [X] T015 [P] [US2] Test that reloading an entry stops the old embedded server before the new one starts, with no leftover listening socket, in `cremalink-ha/tests/test_init.py`
- [X] T016 [US2] Test that two simultaneously loaded local-mode entries run fully independent embedded servers/state on distinct ports, in `cremalink-ha/tests/test_init.py`

### Implementation for User Story 2

- [X] T017 [US2] Register `entry.async_on_unload(handle.stop)` in `async_setup_entry` so unload/reload/removal/HA-shutdown always stop the embedded server, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T012)
- [X] T018 [US2] Ensure `async_unload_entry` awaits full teardown and pops the entry's handle from `hass.data`, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T017)
- [X] T019 [US2] Ensure `EmbeddedLocalServer` never reads the process-global `local_server_app.config.get_settings()` `lru_cache` singleton — always construct a fresh per-instance `ServerSettings` — so simultaneously running instances cannot share port/state, in `cremalink/cremalink/local_server_app/embedded.py` (depends on T003)

**Checkpoint**: User Stories 1 AND 2 together deliver the MVP — embedded local mode works end-to-end with correct lifecycle and per-entry isolation.

---

## Phase 5: User Story 3 - Existing add-on-based entries are reconfigured after upgrade (Priority: P2)

**Goal**: Legacy add-on-based local entries are never silently switched to embedded mode; users are clearly prompted (via a Home Assistant repair) to complete an explicit, pre-filled reconfigure step.

**Independent Test**: Take a pre-existing add-on-based config entry, upgrade the integration, and confirm the user is presented with a clear reconfigure step (pre-filled where possible) that results in a working embedded-mode entry once completed.

### Tests for User Story 3

- [X] T020 [P] [US3] Test that a legacy entry (has `CONF_ADDON_URL`) does not auto-start an embedded server on setup and that a repair issue is created instead, in `cremalink-ha/tests/test_init.py`
- [X] T021 [P] [US3] Test that the reconfigure flow pre-fills DSN/device name/device map from the legacy entry and accepts an optional `advertised_ip` override, in `cremalink-ha/tests/test_config_flow_reconfigure.py`
- [X] T022 [US3] Test that completing the reconfigure flow rewrites `entry.data` to the embedded-mode shape, deletes the repair issue, and results in a running `EmbeddedLocalServer`, in `cremalink-ha/tests/test_config_flow_reconfigure.py`
- [X] T023 [US3] Test that dismissing/cancelling the reconfigure flow leaves the entry flagged and the repair issue open, in `cremalink-ha/tests/test_config_flow_reconfigure.py`

### Implementation for User Story 3

- [X] T024 [US3] Implement a legacy-entry detection helper (`CONF_ADDON_URL` present / embedded-mode marker absent) in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T001)
- [X] T025 [US3] In `async_setup_entry`, for legacy local-mode entries, skip embedded-server start and call `issue_registry.async_create_issue(...)`, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T024). **Note**: created with `is_fixable=False` (informational) rather than `is_fixable=True` — the fix path is the entry's native "Reconfigure" UI action (`async_step_reconfigure`), which doesn't require a `repairs.py` fix-flow to be reachable.
- [X] T026 [US3] Implement `async_step_reconfigure` in `cremalink-ha/custom_components/cremalink_ha/config_flow.py`: pre-fill DSN/device name/device map from the existing entry, collect an optional `advertised_ip` override, and rewrite/reload the entry (depends on T024, T002). **Note**: implemented via `hass.config_entries.async_update_entry(...)` + `async_reload(...)` + `async_abort(reason="reconfigure_successful")` rather than the `async_update_reload_and_abort(...)` convenience helper, for straightforward testability against the existing mocked-`hass` test harness; behavior is equivalent.
- [X] T027 [US3] On successful reconfigure, delete the corresponding repair issue (`issue_registry.async_delete_issue`), in `cremalink-ha/custom_components/cremalink_ha/config_flow.py` (depends on T026)
- [X] T028 [US3] Pass the reconfigure flow's `advertised_ip` override through to the `EmbeddedLocalServer` constructor on (re)load, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T026, T012)

**Checkpoint**: Legacy add-on users have a clear, explicit path off the add-on with no silent data reuse.

---

## Phase 6: User Story 4 - Port conflicts are handled automatically (Priority: P3)

**Goal**: A busy default port never fails setup — the embedded server automatically falls back to another free port, visibly.

**Independent Test**: Occupy the default port with a dummy listener, then add a local-mode config entry and confirm it starts successfully on an alternate port, with the chosen port visible in logs/diagnostics.

### Tests for User Story 4

- [X] T029 [P] [US4] Test that occupying the default port with a dummy listener before `start()` results in binding to a fallback port, with `bound_port` reflecting it, in `cremalink/tests/test_embedded_server.py`
- [X] T030 [US4] Test that exhausting the fallback range raises a clear error rather than hanging, in `cremalink/tests/test_embedded_server.py`
- [X] T031 [US4] Test that `bound_port`/`advertised_ip` are visible in `cremalink_ha` diagnostics output after a fallback occurred, in `cremalink-ha/tests/test_diagnostics.py`

### Implementation for User Story 4

- [X] T032 [US4] Extend `EmbeddedLocalServer.start()`'s bind logic with a bounded retry loop (increment port on `OSError`/`EADDRINUSE` up to `port_fallback_range`), logging a warning naming the conflict and the chosen fallback port, in `cremalink/cremalink/local_server_app/embedded.py` (depends on T003). **Note**: already implemented as part of T003 (see note there).
- [X] T033 [US4] Surface `bound_port` and `advertised_ip` in diagnostics output, in `cremalink-ha/custom_components/cremalink_ha/diagnostics.py` (depends on T032)
- [X] T034 [US4] Translate a `start()` failure (fallback range exhausted) into `ConfigEntryNotReady` with a clear message in `async_setup_entry`, in `cremalink-ha/custom_components/cremalink_ha/__init__.py` (depends on T032). **Note**: handled by the existing generic `except Exception as e: ... raise ConfigEntryNotReady(...)` wrapper around the embedded-mode setup path in `async_setup_entry`, which already catches `EmbeddedLocalServer.start()`'s `OSError` on range exhaustion — no separate branch needed.

**Checkpoint**: All four user stories are independently functional; port conflicts no longer block setup.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and release bookkeeping affecting multiple user stories

- [X] T035 [P] Update `cremalink-ha/README.md` to describe embedded local mode as the default (no add-on required) and document the reconfigure step for upgrading users
- [X] T036 [P] Add a deprecation note to `cremalink-ha/addons/cremalink-server/README.md` and `cremalink-ha/addons/cremalink-server/config.yaml` describing the add-on as no longer required by `cremalink_ha`
- [X] T037 [P] Bump `cremalink-ha` version (`custom_components/cremalink_ha/manifest.json` and `pyproject.toml`) per repo convention — bumped `v0.2.0b1` → `v0.3.0b1`
- [X] T038 Run `quickstart.md` validation end-to-end and confirm SC-001 through SC-005 all hold — full suites green: `cremalink` 35/35, `cremalink-ha` 23/23

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion. BLOCKS all user stories.
- **User Stories (Phase 3-6)**: All depend on Foundational completion.
  - US1 (P1) and US2 (P1) can be worked in parallel by different people once Foundational is done, but US2's lifecycle tasks (T017-T018) depend on US1's `async_setup_entry` wiring (T012) existing first.
  - US3 (P2) depends on US1's `async_setup_entry`/`config_flow.py` structure (T010, T012) existing, since the reconfigure flow reuses the same entry-creation code paths.
  - US4 (P3) only depends on Foundational (T003) — it extends `EmbeddedLocalServer.start()` directly and can be implemented in parallel with US2/US3 once Foundational is done.
- **Polish (Phase 7)**: Depends on all user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational. Independently testable with the embedded-server protocol behavior alone (T007) and config-flow behavior alone (T008).
- **User Story 2 (P1)**: Can start after Foundational; its lifecycle wiring (T017-T018) builds on US1's `async_setup_entry` change (T012). Independently testable via port-release/reload/multi-entry tests.
- **User Story 3 (P2)**: Depends on US1 (T010, T012) for the entry-creation code paths it reuses; adds the reconfigure branch.
- **User Story 4 (P3)**: Depends only on Foundational (T003); hardens `start()` with fallback logic usable by every story.

### Within Each User Story

- Tests are written before their corresponding implementation task where both exist.
- Library changes (`cremalink/`) before the `cremalink_ha` wiring that consumes them.
- Story checkpoint reached only once both its tests and implementation tasks are done.

### Parallel Opportunities

- All Phase 1 (Setup) tasks — T001-T002 — touch different files and can run in parallel.
- T007 and T008 in Phase 3 (US1) touch different files/repos and can run in parallel.
- T014 and T015 in Phase 4 (US2) touch the same test file but different, independent test cases — treat as parallel-safe for authoring, sequential for execution if the test runner requires it.
- T020 and T021 in Phase 5 (US3) touch different files and can run in parallel.
- T029 in Phase 6 (US4) can be drafted in parallel with US2/US3 test work once Foundational (T003) is done.

---

## Parallel Example: User Story 1

```text
# After Foundational (Phase 2) is done, these can run together:
T007 [P] [US1] Embedded server protocol round-trip test — cremalink/tests/test_embedded_server.py
T008 [P] [US1] No addon_url in new local entries test — cremalink-ha/tests/test_config_flow.py

# Then sequentially (all touch config_flow.py / __init__.py):
T010 → T011 → T012 → T013
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 together)

Per spec.md's own framing, US1 and US2 are both P1 and jointly form the
minimum viable slice: embedded local mode that actually works end-to-end
(US1) with correct, leak-free lifecycle (US2). Ship Phases 1-4 first; this
alone eliminates the add-on requirement for new setups.

### Incremental Delivery

1. Phases 1-4 (Setup, Foundational, US1, US2) → MVP: brand-new local-mode
   setups run entirely embedded, with correct start/stop/reload/isolation.
2. Phase 5 (US3) → gives existing add-on users an explicit, safe path off
   the add-on.
3. Phase 6 (US4) → adds automatic port-conflict resilience, completing the
   spec's Success Criteria.
4. Phase 7 (Polish) → documentation, add-on deprecation notices, version
   bump, and final quickstart validation.
