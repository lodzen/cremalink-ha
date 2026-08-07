# Quickstart: Validating Cloud-Assisted Device Onboarding

This guide describes how to manually and automatically validate this
feature end-to-end. It links to [data-model.md](data-model.md) and
[contracts/](contracts/) rather than repeating field/step details.

## Prerequisites

- Python >= 3.13 with `cremalink`'s dev extras installed:
  `pip install -e "cremalink[dev]"` (from `cremalink/`).
- A running Home Assistant dev instance with `cremalink-ha`'s
  `custom_components/cremalink_ha` symlinked/copied into
  `config/custom_components/`.
- For full end-to-end (not just unit-level) validation: a real or test
  De'Longhi Comfort2 cloud account (email/password) with at least one
  registered coffee machine. Unit/integration tests below do not require
  this — they use fixtures/mocked HTTP responses.

## 1. Library-level validation (`cremalink`)

```bash
cd cremalink
pip install -e ".[dev]"
pytest tests/test_cloud_client.py tests/test_model_detection.py -v
```

Expected outcomes (see [contracts/cremalink-library-api.md](contracts/cremalink-library-api.md)):
- `list_account_devices()` returns only entries with `is_coffee_device:
  true`, each including `dsn`, `product_name`, `oem_model`, `lan_enabled`.
- `get_lan_config(dsn)` returns `lan_enabled: false` (not an exception) for
  a device fixture with LAN disabled.
- `detect_model_id(...)` resolves known plaintext-serial, binary-serial-SKU,
  cloud-metadata, and OEM-table fixtures to the expected `device_map_id`,
  and returns `None` for an unrecognized identifier (never a guessed id).
- A simulated transient failure (mocked timeout/5xx) on
  `list_account_devices()`/`get_lan_config()` is retried a bounded number
  of times before raising.

## 2. Config-flow validation (`cremalink_ha`)

```bash
cd cremalink-ha
pip install -r requirements_test.txt  # add if not already present, mirroring delonghi-ha
pytest tests/test_config_flow.py -v
```

Expected outcomes (see [contracts/config-flow-steps.md](contracts/config-flow-steps.md)):
- Submitting valid email/password with a single-coffee-device account fixture
  creates a config entry without a device-map or DSN prompt.
- A multi-device account fixture shows the device-select step listing
  friendly names + DSNs.
- An account fixture with zero coffee devices surfaces the
  `no_coffee_machine` error and creates no entry.
- An unresolved-model device fixture is routed to the `manual_map` step,
  pre-filled with the discovered DSN/friendly name/LAN details.
- A LAN-disabled device fixture completes as a cloud connection
  automatically, with no LAN prompt.
- Choosing "advanced setup" from the login step reaches the existing
  device-map-picker flow unchanged.
- `async_get_config_entry_diagnostics()` output has `email`, `password`,
  `access_token`, `refresh_token`, and `lan_key` redacted.

## 3. Manual end-to-end validation (optional, requires a real account)

1. Start Home Assistant with `cremalink_ha` installed; begin **Add
   Integration → Cremalink**.
2. Enter the cloud account email/password on the new first step.
3. Confirm the device list (or automatic single-device continuation) shows
   the correct friendly name(s) and no DSN entry field.
4. Confirm the resulting config entry uses the correct device map (compare
   entity availability/behavior against the machine's known model).
5. If the machine is LAN-enabled and its device map supports local mode,
   confirm the entry was created as a **local** connection (check the
   Cremalink Server add-on logs for a local handshake) without ever being
   asked for the LAN key.
6. Download diagnostics for the new entry from **Settings → Devices &
   Services → Cremalink → ⋮ → Download diagnostics** and confirm no
   plaintext email, password, tokens, or LAN key appear.
7. From the login step, choose "advanced setup" and confirm the previous
   manual flow (device map → DSN/LAN key/IP or refresh token) still works
   unchanged.

## Success criteria mapping

See [spec.md](spec.md) Success Criteria (SC-001..SC-005) — steps 3–7 above
directly exercise SC-001 (time budget), SC-002/SC-003 (correct/never-wrong
device map), SC-004 (manual path regression-free), and SC-005 (cloud
fallback when LAN unavailable).
