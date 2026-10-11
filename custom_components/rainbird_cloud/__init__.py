"""Rain Bird irrigation controllers through the Rain Bird (IQ4) cloud."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyrainbird.exceptions import (
    RainbirdApiException,
    RainbirdAuthException,
    RainbirdConnectionError,
)

from .api import RainbirdCloudApi
from .const import CONF_SATELLITE_ID, CONF_TOKEN, TIMEOUT_SECONDS
from .coordinator import (
    RainbirdCloudConfigEntry,
    RainbirdCloudCoordinator,
    RainbirdCloudData,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: RainbirdCloudConfigEntry
) -> bool:
    """Set up Rain Bird Cloud from a config entry."""

    async def _save_token(token: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: token}
        )

    api = RainbirdCloudApi(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        satellite_id=entry.data[CONF_SATELLITE_ID],
        token=entry.data.get(CONF_TOKEN),
        token_update_callback=_save_token,
    )
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            await api.satellites()
            sat = await api.satellite()
            await api.load_stations()
            programs = await api.programs()
            has_rain_sensor = await api.has_rain_sensor()
    except RainbirdAuthException as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (RainbirdApiException, RainbirdConnectionError, TimeoutError) as err:
        raise ConfigEntryNotReady(f"Rain Bird cloud unavailable: {err}") from err

    model = sat.get("modelName") or sat.get("model") or sat.get("satelliteType")
    coordinator = RainbirdCloudCoordinator(
        hass,
        entry,
        api,
        str(model) if model else None,
        sat.get("versionString"),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = RainbirdCloudData(api, coordinator, programs, has_rain_sensor)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_stream(), f"{entry.title} live stream"
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: RainbirdCloudConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: RainbirdCloudConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
