# KeepSmile Light Protocol Notes

Working notes for the KeepSmile Bluetooth LED lights supported by this
project. These observations come from live BLE testing and disassembly of
the official KeepSmile Android APK (`com.youzda.smartlight` v1.1).
Shared with the `ks_lights` Rust project, which holds its own copy.

> **Command reference:** the canonical, tested command set lives in
> [`protocol.py`](protocol.py) (frame builders, `STATUS_QUERY`,
> `TIMER_OFF`/`timer_on_frame`, UUIDs, `parse_strip_status`). This file
> records device observations, live-test findings, and open questions —
> not the frames themselves.

## Observed Device

- Device: `KS03~981B2B` LED strip (MAC `23:01:02:98:1B:2B`)
- Device family: names beginning with `KS` or `LEDBLE`
- `KS03~` (tilde) is its own protocol family. `KS03-` (hyphen), `KS04-`,
  `KS01-`, `KS02-` use a shorter `7E ... EF` format; Triones/`LEDBLE`
  hardware uses `56 ...` / `CC ...` frames. `KS03~` hardware silently
  ignores both — this caused most of our early confusion.

### GATT layout (confirmed live and in the APK's `UUIDBeanList`)

```text
service AFD0 / characteristic AFD1
  properties: WRITE_WITHOUT_RESPONSE | WRITE   -> command/write

service AFD0 / characteristic AFD2
  properties: NOTIFY                           -> status/event notifications

service AFD0 / characteristic AFD3
  properties: READ                             -> static data
```

Full 128-bit form: `0000XXXX-0000-1000-8000-00805f9b34fb`. The APK builds
these from 16-bit shorts (`String.format("0000%s-...", "AFD0")`, ...).

### Direct-read probe results

```text
AFD1: 00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d
AFD2: 00 01 02 03 04 05 06 07 08 09 0a 0b
AFD3: 00 01 02 03 04
```

Deterministic sequential bytes, unrelated to light state. BlueZ allows
reading even the write/notify characteristics; none of these values are
status. `AFD2` probe values especially must not be treated as notification
responses.

## App Behavior (from APK disassembly)

- **Command classes**: `CmdFloor` (the command class our strip answers to)
  builds
  `5B(F0|0F)(01|02|00)B5` channel on/off; `FloorBean.getSendCmd` builds the
  `5A00(01|02)...A5` color/white frames; `CmdBase` holds shared builders
  (effects, scenes, music, timer, time sync).
- **Color path**: color wheel → normalized values `× 255` → R/G/B
  (`0x00`–`0xFF`); percent slider (max 100, default 50) → `BR` byte
  unscaled. See `MAX_BRIGHTNESS` in `protocol.py`.
- **Send path**: hex-string commands queued per device and flushed on a
  ~100 ms loop timer; writes use write-without-response when supported
  (`BleUtils.write` / `BleSend` / `cnn.depend.ble` layer).
- **Session setup**: subscribe to `AFD2` on service discovery; the
  app sends status query `5F 01 00 F5` right after connecting
  (seen in the APK's floor-lamp flow) and parses the reply per the
  `StripStatus` field layout in
  `protocol.py`.
- **Per-model routing**: `BleUtils.setCmd` maps name prefixes (`KS03-`,
  `KS01-`, ...) to `Cmd_*` classes; scan filtering matches `KS03~`, timer,
  scene, music, and password flows exist but are secondary.

## Live BLE Findings (2026-09-10, CoreELEC box next to the light)

Tested with `bleak` 3.0.2 in a Python venv on the CoreELEC host, with
`btmon` HCI traces to confirm.

- `recover` (`5A 00 01 1A 00 00 00 1A 00 A5`) is accepted: HCI shows the
  `ATT Write Command` on handle `0x0006` and the light shows dim red.
- `ON` (`5B F0 01 B5`) plus dim red/white frames all send cleanly.
- Wrong-family status query `EF 01 77` → **no notification within 8 s**.
- The peripheral drops the connection ~1–2 s after the last GATT activity,
  peripheral-initiated (`Disconnect Complete, reason 0x13`). Plain
  `bluetoothctl connect` shows the same pattern. Implementations must
  reconnect per command batch.
- Boot-catch attempts (power-cycle, rapid reconnect, spam dim frames) fail:
  during early boot the peripheral accepts a connection then drops it
  within milliseconds, repeatedly (~15 connects, zero successful writes).
  The boot window cannot be caught over BLE.
- Physical symptom: on power plug-in the strip flashes bright white for
  ~1 s, then goes dark. BLE keeps working. `turn_on` and color/white writes
  sent later produce no LED response while the driver is in this latched-off
  state — later resolved as wrong-protocol frames being ignored, but the
  boot flash itself remains a power-stage behavior to respect (stay at or
  below the app's brightness range).

## Later findings: the status query answer (2026-09-11)

- The correct query `5F 01 00 F5` **is** answered: `AFD2` delivers a
  12-byte notification framed as `5F ... F5`, e.g.
  `5F 06 01 0F 1A 00 00 00 02 01 00 F5` while the light showed dim red.
- That layout does **not** match the APK's `FloorBean` substring positions
  (which expect ≥28 hex chars), so `parse_strip_status` returns `None` for
  it and callers keep their previous state. Byte 4 (`0x1A` = 26) coincides
  with both the red channel and the brightness of that test state, and a
  later reply after a color change came back byte-identical — the field
  layout is still undecoded. Polls therefore confirm reachability but
  rarely refresh color/brightness.

## Open Questions

- The CW byte's exact role remains unconfirmed (the mode-`02`
  `5A 00 02 00 00 00 CW BR 00 A5` white branch from the APK produced no
  visible change in testing; white goes through RGB mode).
- Full decode of the 12-byte `5F ... F5` query reply (see above).
- Does `5B F0 01 B5` restore a previously stored brightness that can exceed
  the safe power limit?
- Scene (`5C...C5`), music (`5A0001...00A5` variants), and effect-model
  (`5A0AF00...A5`) frames are decoded but not live-tested.
