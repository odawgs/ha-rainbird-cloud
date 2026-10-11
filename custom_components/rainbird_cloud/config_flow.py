"""Config flow for Rain Bird Cloud."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyrainbird.exceptions import (
    RainbirdApiException,
    RainbirdAuthException,
    RainbirdConnectionError,
)

from .api import RainbirdCloudApi
from .const import (
    CONF_DURATION,
    CONF_SATELLITE_ID,
    CONF_TOKEN,
    DEFAULT_DURATION_MINUTES,
    DOMAIN,
    TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class RainbirdCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in with a Rain Bird account and pick a controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._credentials: dict[str, Any] = {}
        self._satellites: dict[int, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RainbirdCloudOptionsFlow()

    async def _login(self, username: str, password: str) -> tuple[str | None, str]:
        """Log in and list controllers. Returns (token, error key or '')."""
        api = RainbirdCloudApi(async_get_clientsession(self.hass), username, password)
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS * 3):
                sats = await api.satellites()
        except RainbirdAuthException:
            return None, "invalid_auth"
        except (RainbirdApiException, RainbirdConnectionError, TimeoutError) as err:
            _LOGGER.warning("Rain Bird cloud login failed: %s", err)
            return None, "cannot_connect"
        self._satellites = {sid: f"{name} ({zones} zones)" for sid, name, zones in sats}
        if not self._satellites:
            return None, "no_controllers"
        return api.token, ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Rain Bird account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            token, error = await self._login(username, user_input[CONF_PASSWORD])
            if not error:
                self._credentials = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_TOKEN: token,
                }
                if len(self._satellites) == 1:
                    return await self._create(next(iter(self._satellites)))
                return await self.async_step_controller()
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_controller(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a controller when the account has more than one."""
        if user_input is not None:
            return await self._create(int(user_input[CONF_SATELLITE_ID]))
        options = [
            selector.SelectOptionDict(value=str(sid), label=label)
            for sid, label in self._satellites.items()
        ]
        return self.async_show_form(
            step_id="controller",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SATELLITE_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def _create(self, satellite_id: int) -> ConfigFlowResult:
        await self.async_set_unique_id(str(satellite_id))
        self._abort_if_unique_id_configured()
        title = self._satellites[satellite_id].rsplit(" (", 1)[0]
        return self.async_create_entry(
            title=title,
            data={**self._credentials, CONF_SATELLITE_ID: satellite_id},
            options={CONF_DURATION: DEFAULT_DURATION_MINUTES},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a rejected login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account password again."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token, error = await self._login(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not error:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_TOKEN: token,
                    },
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )


class RainbirdCloudOptionsFlow(OptionsFlow):
    """Default watering time for the zone switches."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_DURATION): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1,
                                max=180,
                                step=1,
                                unit_of_measurement="min",
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        )
                    }
                ),
                self.config_entry.options,
            ),
        )
