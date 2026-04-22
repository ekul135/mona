"""Config flow for Mona integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import MonaAuthError, MonaApiError, MonaClient, MonaMFARequired, MonaOTPMethodChoice
from .const import CONF_MEMBER_NUMBER, CONF_OTP, CONF_SESSION_COOKIES, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MonaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mona."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._username: str | None = None
        self._password: str | None = None
        self._client: MonaClient | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None
        self._otp_options: list[dict] | None = None  # OTP delivery options

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - login credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]

            try:
                self._client = MonaClient()
                await self._client.login(self._username, self._password)
                # If we get here without MFA, create entry directly
                return await self._create_entry()

            except MonaOTPMethodChoice as err:
                # User needs to choose SMS or Email
                self._otp_options = err.options
                return await self.async_step_otp_method()
            except MonaMFARequired:
                # OTP already sent (no choice) - go directly to OTP entry
                return await self.async_step_otp()
            except MonaAuthError as err:
                _LOGGER.error("Authentication error: %s", err)
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError as err:
                _LOGGER.error("Connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "docs_url": "https://github.com/ekul135/mona"
            },
        )

    async def async_step_otp_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle OTP delivery method selection (SMS or Email)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            method_index = int(user_input["otp_method"])

            try:
                if self._client is None:
                    raise MonaAuthError("No authentication in progress")
                
                await self._client.select_otp_method(method_index)
                # If we get here, no OTP needed (unlikely)
                return await self._create_entry()

            except MonaMFARequired:
                # Expected - OTP sent, now need code entry
                return await self.async_step_otp()
            except MonaAuthError as err:
                _LOGGER.error("OTP method selection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error during OTP method selection: %s", err)
                errors["base"] = "unknown"

        # Build options from stored choices
        method_options = {}
        if self._otp_options:
            for opt in self._otp_options:
                method_options[str(opt["index"])] = opt["label"]
        else:
            # Fallback if no options stored
            method_options = {"0": "SMS", "1": "Email"}

        return self.async_show_form(
            step_id="otp_method",
            data_schema=vol.Schema(
                {
                    vol.Required("otp_method"): vol.In(method_options),
                }
            ),
            errors=errors,
            description_placeholders={
                "username": self._username or "user"
            },
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the OTP verification step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input[CONF_OTP]

            try:
                if self._client is None:
                    raise MonaAuthError("No authentication in progress")
                
                await self._client.submit_otp(otp)
                
                # OTP successful - create/update entry
                if self._reauth_entry:
                    return await self._update_reauth_entry()
                return await self._create_entry()

            except MonaAuthError as err:
                _LOGGER.error("OTP error: %s", err)
                errors["base"] = "invalid_otp"
            except Exception as err:
                _LOGGER.exception("Unexpected error during OTP: %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OTP): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "username": self._username or "user"
            },
        )

    async def _create_entry(self) -> FlowResult:
        """Create the config entry after successful authentication."""
        if self._client is None:
            raise MonaAuthError("No client available")
        
        # Get member data to confirm login and get member number
        try:
            data = await self._client.get_dashboard()
            member_number = data.get("membershipNumber", self._username)
        except MonaApiError:
            member_number = self._username
        
        # Get session cookies to store
        cookies = self._client.get_cookies()
        await self._client.close()
        
        # Set unique ID and abort if already configured
        await self.async_set_unique_id(member_number)
        self._abort_if_unique_id_configured()
        
        return self.async_create_entry(
            title=f"Mona ({member_number})",
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_MEMBER_NUMBER: member_number,
                CONF_SESSION_COOKIES: cookies,
            },
        )

    async def _update_reauth_entry(self) -> FlowResult:
        """Update existing entry during reauth."""
        if self._client is None or self._reauth_entry is None:
            raise MonaAuthError("No client or entry available")
        
        # Get updated cookies
        cookies = self._client.get_cookies()
        await self._client.close()
        
        # Update the entry with new credentials/cookies
        self.hass.config_entries.async_update_entry(
            self._reauth_entry,
            data={
                **self._reauth_entry.data,
                CONF_PASSWORD: self._password,
                CONF_SESSION_COOKIES: cookies,
            },
        )
        
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        
        return self.async_abort(reason="reauth_successful")

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthorization when session expires."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._username = entry_data.get(CONF_USERNAME)
        self._password = entry_data.get(CONF_PASSWORD)
        
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth confirmation - try stored credentials, prompt for OTP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # User can optionally update password
            if CONF_PASSWORD in user_input and user_input[CONF_PASSWORD]:
                self._password = user_input[CONF_PASSWORD]

        # Try to login with stored/updated credentials
        if self._username and self._password:
            try:
                self._client = MonaClient()
                await self._client.login(self._username, self._password)
                # If we get here without MFA, update entry directly
                return await self._update_reauth_entry()

            except MonaOTPMethodChoice as err:
                # User needs to choose SMS or Email
                self._otp_options = err.options
                return await self.async_step_otp_method()
            except MonaMFARequired:
                return await self.async_step_otp()
            except MonaAuthError as err:
                _LOGGER.error("Reauth error: %s", err)
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError as err:
                _LOGGER.error("Connection error during reauth: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error during reauth: %s", err)
                errors["base"] = "unknown"

        # Show form to confirm/update password if needed
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PASSWORD, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "username": self._username or "user"
            },
        )
