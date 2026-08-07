# Contract: `cremalink` Library Public API Additions

This is the interface `cremalink_ha`'s config flow is allowed to depend on
(Principle I — Library-First Architecture). All new authentication,
discovery, LAN-lookup, and model-detection behavior is exposed here; no
region tables, serial-decoding logic, or OEM tables may be embedded directly
in `cremalink_ha`.

## `cremalink.clients.auth.authenticate_cloud(email, password, language="en") -> CloudToken`

*(Existing, unchanged.)* Used by the new config-flow login step exactly as
today's cloud-auth step already uses it: called via
`hass.async_add_executor_job`, result saved with `CloudToken.save(path)`.

## `cremalink.clients.cloud.Client`

### `Client.list_account_devices(self) -> list[dict]`

**New.** Returns one dict per appliance on the account:

```json
{
  "dsn": "AC000W123456789",
  "product_name": "PrimaDonna Soul",
  "oem_model": "DL-pd-soul",
  "raw_serial": "ECAM61075MB...",
  "is_coffee_device": true,
  "lan_enabled": true,
  "connection_status": "Online"
}
```

- MUST filter out non-coffee appliances (`is_coffee_device: false` entries
  are excluded from the returned list, not just flagged) — FR-002.
- MUST NOT change the existing `Client.get_devices()` method's signature or
  return type (`list[str]`) — backward compatibility for existing callers.
- Raises the same exception types as the existing `/devices.json` call path
  (`requests.RequestException` subtypes) on unrecoverable failure, after the
  bounded retry (see below) is exhausted.

### `Client.get_lan_config(self, dsn: str) -> dict`

**New.** Returns:

```json
{
  "lan_enabled": true,
  "lanip_key": "base64-or-hex-key",
  "lan_ip": "192.168.1.42",
  "status": "Online"
}
```

- MUST NOT raise on a device that simply has LAN disabled — returns
  `lan_enabled: false` with the other fields `None`/absent (FR-008).
- MUST apply the same bounded retry + explicit timeout as
  `list_account_devices()` (FR-014).

### Retry behavior (both methods above)

- Bounded automatic retry (small, fixed count — matching
  `delonghi_coffee`'s `RETRY_COUNT`/`RETRY_DELAY` constants) on transient
  failures (timeouts, 5xx) before raising to the caller (FR-014).
- Every underlying HTTP call sets an explicit timeout (constitution
  Principle VI).

## `cremalink.domain.model_detection`

### `detect_model_id(raw_serial: str | None, cloud_metadata: dict | None, oem_model: str | None) -> str | None`

**New.** Pure function, no I/O. Precedence (first match wins), per FR-004:

1. Plaintext model pattern parsed from `raw_serial`.
2. Decoded binary-encoded `raw_serial` → SKU lookup.
3. `cloud_metadata` product/model-code fields.
4. Static `oem_model` → device-map-id table.

- Returns a value that MUST be a valid `device_map()`/`load_device_map()`
  id, or `None` if no method matched (FR-005). Never returns a guessed or
  default id.
- Callers (the config flow) MUST treat `None` as "fall back to the in-flow
  manual device-map picker", never as "use a default map".

## `cremalink_ha` config-flow consumption rule

`config_flow.py` MAY call the functions/methods above (via executor jobs)
and MAY read their return values to decide which step to show next. It MUST
NOT re-implement any part of the precedence chain, region/app credentials,
or Ayla endpoint calls itself.
