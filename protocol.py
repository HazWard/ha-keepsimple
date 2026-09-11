"""BLE command protocol for KeepSmile KS LED lights.

This module is the canonical command reference for this integration. It was
built by disassembling the official KeepSmile Android app
(``com.youzda.smartlight`` v1.1: ``BleUtils``, ``FloorBean``, ``CmdFloor``,
``CmdBase``, ``UUIDBeanList``) and verified live against ``KS03~981B2B``.

The ``KS03~`` (tilde) family uses an extended frame format on service
``AFD0``, write characteristic ``AFD1``::

    ON:    5B F0 01 B5          (channel byte: 01 top, 02 bottom, 00 all)
    OFF:   5B 0F 01 B5
    RGB:   5A 00 01 RR GG BB 00 BR 00 A5
    White: 5A 00 01 FF FF FF 00 BR 00 A5

Value ranges, as the app produces them:

- ``RR``/``GG``/``BB``: full ``0x00``-``0xFF``.
- ``BR``: ``0x00``-``0x64`` (0-100). The brightness slider is percent-based
  and its progress is passed through unscaled; see :data:`MAX_BRIGHTNESS`.

App transport behavior, mirrored here where applicable:

- UI-driven commands are queued and flushed on a ~100 ms loop timer (see
  :data:`SEND_QUEUE_FLUSH_INTERVAL_S`); rapid changes should be coalesced
  rather than written synchronously one by one.
- Writes use write-without-response.
- On connect the app sends :data:`STATUS_QUERY` and parses the
  notification reply on ``AFD2`` as :func:`parse_strip_status` (seen in the
  APK's floor-lamp flow; our LED strip answers the same query).

The older ``KS03-``/``KS04-``/``KS01-``/``KS02-`` families use a shorter
standard format (``7E 07 05 03 RR GG BB 00 EF``); the Triones/``LEDBLE``
family uses yet another format (``56 ...``, ``CC 23 33``). Neither applies
to ``KS03~`` hardware, which silently ignores those frames.
"""

from typing import Dict, Optional


def _uuid(short: int) -> str:
    return "0000{:04x}-0000-1000-8000-00805f9b34fb".format(short)


#: ``KS03~`` GATT service.
SERVICE_UUID = _uuid(0xAFD0)
#: ``KS03~`` write characteristic (write, write-without-response).
WRITE_UUID = _uuid(0xAFD1)
#: ``KS03~`` notify characteristic (status reports).
NOTIFY_UUID = _uuid(0xAFD2)
#: ``KS03~`` read characteristic (static device data, not light state).
READ_UUID = _uuid(0xAFD3)

#: Interval (s) of the app's send-queue flush loop. Bursts of color /
#: brightness changes should be coalesced on roughly this cadence instead of
#: one synchronous write per change.
SEND_QUEUE_FLUSH_INTERVAL_S = 0.1

#: Maximum brightness byte sent to the light (``0x64`` = 100).
#:
#: This matches the official KeepSmile app: its brightness slider is
#: percent-based and the progress value is passed straight through as the
#: ``BR`` byte with no further scaling. Full scale (``0xFF``) trips the LED
#: driver/power protection on some units, so brightness is capped here.
MAX_BRIGHTNESS = 100

#: Safe recovery brightness: dim output used to bring a light back to a
#: visible but low-draw state.
RECOVER_BRIGHTNESS = 26

#: How long :meth:`keepsmile.KeepSmileInstance.update` waits for the ``AFD2``
#: notification after sending :data:`STATUS_QUERY`.
STATUS_QUERY_TIMEOUT_S = 8.0


class Channel:
    """Output channel selector (``01`` top, ``02`` bottom, ``00`` both)."""

    TOP = 0x01
    BOTTOM = 0x02
    ALL = 0x00


def clamp_brightness(value: int) -> int:
    """Clamp a brightness value to :data:`MAX_BRIGHTNESS`."""
    return max(0, min(int(value), MAX_BRIGHTNESS))


def power_frame(channel: int = Channel.TOP, on: bool = True) -> bytes:
    """Encode a power frame: ``5B (F0|0F) (01|02|00) B5``."""
    return bytes((0x5B, 0xF0 if on else 0x0F, channel, 0xB5))


def rgb_frame(red: int, green: int, blue: int, brightness: int) -> bytes:
    """Encode an RGB frame: ``5A 00 01 RR GG BB 00 BR 00 A5``.

    ``red``/``green``/``blue`` are full-range (``0x00``-``0xFF``);
    ``brightness`` is capped at :data:`MAX_BRIGHTNESS`.
    """
    return bytes(
        (
            0x5A,
            0x00,
            0x01,
            red & 0xFF,
            green & 0xFF,
            blue & 0xFF,
            0x00,
            clamp_brightness(brightness),
            0x00,
            0xA5,
        )
    )


def white_frame(brightness: int) -> bytes:
    """Encode a white frame: ``5A 00 01 FF FF FF 00 BR 00 A5``.

    Verified live: driving all three RGB channels at full with the
    brightness byte produces white. (The app also has a mode-``02``
    ``5A 00 02 00 00 00 CW BR 00 A5`` white branch, but frames in that form
    produced no visible change in live testing, so white goes through RGB
    mode here.)
    """
    level = clamp_brightness(brightness)
    return bytes((0x5A, 0x00, 0x01, 0xFF, 0xFF, 0xFF, 0x00, level, 0x00, 0xA5))


def recover_frame() -> bytes:
    """Dim red recovery state: visible output at minimal power draw."""
    return rgb_frame(RECOVER_BRIGHTNESS, 0, 0, RECOVER_BRIGHTNESS)


#: Stop any running effect: ``5A 0A 0F 03 05 A5``.
EFFECTS_OFF = bytes((0x5A, 0x0A, 0x0F, 0x03, 0x05, 0xA5))

#: Status query for ``KS03~`` hardware: ``5F 01 00 F5``.
#:
#: The app sends this immediately after connecting (seen in the APK's
#: floor-lamp flow; our LED strip answers the same query). The
#: notification reply on ``AFD2`` is parsed as :func:`parse_strip_status`.
STATUS_QUERY = bytes((0x5F, 0x01, 0x00, 0xF5))

#: Timer off command: ``5D 0F 0E 0F 00 00 00 00 D5``.
TIMER_OFF = bytes((0x5D, 0x0F, 0x0E, 0x0F, 0x00, 0x00, 0x00, 0xD5))


def timer_on_frame(hour: int, minute: int, second: int) -> bytes:
    """Encode a timer-on command: ``5D F0 HH MM SS 00 00 00 D5``."""
    return bytes((0x5D, 0xF0, hour, minute, second, 0x00, 0x00, 0xD5))


def parse_strip_status(payload: bytes) -> Optional[Dict[str, object]]:
    """Parse an ``AFD2`` status report, as the app's ``CmdFloor.getFloorBean``
    handler does (APK names; our LED strip answers the same frames).

    Field positions are hex-character offsets into the notification payload,
    as observed in the APK's substring parsing. ``R/G/B/CW/BR`` are one byte
    each; the ``F0`` flags mean "on". Returns ``None`` when the payload is
    too short to hold the status layout.

    .. note::
        Live ``KS03~981B2B`` answers :data:`STATUS_QUERY` with a 12-byte
        ``5F ... F5`` frame whose field layout is not decoded yet; such
        replies return ``None`` and callers must keep their previous state.
    """
    hex_payload = payload.hex()
    if len(hex_payload) < 28:
        return None

    def byte_at(char_offset: int) -> int:
        return int(hex_payload[char_offset : char_offset + 2], 16)

    return {
        "dynamic": hex_payload[4:6] == "01",
        "rgb_mode": hex_payload[8:10] == "01",
        "red": byte_at(10),
        "green": byte_at(12),
        "blue": byte_at(14),
        "cold_white": byte_at(16),
        "brightness": byte_at(18),
        "speed": byte_at(20),
        "model": byte_at(22),
        "top_on": hex_payload[24:26].upper() == "F0",
        "bottom_on": hex_payload[26:28].upper() == "F0",
    }
