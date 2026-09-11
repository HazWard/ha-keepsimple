"""Light platform for KeepSmile lights."""

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .keepsmile import KeepSmileInstance
from .protocol import MAX_BRIGHTNESS

#: A full-white RGB pick drives the native white frame instead of RGB.
WHITE_PICK = (255, 255, 255)


def _to_device_brightness(ha_brightness: int) -> int:
    """Scale Home Assistant brightness (0-255) to device units (0-100)."""
    return max(0, min(MAX_BRIGHTNESS, round(ha_brightness * MAX_BRIGHTNESS / 255)))


def _to_ha_brightness(device_brightness: int) -> int:
    """Scale device brightness (0-100) to Home Assistant units (0-255)."""
    return round(device_brightness * 255 / MAX_BRIGHTNESS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KeepSmile lights from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    instance = KeepSmileInstance(data[CONF_MAC], data.get("name"))
    async_add_entities([KeepSmileLight(instance)])


class KeepSmileLight(LightEntity):
    """Representation of a KeepSmile light (RGB + white, optimistic)."""

    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.WHITE}
    _attr_assumed_state = True

    def __init__(self, instance: KeepSmileInstance) -> None:
        self._instance = instance
        self._attr_unique_id = format_mac(instance.mac)
        self._attr_name = instance.name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, format_mac(instance.mac))},
            "name": instance.name,
            "manufacturer": "KeepSmile",
            "model": "KS03~",
        }
        self._attr_color_mode = ColorMode.RGB
        self._sync_attrs()

    def _sync_attrs(self) -> None:
        """Mirror the instance shadow onto entity attributes."""
        self._attr_is_on = self._instance.is_on
        if self._instance.white_mode:
            self._attr_color_mode = ColorMode.WHITE
            self._attr_rgb_color = None
        else:
            self._attr_color_mode = ColorMode.RGB
            self._attr_rgb_color = self._instance.rgb_color
        self._attr_brightness = _to_ha_brightness(self._instance.brightness)

    @property
    def available(self) -> bool:
        return self._instance.available

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb = kwargs.get(ATTR_RGB_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if rgb is not None:
            device_brightness = (
                _to_device_brightness(brightness)
                if brightness is not None
                else self._instance.brightness
            )
            if tuple(rgb) == WHITE_PICK:
                await self._instance.set_white(device_brightness)
            else:
                await self._instance.set_rgb(*rgb, device_brightness)
        elif brightness is not None:
            device_brightness = _to_device_brightness(brightness)
            if self._instance.white_mode:
                await self._instance.set_white(device_brightness)
            else:
                red, green, blue = self._instance.rgb_color
                await self._instance.set_rgb(red, green, blue, device_brightness)
        else:
            await self._instance.turn_on()
        self._sync_attrs()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._instance.turn_off()
        self._sync_attrs()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        await self._instance.update()
        self._sync_attrs()

    async def async_will_remove_from_hass(self) -> None:
        await self._instance.disconnect()
