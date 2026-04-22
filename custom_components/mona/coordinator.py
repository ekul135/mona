"""Data coordinator for Mona."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MonaApiError, MonaAuthError, MonaClient, MonaMFARequired, MonaOTPMethodChoice
from .const import CONF_SESSION_COOKIES, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MonaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage data fetching from Mona API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self._client: MonaClient | None = None

    async def _get_client(self) -> MonaClient:
        """Get or create the API client with session cookies."""
        if self._client is None:
            self._client = MonaClient()
            
            # Restore session cookies if available
            cookies = self.entry.data.get(CONF_SESSION_COOKIES, {})
            if cookies:
                await self._client.set_cookies(cookies)
                _LOGGER.debug("Restored %d session cookies", len(cookies))
        
        return self._client

    async def _try_reauth(self) -> bool:
        """Attempt to re-authenticate with stored credentials.
        
        Returns:
            True if re-auth successful without MFA
            
        Raises:
            ConfigEntryAuthFailed: If MFA is required (user interaction needed)
        """
        client = await self._get_client()
        username = self.entry.data.get(CONF_USERNAME)
        password = self.entry.data.get(CONF_PASSWORD)
        
        if not username or not password:
            raise ConfigEntryAuthFailed("No stored credentials")
        
        try:
            _LOGGER.info("Session expired, attempting re-authentication")
            await client.login(username, password)
            
            # Update stored cookies
            cookies = client.get_cookies()
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_SESSION_COOKIES: cookies},
            )
            
            _LOGGER.info("Re-authentication successful")
            return True
            
        except (MonaMFARequired, MonaOTPMethodChoice):
            # MFA required - need user interaction
            _LOGGER.warning("Re-authentication requires OTP - user action needed")
            raise ConfigEntryAuthFailed("Session expired - please re-authenticate")
        except MonaAuthError as err:
            _LOGGER.error("Re-authentication failed: %s", err)
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the API.
        
        This method is called by the coordinator at the configured interval.
        It handles session expiry and triggers reauth when needed.
        """
        client = await self._get_client()
        
        try:
            data = await client.get_all_data()
            
            # Update stored cookies on successful fetch (keeps session fresh)
            cookies = client.get_cookies()
            if cookies:
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_SESSION_COOKIES: cookies},
                )
            
            _LOGGER.debug("Data fetch successful: balance=%s", data.get("account_balance"))
            return data
            
        except MonaAuthError:
            # Session expired - try to re-authenticate
            try:
                await self._try_reauth()
                # Retry the data fetch after successful reauth
                data = await client.get_all_data()
                
                # Update cookies after successful retry
                cookies = client.get_cookies()
                if cookies:
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        data={**self.entry.data, CONF_SESSION_COOKIES: cookies},
                    )
                
                return data
                
            except ConfigEntryAuthFailed:
                # Re-raise to trigger HA's reauth flow
                raise
            except Exception as err:
                _LOGGER.error("Failed to re-authenticate: %s", err)
                raise ConfigEntryAuthFailed(f"Re-authentication failed: {err}")
                
        except MonaApiError as err:
            _LOGGER.error("API error: %s", err)
            raise UpdateFailed(f"API error: {err}")
        except aiohttp.ClientError as err:
            _LOGGER.error("Connection error: %s", err)
            raise UpdateFailed(f"Connection error: {err}")
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching data: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}")

    async def async_shutdown(self) -> None:
        """Close the client session on shutdown."""
        if self._client is not None:
            await self._client.close()
            self._client = None
