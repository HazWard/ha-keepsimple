from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

PLATFORMS = ["light"]  # Add the platforms your integration supports

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KeepSmile from a config entry."""
    hass.data.setdefault("keepsmile", {})
    hass.data["keepsmile"][entry.entry_id] = entry.data

    # Forward the entry setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data["keepsmile"].pop(entry.entry_id)

    return unload_ok
