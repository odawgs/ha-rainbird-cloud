"""Update coordinator for Rain Bird Cloud.

Polling (every minute) reads the rain delay and any scheduled run the server
reports. Live zone, rain sensor and online state come from Rain Bird's AppSync
stream, the same feed the Rain Bird 2.0 app uses. Zones Home Assistant starts
are also shown as on for the run time it asked for, in case the stream is slow.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass, replace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pyrainbird.cloud.models import (
    ConnectionStatusEvent,
    RainSensorStateEvent,
    StationStateEvent,
)
from pyrainbird.cloud.stream import AsyncRainbirdCloudStream
from pyrainbird.exceptions import (
    RainbirdApiException,
    RainbirdAuthException,
    RainbirdConnectionError,
)

from .api import CloudState, Program, RainbirdCloudApi
from .const import DOMAIN, MANUFACTURER, TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = datetime.timedelta(minutes=1)
# The cloud takes a few seconds to reflect a start or stop.
DEBOUNCER_COOLDOWN = 10
STREAM_RETRY = 60


@dataclass
class RainbirdCloudData:
    """Runtime data for a config entry."""

    api: RainbirdCloudApi
    coordinator: RainbirdCloudCoordinator
    programs: list[Program]
    has_rain_sensor: bool


type RainbirdCloudConfigEntry = ConfigEntry[RainbirdCloudData]


class RainbirdCloudCoordinator(DataUpdateCoordinator[CloudState]):
    """Polls the Rain Bird cloud and follows its live stream for one controller."""

    config_entry: RainbirdCloudConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RainbirdCloudConfigEntry,
        api: RainbirdCloudApi,
        model: str | None,
        sw_version: str | None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=config_entry.title,
            update_interval=UPDATE_INTERVAL,
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=DEBOUNCER_COOLDOWN, immediate=False
            ),
        )
        self.api = api
        self._model = model
        self._sw_version = sw_version
        # zone -> time its run ends, from the stream or from a start sent by HA
        self._zone_until: dict[int, datetime.datetime] = {}
        self._rain_sensor: bool | None = None
        self._online: bool | None = None
        self._polled = CloudState()
        self._expiry_unsub = None

    @property
    def unique_id(self) -> str:
        """Return the controller's unique id."""
        return str(self.config_entry.unique_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the controller device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=self.config_entry.title,
            manufacturer=MANUFACTURER,
            model=self._model,
            sw_version=self._sw_version,
        )

    async def _async_update_data(self) -> CloudState:
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                polled = await self.api.state()
        except RainbirdAuthException as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (RainbirdApiException, RainbirdConnectionError, TimeoutError) as err:
            raise UpdateFailed(f"Rain Bird cloud error: {err}") from err
        self._polled = polled
        return self._merge()

    def _merge(self) -> CloudState:
        """Combine the last poll with live zone timers and stream values."""
        base = self._polled
        now = dt_util.utcnow()
        self._zone_until = {z: t for z, t in self._zone_until.items() if t > now}
        active = set(base.active_zones) | set(self._zone_until)
        remaining = {
            z: int((t - now).total_seconds()) for z, t in self._zone_until.items()
        }
        self._schedule_expiry()
        return replace(
            base,
            active_zones=active,
            remaining=remaining,
            rain_sensor=self._rain_sensor,
            online=self._online,
        )

    async def async_shutdown(self) -> None:
        """Cancel the zone expiry timer."""
        if self._expiry_unsub:
            self._expiry_unsub()
            self._expiry_unsub = None
        await super().async_shutdown()

    @callback
    def _schedule_expiry(self) -> None:
        if self._expiry_unsub:
            self._expiry_unsub()
            self._expiry_unsub = None
        if not self._zone_until:
            return
        delay = (min(self._zone_until.values()) - dt_util.utcnow()).total_seconds()
        self._expiry_unsub = async_call_later(
            self.hass, max(1.0, delay + 1), self._handle_expiry
        )

    @callback
    def _handle_expiry(self, _now: datetime.datetime) -> None:
        self._expiry_unsub = None
        if self.data is not None:
            self.async_set_updated_data(self._merge())

    @callback
    def zone_started(self, zone: int, seconds: int) -> None:
        """Record a run Home Assistant just started."""
        self._zone_until[zone] = dt_util.utcnow() + datetime.timedelta(seconds=seconds)
        self.async_set_updated_data(self._merge())

    @callback
    def all_stopped(self) -> None:
        """Record a stop Home Assistant just sent."""
        self._zone_until.clear()
        self._polled = replace(self._polled, active_zones=set())
        self.async_set_updated_data(self._merge())

    async def async_stream(self) -> None:
        """Follow the live stream for as long as the entry is loaded."""
        if not self.api.device_uuid:
            _LOGGER.warning("No device id for %s; live updates disabled", self.name)
            return
        stream = AsyncRainbirdCloudStream(
            self.api.token_provider,
            self.api.satellite_id,
            self.api.device_uuid,
            async_get_clientsession(self.hass),
        )
        while True:
            try:
                async for event in stream.listen():
                    self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the stream alive
                _LOGGER.warning("Rain Bird live stream stopped (%s); retrying", err)
            await asyncio.sleep(STREAM_RETRY)

    @callback
    def _handle_event(self, event: object) -> None:
        _LOGGER.debug("Rain Bird stream event: %s", event)
        now = dt_util.utcnow()
        if isinstance(event, StationStateEvent):
            if event.is_watering and (event.remaining_seconds or 0) > 0:
                self._zone_until[event.zone] = now + datetime.timedelta(
                    seconds=event.remaining_seconds
                )
            else:
                self._zone_until.pop(event.zone, None)
        elif isinstance(event, ConnectionStatusEvent):
            self._online = event.is_connected
            station = event.active_station
            if station and (event.remaining_seconds or 0) > 0:
                self._zone_until = {
                    station: now + datetime.timedelta(seconds=event.remaining_seconds)
                }
            elif event.active_station is not None or event.remaining_seconds == 0:
                self._zone_until.clear()
        elif isinstance(event, RainSensorStateEvent):
            self._rain_sensor = event.is_wet
        else:
            return
        if self.data is not None:
            self.async_set_updated_data(self._merge())
