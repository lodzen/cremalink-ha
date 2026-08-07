---

description: "Task list template for feature implementation"
---

# Tasks: Cloud-Assisted Device Onboarding

**Input**: Design documents from `/specs/001-cloud-assisted-onboarding/`

**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (required for user stories), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. The design docs (`research.md` #8, `quickstart.md`) already name specific test files (`test_cloud_client.py`, `test_model_detection.py`, `test_config_flow.py`) as part of the validation strategy, so test tasks are generated alongside implementation tasks.

**Organization**: Tasks are grouped by user story (from spec.md, priority order) to enable independent implementation and testing of each story. Per spec.md's own "Why this priority" notes, these four stories form a sequential pipeline (login/discovery → model detection → LAN discovery → cloud fallback) rather than fully parallel slices — this is called out explicitly in Dependencies & Execution Order below.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Multi-repo, library-first layout (per plan.md Project Structure — not the
single-project/web-app/mobile options below):

- `cremalink/cremalink/` — shared library (clients, domain) + `cremalink/tests/`
- `cremalink-ha/custom_components/cremalink_ha/` — HA integration + `cremalink-ha/tests/` (new)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffolding needed before any shared library or config-flow code changes

- [X] T001 [P] Create `cremalink-ha/requirements_test.txt` (pytest>=9.0.3, pytest-cov, voluptuous, cryptography) mirroring `delonghi-ha/requirements_test.txt`
- [X] T002 [P] Create `cremalink-ha/tests/__init__.py` and `cremalink-ha/tests/conftest.py`, porting the `unittest.mock` Home Assistant module-stubbing pattern from `delonghi-ha/tests/conftest.py` (research.md #8)
- [X] T003 [P] Add new config-flow constants (`CONF_EMAIL`, `CONF_PASSWORD`, `STEP_DEVICE_SELECT`, `STEP_MANUAL_MAP`, `STEP_MANUAL`) to `cremalink-ha/custom_components/cremalink_ha/const.py`
- [X] T004 [P] Add new translation strings/errors (email/password labels, `auth_failed`, `no_devices`, `no_coffee_machine`, "advanced setup" link label) to `cremalink-ha/custom_components/cremalink_ha/strings.json`

**Checkpoint**: Test scaffolding and constants exist; ready for Foundational library work.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared library primitives every user story calls into

**⚠️ CRITICAL**: No user story work should begin until this phase is complete

- [X] T005 Implement bounded-retry helper (ported from `delonghi_coffee`'s `_retry`/`RETRY_COUNT`/`RETRY_DELAY`) in `cremalink/cremalink/clients/cloud.py` (research.md #5, FR-014)
- [X] T006 Implement `is_coffee_device()` classifier (ported from `delonghi_coffee`'s `is_coffee_oem_model`) in `cremalink/cremalink/clients/cloud.py` (depends on T005 same file) (FR-002)
- [X] T007 Implement `Client.list_account_devices()` in `cremalink/cremalink/clients/cloud.py`, using the retry helper and classifier, returning enriched dicts per [contracts/cremalink-library-api.md](contracts/cremalink-library-api.md) (depends on T005, T006) (FR-002, FR-003)
- [X] T008 [P] Create `cremalink/cremalink/domain/model_detection.py` with `detect_model_id()` 4-tier precedence skeleton (plaintext serial → binary SKU → cloud metadata → OEM table), lookup tables intentionally empty so it safely returns `None` (fail-closed) until Phase 4 populates them (data-model.md `ModelDetectionResult`, FR-004, FR-005)
- [X] T009 [P] Create `cremalink-ha/custom_components/cremalink_ha/diagnostics.py` with `REDACT_KEYS` covering `email`, `password`, `access_token`, `refresh_token`, `lan_key`, `device_ip`, ported from `delonghi_coffee`'s `diagnostics.py` (FR-013)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Cloud login replaces manual device-map and DSN entry (Priority: P1) 🎯 MVP (part 1 of 2 — see US2)

**Goal**: Users sign in with cloud email/password instead of picking a device map and typing a DSN; the integration discovers, and (if more than one) lets the user choose, their coffee machine(s).

**Independent Test**: Run the config flow with valid cloud credentials for a single-coffee-machine account fixture (with `detect_model_id()` stubbed to a known device-map id) and verify a config entry is created without a device-map or DSN prompt.

### Tests for User Story 1

- [X] T010 [P] [US1] `list_account_devices()` returns only coffee devices, single- and multi-device fixtures, in `cremalink/tests/test_cloud_client.py`
- [X] T011 [P] [US1] Single-device account creates entry with no map/DSN prompt (detection stubbed) in `cremalink-ha/tests/test_config_flow.py`
- [X] T012 [US1] Multi-device account shows `device_select` step listing friendly names + DSNs in `cremalink-ha/tests/test_config_flow.py`
- [X] T013 [US1] Invalid credentials show `auth_failed` and allow retry in `cremalink-ha/tests/test_config_flow.py`
- [X] T014 [US1] Zero coffee devices show `no_coffee_machine`, no entry created, in `cremalink-ha/tests/test_config_flow.py`
- [X] T015 [US1] "Advanced setup" link routes to `async_step_manual` unchanged, in `cremalink-ha/tests/test_config_flow.py`

### Implementation for User Story 1

- [X] T016 [US1] Rename existing `async_step_user` → `async_step_manual` in `cremalink-ha/custom_components/cremalink_ha/config_flow.py`, preserving all existing behavior verbatim (FR-010)
- [X] T017 [US1] Implement new `async_step_user` as the cloud-login step (email + password; region fixed to `"EU"`), calling `authenticate_cloud()` and `Client.list_account_devices()` via `hass.async_add_executor_job` (depends on T007, T016) (FR-001, FR-002, FR-012)
- [X] T018 [US1] Add an "advanced setup" menu option from `async_step_user` to `async_step_manual` (depends on T017) (FR-010) — implemented as a checkbox on the login form rather than a separate link, per the same "same first screen" requirement
- [X] T019 [US1] Implement `async_step_device_select`, shown only when more than one coffee device is discovered (depends on T017) (FR-003)
- [X] T020 [US1] Wire the selected/only device into a `detect_model_id()` call and config-entry creation, with `async_set_unique_id(dsn)` + `_abort_if_unique_id_configured()` (depends on T008, T019) (FR-005 partial, FR-011)
- [X] T021 [US1] Add `auth_failed`/`no_devices`/`no_coffee_machine` error handling to `async_step_user`, using the T004 strings (depends on T017)

**Checkpoint**: User Story 1 is independently testable (with model detection stubbed) — a config entry is created automatically for a known-model fixture, with no manual DSN/device-map entry.

---

## Phase 4: User Story 2 - Automatic model detection selects the right device map (Priority: P1) 🎯 MVP (part 2 of 2)

**Goal**: The device discovered in US1 is automatically matched to the correct existing device map, using the same precedence order proven in `delonghi_coffee`, with a safe in-flow manual fallback when detection is inconclusive.

**Independent Test**: Feed `detect_model_id()` known plaintext-serial, binary-serial-SKU, cloud-metadata, and OEM-only fixtures and confirm each resolves to the expected device-map id, and that an unrecognized identifier resolves to `None` (never a guess) and routes the config flow to the manual fallback picker.

### Tests for User Story 2

- [X] T022 [P] [US2] Plaintext-serial match resolves the expected `device_map_id` in `cremalink/tests/test_model_detection.py`
- [X] T023 [US2] Binary-serial → SKU lookup resolves the expected `device_map_id` in `cremalink/tests/test_model_detection.py`
- [X] T024 [US2] Cloud-metadata fallback resolves the expected `device_map_id` in `cremalink/tests/test_model_detection.py`
- [X] T025 [US2] OEM-table fallback resolves the expected `device_map_id` in `cremalink/tests/test_model_detection.py`
- [X] T026 [US2] Unrecognized identifier returns `None` (never a guessed/default map) in `cremalink/tests/test_model_detection.py`
- [X] T027 [P] [US2] Unresolved model routes to `manual_map` step, pre-filled with DSN/friendly name/LAN details, in `cremalink-ha/tests/test_config_flow.py`

### Implementation for User Story 2

- [X] T028 [US2] Port the binary-serial decode helper (from `delonghi_coffee`'s `DeLonghiApi.parse_serial_number`) into `cremalink/cremalink/domain/model_detection.py` (depends on T008)
- [X] T029 [US2] Populate and verify the OEM-identifier → `device_map_id` table (`ECAM452`, `ECAM612`) in `cremalink/cremalink/domain/model_detection.py` against confirmed hardware/serial samples — flagged as unverified in research.md #3; do **not** fabricate values (depends on T028). Resolved: `DL-pd-soul`/`DL-millcore` → `ECAM612`, sourced from `delonghi_coffee`'s confirmed `OEM_TO_APP_MODEL` (issue #10 hardware) and corroborated by `ECAM612.json`'s own `device_type`/`espresso_soul` command.
- [X] T030 [US2] Populate and verify the SKU → `device_map_id` table (`ECAM452`, `ECAM612`) in `cremalink/cremalink/domain/model_detection.py`, same verification caveat as T029 (depends on T028). Resolved: SKU `217055` → `ECAM612`, verified against a real decoded serial sample (base64 `0BuhDwDNMjE3MDU1WloyNTA3MDEzMDEzNAD9pg==`) provided during implementation; covered by `test_binary_serial_sku_resolves_real_soul_sample`.
- [X] T031 [P] [US2] Implement `async_step_manual_map` fallback step (pre-filled DSN/friendly name/LAN details, reusing the existing device-map picker) in `cremalink-ha/custom_components/cremalink_ha/config_flow.py` (depends on T020) (FR-005)

**Checkpoint**: User Stories 1 + 2 together deliver the MVP — cloud login always resolves to a correct device map or a safe manual fallback, never a wrong guess.

---

## Phase 5: User Story 3 - Automatic LAN detail discovery for local connection (Priority: P2)

**Goal**: When the resolved device map supports local mode and the account reports the machine as LAN-enabled, fetch the LAN key/IP automatically and offer a local connection.

**Independent Test**: Use a discovered device fixture whose cloud record reports LAN-enabled with a known LAN key/IP, and verify the resulting config entry is created in local connection mode with those values populated automatically.

### Tests for User Story 3

- [X] T032 [P] [US3] `get_lan_config()` returns `lan_key`/`lan_ip` for a LAN-enabled fixture in `cremalink/tests/test_cloud_client.py`
- [X] T033 [P] [US3] LAN-enabled + local-supported device map creates a local-connection entry with auto-fetched key/IP in `cremalink-ha/tests/test_config_flow.py`

### Implementation for User Story 3

- [X] T034 [P] [US3] Implement `Client.get_lan_config(dsn)` in `cremalink/cremalink/clients/cloud.py`, ported from `delonghi_coffee`'s `api.get_lan_config` (depends on T005) (FR-006)
- [X] T035 [US3] Wire `get_lan_config()` after model resolution and complete setup as a local connection when `lan_enabled` and the device map's `support.local` is true (depends on T031, T034) (FR-007)

**Checkpoint**: User Stories 1–3 deliver full automatic local-connection setup.

---

## Phase 6: User Story 4 - Graceful cloud-only fallback when LAN details are unavailable (Priority: P3)

**Goal**: When LAN details are unavailable, disabled, or the lookup fails, complete setup as a cloud connection automatically instead of blocking or erroring.

**Independent Test**: Use a discovered device fixture reported as not LAN-enabled (and, separately, one where the LAN lookup fails/times out) and verify the config entry is still created successfully in cloud connection mode.

### Tests for User Story 4

- [X] T036 [P] [US4] LAN-disabled device fixture completes as a cloud connection automatically, no LAN prompt, in `cremalink-ha/tests/test_config_flow.py`
- [X] T037 [P] [US4] `get_lan_config()` retries a bounded number of times on a simulated transient failure, then the flow falls back to cloud, in `cremalink/tests/test_cloud_client.py`

### Implementation for User Story 4

- [X] T038 [US4] Add the cloud-connection completion branch (else of US3's local branch) using the existing `CONF_TOKEN_FILE` pattern in `cremalink-ha/custom_components/cremalink_ha/config_flow.py` (depends on T035) (FR-008)
- [X] T039 [P] [US4] Apply the T005 retry helper to `list_account_devices()` and `get_lan_config()` with explicit timeouts on every call (depends on T007, T034) (FR-014)

**Checkpoint**: All four user stories are independently functional; the full pipeline satisfies spec.md's Success Criteria.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that span multiple user stories

- [X] T040 [P] Update `cremalink-ha/README.md` installation/configuration section to describe the new cloud-login-first onboarding flow and the "advanced setup" link
- [X] T041 [P] Add diagnostics redaction test (`email`/`password`/tokens/`lan_key` never appear) in `cremalink-ha/tests/test_diagnostics.py` (FR-013)
- [X] T042 Run [quickstart.md](quickstart.md) validation end-to-end: library tests, config-flow tests, and the manual walkthrough against spec.md's Success Criteria (SC-001..SC-005) — automated portions (`cremalink/tests/`, `cremalink-ha/tests/`) run green (36/36); the manual real-account walkthrough (quickstart.md step 3) still requires a live cloud account and is not part of this automated pass
- [ ] T043 Bump `cremalink` and `cremalink-ha` versions and update changelog entries per existing release conventions — T029/T030 are now resolved (ECAM612 verified); still deferred only because a version bump/release wasn't requested as part of this implementation pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories.
- **User Stories (Phase 3–6)**: Depend on Foundational completion. Unlike a typical fully-parallel story set, these four stories form a **sequential pipeline** by design (per spec.md's own "Why this priority" notes): US2 makes US1 safe, US3 builds on US1+US2, US4 builds on US1–US3. Implement in listed order.
- **Polish (Phase 7)**: Depends on all four user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational. Independently testable with model detection stubbed.
- **User Story 2 (P1)**: Can start after Foundational; needed for US1's "correct device map" guarantee to be real rather than stubbed. Independently testable via `cremalink/tests/test_model_detection.py` fixtures alone.
- **User Story 3 (P2)**: Depends on US1 (device selection) and US2 (`async_step_manual_map`/resolved model) existing; adds the local-connection branch.
- **User Story 4 (P3)**: Depends on US3 (adds the `else` branch of the same completion decision) and hardens US1's discovery call with retry.

### Within Each User Story

- Tests are written before their corresponding implementation task where both exist.
- Library changes (`cremalink/`) before the `cremalink_ha` config-flow wiring that consumes them.
- Story checkpoint reached only once both its tests and implementation tasks are done.

### Parallel Opportunities

- All Phase 1 (Setup) tasks — T001–T004 — touch different files and can run in parallel.
- T008 and T009 in Phase 2 (Foundational) touch different files and can run in parallel with each other (but not with T005–T007, which share `cloud.py`).
- Within a story, tasks marked `[P]` above touch different files than other tasks active at the same time; tasks without `[P]` share a file with a preceding task in the same story and must be done in order.
- Across stories, US3's and US4's test tasks can be drafted in parallel with US1/US2 implementation once Foundational is done, since they target different files — but their *implementation* tasks have real dependencies on earlier stories (see above) and should not be started early.

---

## Parallel Example: User Story 1

```text
# After Foundational (Phase 2) is done, these can run together:
T010 [P] [US1] list_account_devices() coffee-filter test — cremalink/tests/test_cloud_client.py
T011 [P] [US1] Single-device entry-creation test (detection stubbed) — cremalink-ha/tests/test_config_flow.py

# Then sequentially (all touch config_flow.py):
T016 → T017 → T018 → T019 → T020 → T021
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 together)

Per spec.md's own framing, US1 and US2 are both P1 and jointly form the
minimum viable slice: cloud login that **always** resolves to either a
correct device map or a safe manual fallback — never a guess. Ship Phases
1–4 first; this alone eliminates manual DSN/device-map entry for the
happy path.

### Incremental Delivery

1. Phases 1–4 (Setup, Foundational, US1, US2) → MVP: cloud-assisted
   onboarding with correct or safely-deferred model selection.
2. Phase 5 (US3) → adds automatic local-connection setup on top of the MVP.
3. Phase 6 (US4) → adds resilience (retry) and explicit cloud fallback when
   LAN isn't available, completing the spec's Success Criteria.
4. Phase 7 (Polish) → documentation, diagnostics test coverage, release
   bookkeeping, and final quickstart validation.
