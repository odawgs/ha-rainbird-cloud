"""Thin wrapper over pyrainbird's IQ4 cloud client.

pyrainbird's AsyncRainbirdCloudController does not fit what the server returns
for an ARC controller on firmware 4.103:
- the run status reply nests zones per program and keeps every zone at "-" even
  while a manual run is watering, so live zone state comes from the AppSync
  stream (see coordinator.py), not from polling;
- Satellite/isConnected returns an empty list for an online controller;
- the sensor list's "onOffState" is undocumented; it is read as the rain
  sensor's state (non-zero = wet) until the stream reports a change.
This module reads the raw replies itself.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from pyrainbird.cloud.client import AsyncRainbirdCloudClient, RainbirdCloudTokenProvider

TICKS_PER_SECOND = 10_000_000

# Run status values that mean a station is not watering.
IDLE_STATUSES = {"", "-", "idle", "pending", "waiting", "queued", "complete", "done"}


@dataclass
class Station:
    """A zone on the controller."""

    station_id: int
    zone: int
    name: str


@dataclass
class Program:
    """A watering program."""

    program_id: int
    name: str


@dataclass
class CloudState:
    """Polled controller state."""

    active_zones: set[int] = field(default_factory=set)
    zone_status: dict[int, str] = field(default_factory=dict)
    remaining: dict[int, int] = field(default_factory=dict)
    rain_delay_days: int = 0
    rain_sensor: bool | None = None
    online: bool | None = None


def _parse_dt(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def is_running(status: Any) -> bool:
    """Return True when a run station status means the valve is open."""
    if status is None:
        return False
    return str(status).strip().lower() not in IDLE_STATUSES


class RainbirdCloudApi:
    """Rain Bird IQ4 cloud access for one controller (satellite)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        satellite_id: int | None = None,
        token: str | None = None,
        token_update_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the API."""
        provider = RainbirdCloudTokenProvider(
            session,
            username,
            password,
            token=token,
            token_update_callback=token_update_callback,
        )
        self._client = AsyncRainbirdCloudClient(session, provider)
        self.satellite_id = satellite_id
        self.device_uuid: str | None = None
        self.stations: dict[int, Station] = {}

    @property
    def token_provider(self) -> RainbirdCloudTokenProvider:
        """Return the token provider (shared with the live stream)."""
        return self._client.token_provider

    @property
    def token(self) -> str | None:
        """Return the current bearer token."""
        return self._client.token_provider.token

    async def satellites(self) -> list[tuple[int, str, int]]:
        """Return (id, name, zone count) for each controller on the account."""
        sats = await self._client.get_satellites()
        for sat in sats:
            if sat.id == self.satellite_id:
                self.device_uuid = sat.device_uuid
        return [(s.id, s.name, s.station_count) for s in sats]

    async def satellite(self) -> dict[str, Any]:
        """Return the raw satellite record."""
        return await self._client.get_satellite(self.satellite_id)

    async def load_stations(self) -> dict[int, Station]:
        """Read the controller's zones, keyed by zone number."""
        stations = {}
        for st in await self._client.get_station_list(self.satellite_id):
            zone = st.station_number or st.number or st.terminal
            if zone is None:
                continue
            stations[zone] = Station(st.id, zone, st.name or f"Zone {zone}")
        self.stations = stations
        return stations

    async def programs(self) -> list[Program]:
        """Return the controller's programs."""
        return [
            Program(p.id, p.name or p.short_name or str(p.id))
            for p in await self._client.get_program_list(self.satellite_id)
        ]

    async def state(self) -> CloudState:
        """Poll zone, rain delay and rain sensor state."""
        state = CloudState()
        by_station_id = {s.station_id: s.zone for s in self.stations.values()}
        for program in await self._client.get_run_station_status(self.satellite_id):
            entries = program.get("runStationStatuses")
            if entries is None:
                entries = [program]
            for entry in entries:
                zone = by_station_id.get(
                    entry.get("stationId"), entry.get("stationTerminal")
                )
                if zone is None:
                    continue
                status = entry.get("status")
                if is_running(status) or entry.get("isIrrigating"):
                    state.active_zones.add(zone)
                    state.zone_status[zone] = str(status)

        sat = await self.satellite()
        state.rain_delay_days = self._rain_delay_days(sat)
        state.rain_sensor = await self.rain_sensor_state()
        return state

    @staticmethod
    def _rain_delay_days(sat: dict[str, Any]) -> int:
        if isinstance(sat.get("rainDelayDaysRemaining"), int):
            return max(0, sat["rainDelayDaysRemaining"])
        ticks = sat.get("rainDelayLong") or 0
        if ticks <= 0:
            return 0
        delay = datetime.timedelta(seconds=ticks / TICKS_PER_SECOND)
        start = _parse_dt(sat.get("rainDelayStart"))
        if start is None:
            return math.ceil(delay.total_seconds() / 86400)
        remaining = start + delay - datetime.datetime.now(datetime.UTC)
        return max(0, math.ceil(remaining.total_seconds() / 86400))

    async def _rain_sensor(self) -> dict[str, Any] | None:
        for sensor in await self._client.get_sensor_list(self.satellite_id):
            text = f"{sensor.get('name', '')} {sensor.get('model', '')}".lower()
            if sensor.get("type") == "Rain" or "rain" in text:
                return sensor
        return None

    async def has_rain_sensor(self) -> bool:
        """Return True when the controller lists a rain sensor."""
        return await self._rain_sensor() is not None

    async def rain_sensor_state(self) -> bool | None:
        """Return True when the rain sensor reads wet, None if unknown."""
        sensor = await self._rain_sensor()
        if sensor is None or not isinstance(sensor.get("onOffState"), int):
            return None
        return sensor["onOffState"] != 0

    async def start_zone(self, zone: int, minutes: int) -> None:
        """Run one zone for the given minutes."""
        if zone not in self.stations:
            await self.load_stations()
        await self._client.start_stations(
            [self.stations[zone].station_id], [int(minutes) * 60]
        )

    async def stop_all(self) -> None:
        """Stop all watering."""
        await self._client.stop_all_irrigation(self.satellite_id)

    async def start_program(self, program_id: int) -> None:
        """Start a program."""
        await self._client.start_programs([program_id])

    async def set_rain_delay(self, days: int) -> None:
        """Set or clear the rain delay."""
        ticks = int(days) * 86400 * TICKS_PER_SECOND
        now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self._client.patch_satellite(
            self.satellite_id,
            [
                {"op": "replace", "path": "/rainDelayLong", "value": ticks},
                {"op": "replace", "path": "/rainDelayStart", "value": now},
            ],
        )
