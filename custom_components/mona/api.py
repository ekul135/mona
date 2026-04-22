"""Mona API Client."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import AUTH_ENDPOINT, BASE_URL

_LOGGER = logging.getLogger(__name__)


class MonaAuthError(Exception):
    """Authentication error."""


class MonaMFARequired(Exception):
    """MFA/OTP is required."""
    
    def __init__(self, message: str, auth_id: str | None = None, options: list[dict] | None = None):
        """Initialize with auth_id for continuing auth flow."""
        super().__init__(message)
        self.auth_id = auth_id
        self.options = options  # List of OTP delivery options (email/sms)


class MonaOTPMethodChoice(Exception):
    """User must choose OTP delivery method."""
    
    def __init__(self, message: str, auth_id: str | None = None, options: list[dict] | None = None):
        """Initialize with available OTP delivery options."""
        super().__init__(message)
        self.auth_id = auth_id
        self.options = options or []  # e.g. [{"index": 0, "label": "SMS"}, {"index": 1, "label": "Email"}]


class MonaApiError(Exception):
    """API error."""


class MonaClient:
    """Async client for Mona API."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        """Initialize the client."""
        self._external_session = session
        self._session: aiohttp.ClientSession | None = None
        self._auth_id: str | None = None
        self._headers = {
            "accept": "application/json",
            "accept-language": "en-GB,en;q=0.9,en-US;q=0.8,en-AU;q=0.7",
            "content-type": "application/json",
            "origin": BASE_URL,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-requested-with": "forgerock-sdk",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session with cookie jar."""
        if self._session is None:
            jar = aiohttp.CookieJar(unsafe=True)
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                cookie_jar=jar,
                timeout=timeout,
            )
        return self._session

    async def close(self) -> None:
        """Close the session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def get_cookies(self) -> dict[str, str]:
        """Get current session cookies for storage."""
        if self._session is None:
            return {}
        
        cookies = {}
        for cookie in self._session.cookie_jar:
            cookies[cookie.key] = cookie.value
        return cookies

    async def set_cookies(self, cookies: dict[str, str]) -> None:
        """Restore session cookies from storage."""
        session = await self._get_session()
        
        # Create cookie objects for the domain
        for name, value in cookies.items():
            session.cookie_jar.update_cookies(
                {name: value},
                response_url=aiohttp.client.URL(BASE_URL)
            )

    async def login(self, username: str, password: str) -> bool:
        """Start login flow with username and password.
        
        Args:
            username: Member number or username
            password: Password

        Returns:
            True if login successful without MFA

        Raises:
            MonaMFARequired: If OTP is required (normal flow)
            MonaAuthError: If login fails
        """
        session = await self._get_session()
        
        # Step 1: Initialize authentication
        auth_url = f"{BASE_URL}{AUTH_ENDPOINT}"
        headers = {
            **self._headers,
            "accept-api-version": "protocol=1.0,resource=2.1",
        }

        # Initial auth request to get callbacks structure
        async with session.post(auth_url, headers=headers, json={}) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.error("Auth init failed: %s - %s", response.status, text)
                raise MonaAuthError(f"Authentication init failed: {response.status}")
            
            data = await response.json()
            self._auth_id = data.get("authId")
            _LOGGER.debug("Auth initialized, got authId")

        # Step 2: Submit username/password
        # ForgeRock uses callbacks structure
        payload = {
            "authId": self._auth_id,
            "callbacks": [
                {
                    "type": "NameCallback",
                    "output": [{"name": "prompt", "value": "User Name"}],
                    "input": [{"name": "IDToken1", "value": username}]
                },
                {
                    "type": "PasswordCallback", 
                    "output": [{"name": "prompt", "value": "Password"}],
                    "input": [{"name": "IDToken2", "value": password}]
                }
            ]
        }

        async with session.post(auth_url, headers=headers, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.error("Login failed: %s - %s", response.status, text)
                raise MonaAuthError(f"Login failed: {response.status}")
            
            data = await response.json()
            
            # Check if we got a token (no MFA needed - unlikely)
            if "tokenId" in data:
                _LOGGER.info("Login successful without MFA")
                return True
            
            # Check for MFA requirement
            self._auth_id = data.get("authId")
            callbacks = data.get("callbacks", [])
            
            # Look for choice callback (SMS/Email selection)
            for callback in callbacks:
                cb_type = callback.get("type", "")
                
                # ChoiceCallback means user needs to select OTP delivery method
                if cb_type == "ChoiceCallback":
                    outputs = callback.get("output", [])
                    choices = []
                    for output in outputs:
                        if output.get("name") == "choices":
                            # Extract options like ["SMS", "Email"]
                            for idx, choice in enumerate(output.get("value", [])):
                                choices.append({"index": idx, "label": choice})
                    
                    if choices:
                        _LOGGER.debug("OTP method choice required: %s", choices)
                        raise MonaOTPMethodChoice("Choose OTP delivery method", self._auth_id, choices)
            
            # Look for OTP entry callback
            for callback in callbacks:
                cb_type = callback.get("type", "")
                if "otp" in cb_type.lower() or "code" in cb_type.lower() or callback.get("type") == "PasswordCallback":
                    # Check outputs for hints
                    outputs = callback.get("output", [])
                    for output in outputs:
                        if "otp" in str(output.get("value", "")).lower() or "code" in str(output.get("value", "")).lower():
                            _LOGGER.debug("MFA required, OTP callback detected")
                            raise MonaMFARequired("OTP required", self._auth_id)
            
            # If we see any callbacks that look like MFA
            if callbacks:
                _LOGGER.debug("MFA step detected with callbacks: %s", [c.get("type") for c in callbacks])
                raise MonaMFARequired("OTP required", self._auth_id)
            
            _LOGGER.warning("Unexpected auth response: %s", data)
            raise MonaAuthError("Unexpected authentication response")

    async def select_otp_method(self, method_index: int) -> bool:
        """Select OTP delivery method (SMS or Email).
        
        Args:
            method_index: Index of the selected method (0=first option, 1=second, etc.)

        Returns:
            True if OTP was sent successfully

        Raises:
            MonaMFARequired: When OTP entry is needed (expected)
            MonaAuthError: If selection fails
        """
        if not self._auth_id:
            raise MonaAuthError("No authentication in progress")

        session = await self._get_session()
        auth_url = f"{BASE_URL}{AUTH_ENDPOINT}"
        headers = {
            **self._headers,
            "accept-api-version": "protocol=1.0,resource=2.1",
        }

        # Submit choice via ChoiceCallback
        payload = {
            "authId": self._auth_id,
            "callbacks": [
                {
                    "type": "ChoiceCallback",
                    "output": [],
                    "input": [{"name": "IDToken1", "value": method_index}]
                }
            ]
        }

        async with session.post(auth_url, headers=headers, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.error("OTP method selection failed: %s - %s", response.status, text)
                raise MonaAuthError(f"OTP method selection failed: {response.status}")
            
            data = await response.json()
            
            # Should now need OTP entry
            if "tokenId" in data:
                _LOGGER.info("Authentication complete (no OTP needed)")
                self._auth_id = None
                return True
            
            self._auth_id = data.get("authId")
            callbacks = data.get("callbacks", [])
            
            if callbacks:
                _LOGGER.debug("OTP sent, now waiting for code entry")
                raise MonaMFARequired("OTP sent, enter code", self._auth_id)
            
            _LOGGER.warning("Unexpected response after OTP method selection: %s", data)
            raise MonaAuthError("Unexpected response after OTP method selection")

    async def submit_otp(self, otp: str) -> bool:
        """Submit OTP to complete authentication.
        
        Args:
            otp: The one-time password from SMS/Email

        Returns:
            True if successful

        Raises:
            MonaAuthError: If OTP validation fails
        """
        if not self._auth_id:
            raise MonaAuthError("No authentication in progress")

        session = await self._get_session()
        auth_url = f"{BASE_URL}{AUTH_ENDPOINT}"
        headers = {
            **self._headers,
            "accept-api-version": "protocol=1.0,resource=2.1",
        }

        # Submit OTP via callback
        payload = {
            "authId": self._auth_id,
            "callbacks": [
                {
                    "type": "PasswordCallback",
                    "output": [{"name": "prompt", "value": "One Time Password"}],
                    "input": [{"name": "IDToken1", "value": otp}]
                }
            ]
        }

        async with session.post(auth_url, headers=headers, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.error("OTP validation failed: %s - %s", response.status, text)
                raise MonaAuthError(f"OTP validation failed: {response.status}")
            
            data = await response.json()
            
            if "tokenId" in data:
                _LOGGER.info("OTP validation successful, session established")
                self._auth_id = None
                return True
            
            # Check if more steps needed
            if data.get("authId"):
                self._auth_id = data.get("authId")
                raise MonaAuthError("Additional authentication steps required")
            
            _LOGGER.error("OTP response: %s", data)
            raise MonaAuthError("OTP validation failed - invalid code")

    async def validate_session(self) -> bool:
        """Check if current session is valid.
        
        Returns:
            True if session is valid
        """
        try:
            # Try to fetch dashboard - if it works, session is valid
            await self.get_dashboard()
            return True
        except (MonaAuthError, MonaApiError):
            return False

    async def get_dashboard(self) -> dict[str, Any]:
        """Get member dashboard data.
        
        Returns:
            Dashboard data including account balance and investment earnings
            
        Raises:
            MonaAuthError: If not authenticated
            MonaApiError: If API call fails
        """
        session = await self._get_session()
        url = f"{BASE_URL}/api/proxy/memberdashboard"
        headers = {**self._headers, "referer": f"{BASE_URL}/"}

        async with session.get(url, headers=headers) as response:
            # Check for redirect to login (session expired)
            if response.status == 401 or response.history:
                _LOGGER.warning("Session expired or not authenticated")
                raise MonaAuthError("Session expired")
            
            if response.content_type != "application/json":
                text = await response.text()
                _LOGGER.error("Dashboard returned non-JSON: %s", text[:500])
                raise MonaAuthError("Not authenticated - received HTML")
            
            if response.status != 200:
                text = await response.text()
                _LOGGER.error("Dashboard request failed: %s - %s", response.status, text)
                raise MonaApiError(f"API error: {response.status}")
            
            data = await response.json()
            
            if data.get("status") != "success":
                raise MonaApiError(f"API error: {data.get('message', 'Unknown error')}")
            
            return data

    async def get_investments(self) -> dict[str, Any]:
        """Get member investment data.
        
        Returns:
            Investment data including options and performance returns
            
        Raises:
            MonaAuthError: If not authenticated
            MonaApiError: If API call fails
        """
        session = await self._get_session()
        url = f"{BASE_URL}/api/proxy/memberinvestment"
        headers = {**self._headers, "referer": f"{BASE_URL}/"}

        async with session.get(url, headers=headers) as response:
            if response.status == 401 or response.history:
                raise MonaAuthError("Session expired")
            
            if response.content_type != "application/json":
                text = await response.text()
                _LOGGER.error("Investment returned non-JSON: %s", text[:500])
                raise MonaAuthError("Not authenticated - received HTML")
            
            if response.status != 200:
                text = await response.text()
                raise MonaApiError(f"API error: {response.status}")
            
            data = await response.json()
            
            if data.get("status") != "success":
                raise MonaApiError(f"API error: {data.get('message', 'Unknown error')}")
            
            return data

    async def get_all_data(self) -> dict[str, Any]:
        """Fetch all data in one call.
        
        Returns:
            Combined data from dashboard and investments
        """
        dashboard = await self.get_dashboard()
        investments = await self.get_investments()
        
        # Extract key values from dashboard
        # Structure from HAR:
        # - membershipNumber: "902596212"
        # - preferredName: "Luke"
        # - investmentEarnings: 86972.53
        # - investmentEarningsFromDate/ToDate
        # - contributions: 21809.85
        # - contributionCap: 30000.00
        # - memberNumbers[].accounts[].balanceAmount: 515272.25
        # - memberNumbers[].accounts[].balanceDate: "2026-04-20"
        
        result = {
            "member_number": dashboard.get("membershipNumber"),
            "preferred_name": dashboard.get("preferredName"),
            "investment_earnings": dashboard.get("investmentEarnings"),
            "investment_earnings_from": dashboard.get("investmentEarningsFromDate"),
            "investment_earnings_to": dashboard.get("investmentEarningsToDate"),
            "contributions_ytd": dashboard.get("contributions"),
            "contribution_cap": dashboard.get("contributionCap"),
        }
        
        # Extract account balance from nested structure
        member_numbers = dashboard.get("memberNumbers", [])
        if member_numbers:
            accounts = member_numbers[0].get("accounts", [])
            if accounts:
                result["account_balance"] = accounts[0].get("balanceAmount")
                result["balance_date"] = accounts[0].get("balanceDate")
                result["account_name"] = accounts[0].get("accountName")
                
                # Get historical balances if available
                historical = accounts[0].get("historicalBalances", [])
                if historical:
                    result["historical_balances"] = historical
        
        # Extract investment returns from investments response
        # Structure has investmentOptions with returns
        investment_options = investments.get("investmentOptions", [])
        if investment_options:
            # Get the primary/default option returns
            primary = investment_options[0] if investment_options else {}
            result["investment_return_1yr"] = primary.get("return1yr")
            result["investment_return_3yr"] = primary.get("return3yr")
            result["investment_return_5yr"] = primary.get("return5yr")
            result["investment_return_7yr"] = primary.get("return7yr")
            result["investment_return_10yr"] = primary.get("return10yr")
            result["investment_return_fytd"] = primary.get("returnFytd")
            result["investment_option_name"] = primary.get("optionName")
            
        return result
