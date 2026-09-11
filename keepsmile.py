"""High-level API for KeepSmile lights.

:class:`KeepSmileInstance` exposes a friendly interface (power channels,
RGB/white color, effects, timers, status) for the config flow and light
platform. All frame encoding lives in :mod:`protocol`; this module only
maps friendly types onto it and owns the BLE connection.

Link behavior: the peripheral terminates idle connections after ~1-2 s, so
every operation connects on demand first. BLE writes are fire-and-forget
(write-without-response), therefore the instance keeps an optimistic shadow
of the last commanded state; :meth:`KeepSmileInstance.update` overwrites it
only when the device answers with a parseable status report.
"""

import asyncio
import logging
import traceback
from typing import List, Optional, Tuple

from bleak import BleakClient, BleakScanner

from . import protocol
from .protocol import (
    EFFECTS_OFF,
    MAX_BRIGHTNESS,
    NOTIFY_UUID,
    STATUS_QUERY,
    STATUS_QUERY_TIMEOUT_S,
    TIMER_OFF,
    WRITE_UUID,
    Channel,
    parse_strip_status,
)

LOGGER = logging.getLogger(__name__)


async def discover():
    """Discover Bluetooth LE devices that look like KeepSmile lights."""
    devices = await BleakScanner.discover()
    LOGGER.debug(
        "Discovered devices: %s",
        [{"address": device.address, "name": device.name} for device in devices],
    )
    return [
        device
        for device in devices
        if device.name
        and (
            device.name.lower().startswith("ks")
            or device.name.lower().startswith("ledble")
        )
    ]


def _create_status_callback(future: "asyncio.Future[bytearray]"):
    def callback(_sender: int, data: bytearray):
        if not future.done():
            future.set_result(data)

    return callback


class KeepSmileInstance:
    """One KeepSmile light: a friendly name over a protocol connection."""

    def __init__(self, mac: str, name: Optional[str] = None) -> None:
        self._mac = mac
        self._name = name or mac
        self._device = BleakClient(self._mac)
        self._is_on: Optional[bool] = None
        self._rgb_color: Tuple[int, int, int] = (0, 0, 0)
        self._brightness: int = MAX_BRIGHTNESS
        self._white_mode: bool = False
        self._available: bool = False

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> Optional[bool]:
        return self._is_on

    @property
    def rgb_color(self) -> Tuple[int, int, int]:
        return self._rgb_color

    @property
    def brightness(self) -> int:
        """Last known brightness in device units (0-100)."""
        return self._brightness

    @property
    def white_mode(self) -> bool:
        return self._white_mode

    @property
    def available(self) -> bool:
        return self._available

    async def _ensure_connected(self) -> None:
        if not self._device.is_connected:
            LOGGER.debug("Connecting to %s", self._mac)
            await self._device.connect(timeout=20)

    async def _write_many(self, frames: List[bytes]) -> None:
        """Write frames spaced at the app's flush cadence."""
        await self._ensure_connected()
        for index, frame in enumerate(frames):
            if index > 0:
                await asyncio.sleep(protocol.SEND_QUEUE_FLUSH_INTERVAL_S)
            LOGGER.debug("Sending to %s: %s", self._mac, frame.hex(" "))
            await self._device.write_gatt_char(WRITE_UUID, frame, response=False)

    async def _write(self, frame: bytes) -> None:
        await self._write_many([frame])

    async def turn_on(self, channel: int = Channel.TOP) -> None:
        """Switch a channel on, keeping the current color/mode."""
        await self._write(protocol.power_frame(channel, True))
        self._is_on = True
        self._available = True

    async def turn_off(self, channel: int = Channel.TOP) -> None:
        """Switch a channel off."""
        await self._write(protocol.power_frame(channel, False))
        self._is_on = False
        self._available = True

    async def set_rgb(
        self, red: int, green: int, blue: int, brightness: int
    ) -> None:
        """Set an RGB color with a device-unit brightness (0-100)."""
        brightness = protocol.clamp_brightness(brightness)
        await self._write_many(
            [
                protocol.power_frame(Channel.TOP, True),
                protocol.rgb_frame(red, green, blue, brightness),
            ]
        )
        self._is_on = True
        self._rgb_color = (red & 0xFF, green & 0xFF, blue & 0xFF)
        self._brightness = brightness
        self._white_mode = False
        self._available = True

    async def set_white(self, brightness: int) -> None:
        """Set white output at the given device-unit brightness (0-100)."""
        brightness = protocol.clamp_brightness(brightness)
        await self._write_many(
            [
                protocol.power_frame(Channel.TOP, True),
                protocol.white_frame(brightness),
            ]
        )
        self._is_on = True
        self._brightness = brightness
        self._white_mode = True
        self._available = True

    async def effects_off(self) -> None:
        """Stop any running effect."""
        await self._write(EFFECTS_OFF)

    async def recover(self) -> None:
        """Bring the light to a dim, low-draw visible state."""
        await self._write(protocol.recover_frame())
        self._is_on = True
        self._rgb_color = (protocol.RECOVER_BRIGHTNESS, 0, 0)
        self._brightness = protocol.RECOVER_BRIGHTNESS
        self._white_mode = False
        self._available = True

    async def timer_on(self, hour: int, minute: int, second: int) -> None:
        """Schedule the light to turn on at ``hour:minute:second``."""
        await self._write(protocol.timer_on_frame(hour, minute, second))

    async def timer_off(self) -> None:
        """Clear any scheduled timer."""
        await self._write(TIMER_OFF)

    async def update(self) -> None:
        """Query live device state (power flags, color, brightness, ...).

        Sends :data:`protocol.STATUS_QUERY` and parses the first ``AFD2``
        notification as :func:`protocol.parse_strip_status`. Replies the
        device sends but which do not decode yet (e.g. the 12-byte
        ``5F ... F5`` query answer) only prove the device is reachable; the
        optimistic shadow is left untouched in that case.
        """
        try:
            await self._ensure_connected()
            await asyncio.sleep(1)

            loop = asyncio.get_running_loop()
            future: "asyncio.Future[bytearray]" = loop.create_future()
            await self._device.start_notify(
                NOTIFY_UUID, _create_status_callback(future)
            )
            try:
                LOGGER.debug("Sending to %s: %s", self._mac, STATUS_QUERY.hex(" "))
                await self._device.write_gatt_char(
                    WRITE_UUID, STATUS_QUERY, response=False
                )
                reply = await asyncio.wait_for(future, STATUS_QUERY_TIMEOUT_S)
            finally:
                await self._device.stop_notify(NOTIFY_UUID)

            LOGGER.debug("Received from %s: %s", self._mac, bytes(reply).hex(" "))
            status = parse_strip_status(bytes(reply))
            if status is None:
                LOGGER.debug(
                    "Status reply from %s did not decode; keeping last known state",
                    self._mac,
                )
                self._available = True
                return

            self._is_on = bool(status["top_on"] or status["bottom_on"])
            self._rgb_color = (
                int(status["red"]),
                int(status["green"]),
                int(status["blue"]),
            )
            self._brightness = protocol.clamp_brightness(int(status["brightness"]))
            self._white_mode = not bool(status["rgb_mode"])
            self._available = True
        except Exception as error:
            self._available = False
            LOGGER.error("Error getting status from %s: %s", self._mac, error)
            LOGGER.debug(traceback.format_exc())

    async def disconnect(self) -> None:
        """Disconnect the BLE client if connected."""
        try:
            if self._device.is_connected:
                await self._device.disconnect()
                LOGGER.info("Disconnected from %s", self._mac)
        except Exception as error:
            LOGGER.error("Error while disconnecting from %s: %s", self._mac, error)
