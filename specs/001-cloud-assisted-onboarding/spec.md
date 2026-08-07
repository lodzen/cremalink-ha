# Feature Specification: Cloud-Assisted Device Onboarding

**Feature Branch**: `[001-cloud-assisted-onboarding]`

**Created**: 2026-08-07

**Status**: Draft

**Input**: User description: "i want to extend the existing homeassitant integration in the custom_components/cremalink_ha folder (which is part of an local addon in the folder cremalink) with the logic of the delonghi-ha/custom_components/delonghi_coffee integration. The overall goal is to takeover the cloud login flow with the different region support from delonghi_coffee and to fetch the needed information to connect to the machine automatically like Friendly name, DSN, lan key and other needed informations. The delonghi_coffee integration also created a automated model mapping including a decoding of the serialnumber _detect_contentstack_pattern to select the correct schema (part of the const.py file). this logic should also be used in the cremalink_ha integration to select the device_map"

## Clarifications

### Session 2026-08-07

- Q: Should the new cloud-login option replace the existing first config-flow step (device-map picker), or be offered as an additional entry-point choice alongside it? → A: Replace the first step entirely with cloud login; manual device-map/DSN entry moves to an "advanced"/secondary path reached via a link or option on the login screen.
- Q: When automatic model detection can't identify a device at all, should the flow let the user fall back to picking a device map manually right there, or must they abandon and restart via the separate manual setup path? → A: Offer an in-flow manual device-map picker as a fallback step, pre-filled with the DSN/friendly name/LAN details already discovered from the cloud.
- Q: Should this feature also add a diagnostics-redaction mechanism to `cremalink_ha` for the new sensitive fields (cloud email, password-derived tokens, LAN key), or is that explicitly out of scope? → A: In scope — add/extend diagnostics redaction (matching `delonghi_coffee`'s `REDACT_KEYS` pattern) to cover the new cloud email, tokens, and LAN key fields.
- Q: When a cloud API call for device discovery or LAN-detail lookup hits a transient failure (timeout, 5xx), should the flow automatically retry a bounded number of times before showing an error, or fail immediately and let the user manually resubmit the step? → A: Automatically retry a small bounded number of times (matching existing library retry conventions) before surfacing an error.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cloud login replaces manual device-map and DSN entry (Priority: P1)

A user setting up Cremalink for the first time is greeted by a cloud login
screen (email, password, region) as the new first step of the config flow,
replacing today's device-map picker as the default entry point. They sign in
instead of picking a device map from a list and typing in a DSN by hand. The
integration signs in, lists the coffee machines on that account (ignoring
unrelated appliances), lets the user pick one if there's more than one,
automatically figures out the exact model, and creates the config entry with
the correct device map already applied. Users who want the previous manual
flow (explicit device-map selection plus manual DSN/LAN-key/IP or
refresh-token entry) reach it via an "advanced"/"manual setup" link or option
presented on the same first screen.

**Why this priority**: This removes the single biggest source of setup
friction and user error today — manually finding and typing a DSN and
guessing which device map matches the machine. Without this, none of the
other automation (LAN auto-discovery, model detection) has anywhere to plug
into the config flow.

**Independent Test**: Can be fully tested by running through config flow with
valid cloud credentials for an account with exactly one supported coffee
machine and verifying a config entry is created with the correct device map,
without the user typing a DSN or picking a map from a dropdown.

**Acceptance Scenarios**:

1. **Given** a user has a valid cloud account with one supported coffee
   machine, **When** they enter their email, password, and region in the
   config flow, **Then** the integration signs in, discovers the device, and
   proceeds without asking the user to select a device map or type a DSN.
2. **Given** the cloud account has more than one coffee machine, **When**
   login succeeds, **Then** the user is shown a list of the machines by
   friendly name and DSN to choose which one to add.
3. **Given** the cloud account has no coffee machines (or none at all),
   **When** login succeeds, **Then** the config flow shows a clear error and
   does not create a config entry.
4. **Given** the entered credentials are invalid, **When** the user submits
   the login step, **Then** the config flow shows an authentication error and
   lets the user retry.
5. **Given** a user is on the new cloud-login first step, **When** they
   choose the "advanced"/"manual setup" option instead of signing in,
   **Then** they are taken to today's existing device-map picker and manual
   DSN/LAN-key/IP or refresh-token entry flow, unchanged.

---

### User Story 2 - Automatic model detection selects the right device map (Priority: P1)

For the device the user selects, the integration automatically determines
its exact model — using the same detection order proven in
`delonghi_coffee` (plaintext serial pattern, decoded binary serial SKU
lookup, cloud metadata fields, then a static OEM-to-model table) — and
resolves it to one of Cremalink's existing device maps, rather than making
the user pick a map from a dropdown.

**Why this priority**: Model detection is what makes User Story 1 safe:
without it, cloud login would still require the user to guess a device map,
which is the exact problem being solved. It also protects against silently
running a device with the wrong command schema.

**Independent Test**: Can be fully tested by feeding the detection routine
known serial numbers and OEM identifiers (plaintext, binary-encoded, and
OEM-only cases) from real fixtures and confirming each resolves to the
expected device map, and that an unrecognized identifier falls back to an
in-flow manual device-map picker (pre-filled with the discovered DSN,
friendly name, and LAN details) rather than ever auto-applying a guessed or
default map.

**Acceptance Scenarios**:

1. **Given** a device reports a plaintext model string in its serial number,
   **When** detection runs, **Then** the matching device map is selected.
2. **Given** a device only reports a binary-encoded serial number, **When**
   detection runs, **Then** the serial is decoded, its SKU is looked up, and
   the matching device map is selected.
3. **Given** neither serial form yields a match, **When** detection falls
   back to cloud metadata and then the static OEM table, **Then** the first
   method that yields a match determines the device map.
4. **Given** no detection method yields a recognized model, **When** the
   config flow reaches this step, **Then** the user is shown an in-flow
   manual device-map picker pre-filled with the DSN, friendly name, and any
   LAN details already discovered, and no config entry is created until
   they explicitly pick a map.

---

### User Story 3 - Automatic LAN detail discovery for local connection (Priority: P2)

After a device is identified, if its device map supports local connectivity
and the account reports the machine as LAN-enabled, the integration
automatically fetches the LAN key and local IP address from the cloud
account so the user can complete local setup (via the Cremalink Server
add-on) without looking up or typing those values manually.

**Why this priority**: Builds on Stories 1–2 by removing the second major
piece of manual technical data entry (LAN key, IP), but the integration is
still usable end-to-end (via cloud connection) without it.

**Independent Test**: Can be fully tested by using a discovered device whose
cloud record reports LAN-enabled with a known LAN key/IP, and verifying the
resulting config entry is created in local connection mode with those values
populated automatically, without user input.

**Acceptance Scenarios**:

1. **Given** a selected device supports local mode and is reported
   LAN-enabled with a LAN key and IP, **When** the user proceeds past model
   detection, **Then** the integration offers to complete setup locally
   using the auto-fetched LAN key and IP.
2. **Given** the device map does not support local mode at all, **When**
   the user proceeds, **Then** local setup is not offered and the flow
   continues with cloud connection only.

---

### User Story 4 - Graceful cloud-only fallback when LAN details are unavailable (Priority: P3)

If the account reports the device as not LAN-enabled, or the LAN details
cannot be fetched, the integration completes setup as a cloud connection
automatically instead of asking the user for LAN information it cannot
provide or erroring out.

**Why this priority**: Ensures the new cloud-assisted flow always reaches a
working end state even when local networking isn't available or supported,
so users aren't blocked by a missing add-on or LAN visibility.

**Independent Test**: Can be fully tested with a discovered device reported
as not LAN-enabled (or where the LAN lookup fails/times out) and verifying
the config entry is still created successfully in cloud connection mode.

**Acceptance Scenarios**:

1. **Given** a selected device is reported as not LAN-enabled, **When** the
   user proceeds past model detection, **Then** the flow completes as a
   cloud connection without prompting for LAN key or IP.
2. **Given** the LAN details lookup fails or times out, **When** the flow
   reaches this step, **Then** it falls back to cloud connection rather than
   failing the whole setup.

### Edge Cases

- What happens when the cloud account has appliances but none are coffee
  machines (e.g., only an unrelated appliance type)?
- How does the system handle a device that is already configured under an
  existing config entry (duplicate DSN)?
- How does the system handle a user attempting to select a cloud region for
  which the integration does not hold valid application credentials?
- What happens if cloud discovery succeeds but the automatic model
  detection and the automatic LAN lookup disagree on whether local mode is
  supported (e.g., device map allows local but the account never reports a
  LAN key)?
- How does the system handle transient cloud API failures during discovery
  or LAN-detail lookup (timeouts, 5xx responses)? The flow automatically
  retries a small bounded number of times before surfacing an error to the
  user, matching existing library retry conventions.
- What happens when a user has no cloud account at all and needs the
  existing manual (device-map + DSN/LAN-key/IP, or manual refresh-token)
  setup path?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow users to authenticate to the vendor cloud
  account using email and password directly in the Cremalink config flow,
  without requiring a pre-generated refresh token.
- **FR-002**: System MUST discover all appliances registered to the
  authenticated cloud account and filter the result down to coffee-machine
  devices only, excluding unrelated appliance types.
- **FR-003**: System MUST present each discovered coffee machine's friendly
  name (and DSN) so the user can identify and select which device to add
  when the account has more than one.
- **FR-004**: System MUST automatically determine each discovered device's
  model using, in order: (1) a plaintext model pattern parsed from the raw
  serial number, (2) a decoded binary-encoded serial number mapped via a
  SKU lookup table, (3) model/product-code metadata already present in the
  cloud device listing, (4) a static OEM-identifier-to-model mapping table.
- **FR-005**: System MUST resolve the detected model to one of Cremalink's
  existing device maps and MUST NOT automatically apply a guessed or
  default device map when detection is inconclusive. If no detection method
  yields a recognized model, the flow MUST present an in-flow manual
  device-map picker, pre-filled with the DSN, friendly name, and any LAN
  details already discovered from the cloud, and MUST NOT create a config
  entry until the user explicitly selects a map.
- **FR-006**: System MUST automatically fetch each selected device's LAN
  connectivity details (LAN-enabled flag, LAN key, local IP address) from
  the cloud account without requiring the user to type them in.
- **FR-007**: When LAN connectivity details are available and the resolved
  device map supports local mode, system MUST offer the user the option to
  complete setup as a local connection using the auto-fetched details.
- **FR-008**: When LAN connectivity details are unavailable, disabled, or
  the resolved device map does not support local mode, system MUST complete
  setup as a cloud connection automatically without requiring additional
  user input.
- **FR-009**: System MUST persist obtained cloud credentials/tokens using
  the same secure storage conventions as the existing cloud connection flow
  (not logged, not hardcoded, stored under the Home Assistant config
  directory).
- **FR-010**: System MUST continue to support the existing manual setup
  path — explicit device-map selection plus manual DSN/LAN-key/IP entry, or
  manual refresh-token entry — reachable via an "advanced"/"manual setup"
  link or option presented on the new cloud-login first step, for users
  without cloud account access or who prefer not to use cloud-assisted
  onboarding.
- **FR-011**: System MUST prevent duplicate config entries for the same
  physical device, keyed on DSN, consistent with existing behavior.
- **FR-012**: System MUST restrict cloud login to the region(s) for which
  the integration holds valid, already-obtained application credentials,
  and MUST show a clear, explicit error (never a silent guess or fabricated
  credential) if a user's account requires an unsupported region.
- **FR-013**: System MUST add diagnostics support to `cremalink_ha` that
  redacts newly-introduced sensitive fields (cloud account email, password,
  access/refresh tokens, LAN key) from any diagnostics export, following
  the same redaction pattern already used by `delonghi_coffee`.
- **FR-014**: System MUST automatically retry a small, bounded number of
  times on transient cloud API failures (timeouts, 5xx responses) during
  device discovery and LAN-detail lookup, matching existing library retry
  conventions, before surfacing an error to the user.

### Key Entities *(include if feature involves data)*

- **Cloud Account Session**: An authenticated cloud login for a given
  region, used to discover devices and fetch their connection details.
  Holds credentials/tokens only long enough to complete discovery, then
  hands off to the same secret storage used by the existing cloud flow.
- **Discovered Device**: A single appliance found on the cloud account —
  friendly name, DSN, detected model identifier, coffee-machine
  classification, and LAN connectivity details (enabled flag, LAN key,
  local IP) if available.
- **Device Map**: The existing JSON schema describing a supported coffee
  machine model's commands/capabilities (unchanged by this feature); the
  detected model is resolved to one of these, never invented ad hoc.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with valid cloud credentials can add a supported
  coffee machine without manually typing a DSN, LAN key, or picking a
  device map, completing setup in under 2 minutes.
- **SC-002**: Automatic model detection selects the correct device map for
  100% of previously-supported machine models when tested against known
  serial number and OEM identifier fixtures.
- **SC-003**: Zero config entries are ever created with an unresolved or
  incorrect device map — unmapped models always surface a clear error
  instead of a default or guessed mapping.
- **SC-004**: 100% of existing manual setup flows (device-map selection,
  manual DSN/LAN-key/IP entry, manual refresh-token entry) continue to work
  unchanged after this feature ships.
- **SC-005**: 100% of setups where LAN details are unavailable still
  complete successfully via automatic cloud fallback, with no user action
  required beyond the initial cloud login.

## Assumptions

- Initial rollout covers only the cloud region(s) for which the integration
  already holds valid application credentials (currently EU); additional
  regions can be added later without redesigning the login flow, once
  credentials for those regions are available. No new region credentials
  are fabricated or guessed as part of this feature.
- Model detection precedence and fallback tables are adapted from the
  equivalent logic already proven in `delonghi_coffee` (its OEM/SKU mapping
  tables and serial-decoding routine), re-targeted at Cremalink's own set
  of supported device maps rather than `delonghi_coffee`'s.
- Per the project constitution's Library-First and Cloud Auth & Discovery
  Reuse principles, this cloud-auth, discovery, and model-detection logic
  is implemented once in the shared `cremalink` library and consumed by
  `cremalink_ha`'s config flow only through the library's public
  interfaces — it is not embedded directly in the HA integration package.
- The existing manual device-map selection and manual local/cloud entry
  steps remain available as an alternative path; this feature adds a new
  cloud-assisted path alongside the current one rather than removing it.
- "Friendly name" refers to the product/display name already reported by
  the vendor cloud account for the device, not a user-assigned alias.
