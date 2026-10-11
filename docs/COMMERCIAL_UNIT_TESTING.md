# Testing a Tadiran / Gree commercial unit (cloud gateway)

This guide is for units such as the Tadiran *Slim Inverter SQ-240/1P*, which show up in the
Gree app as a gateway (for example `Commercial AC`) with one indoor unit behind it
(for example `Commercial ACf700`). Home Assistant reaches them only through the Gree
cloud (MQTT). The gateway MAC is the 12-character one, the indoor unit MAC is the same
plus two characters (for example `…00`).

## What changed in v0.1.9

- **Setup no longer fails with `Malformed response: cols=10 dat=9`.** The unit answers a
  request for several properties with fewer values than names. The values can't be matched
  to names safely in that case, so the integration now asks for those properties one at a time.
  Properties that still have no value are treated as unsupported. Nothing is guessed.
- **Device information (firmware, model) is optional.** If the unit doesn't answer it,
  setup continues without it.
- **Changes made in the Gree app or on the wall controller now show up in HA right away.**
  The unit already pushed status messages, but the integration only refreshed the screen
  without saving the new values.
- **HA shows only what the unit reports.** After a command the integration reads the state
  back, then checks again up to 3 times, 3 seconds apart, in case the gateway is still
  answering from its cache. If the unit never reports the new value, HA keeps showing the
  reported state and logs a warning. If a command fails, the value you asked for is
  dropped rather than shown as if it worked.
- **The cloud connection recovers by itself.** A lost MQTT connection is noticed right away.
  Entities become *unavailable* until a poll succeeds again, and the next request reconnects
  and subscribes again.
- **"Restore Entities" now defaults to off** for new setups. When it's on, HA resends its last
  known state to the unit on every restart, which overrides changes made while HA was down.
- **Secrets stay out of debug logs and diagnostics.** This covers the cloud login response,
  the device list (it holds per-device keys) and the entry data (password, token).

## Install or update through HACS (from this fork)

1. **HACS → Integrations → ⋮ → Custom repositories**, add
   `https://github.com/talKitron/homeassistant-gree-vrf` with type **Integration**.
   If the upstream `Black01986/homeassistant-gree-vrf` repository is also added, remove it
   first. Both use the same `gree_custom` folder.
2. Open **GREE GMV / VRF** in HACS and choose **Download**. To test a pre-release, enable
   *Show beta versions* or pick the version under *Need a different version?*.
3. **Restart Home Assistant.**
4. Check that `/config/custom_components/gree_custom/manifest.json` shows `"version": "0.1.9"`.

The domain stays `gree_custom`, so existing config entries keep working.

## Turn on debug logging (temporary)

Add this to `configuration.yaml` and restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.gree_custom: debug
```

Or go to **Settings → Devices & services → GREE GMV / VRF → ⋮ → Enable debug logging**.
When you turn it off again, HA offers the log as a download.

The debug logs leave out the cloud token, cloud password and device keys. They still contain
MAC addresses, device names and the Gree account e-mail. Remove those before sharing a log
in public.

## What to collect

1. **Setup log.** Add the device, then:

   ```bash
   ha core logs | grep -E "gree_custom" | tail -n 300
   ```

   Lines to look for:
   - `returned an ambiguous response (Malformed response: cols=… dat=…) … Querying them one by one`.
     This is expected for this unit.
   - `Malformed status response: {...}`. Shows the requested props, returned `cols`, `dat`,
     `requested_not_returned`, and the `mac`/`sub` fields.
   - `Single prop queries for '…': returned=[…] missing=[…]`.
   - `Device info is unavailable, continuing without it`, if it appears.

2. **Diagnostics file.** Go to **Settings → Devices & services → GREE GMV / VRF →** the indoor
   unit → **Download diagnostics**. It includes `polled_properties`, the raw `state`, and
   `unconfirmed` (values sent but not yet reported back).

3. **Raw property values.** Under **Developer tools → Actions**, run:

   ```yaml
   action: gree_custom.get_prop_values
   data:
     device_id: <the indoor unit device>
     prop_list: [Pow, Mod, SetTem, TemRec, WdSpd, SwUpDn, SwingLfRig, TemUn, InTem, InTemEn, TemSen, Add0.5]
   ```

   This queries one property at a time. To dump everything, use `gree_custom.get_prop_values_all`.
   It's slow, about one request per property.

4. **Pushed updates.** With debug logging on, change something in the Gree app and look for
   `Pushed status on status/…`. A line saying `Ignoring pushed status for '…'` means the
   unit's pushes carry an id that doesn't match the indoor unit. Please send that line.

## Acceptance checklist

| # | Test | How | Pass when |
|---|------|-----|-----------|
| 1 | Setup | Add the indoor unit (cloud only, *Prefer cloud* on, local fields empty) | Setup finishes with no "Unknown error" |
| 2 | Real state | Compare the climate card with the Gree app | Power, mode, setpoint, fan and room temperature match |
| 3 | On/off from HA | Toggle in HA | Unit switches, the app shows it, and HA still shows it after about 10 s |
| 4 | Setpoint / mode from HA | Change both in HA | The app shows the new values. If it doesn't, HA must go back to the reported value within about 10 s |
| 5 | App → HA | Change power/mode/setpoint in the Gree app | HA updates without touching HA (push, or within one scan interval) |
| 6 | Wall controller → HA | Change on the unit's own controller | Same as 5 |
| 7 | Restart | Change something in the app, then restart HA | After the restart HA shows the unit's current state. Turn off *Restore Entities* first on existing entries |
| 8 | Cloud failure | Block internet for HA for a few minutes | Entities become *unavailable* (not stale). After unblocking they recover without a restart |

For 7, turn off **Restore Entities** in the integration options of an existing entry. Older
entries keep the old default (on).

## Known limits

- Only properties the unit actually reports are offered. Swing, turbo, quiet and so on show up
  only if the unit returns a value for them.
- The half-degree setpoint flag (`Add0.5`) on VRF units is not read, so setpoints are whole
  degrees. This is unchanged from earlier versions.
- How the gateway caches state is inferred from upstream VRF reports. It's handled by polling
  again, never by showing a value the unit hasn't reported.
