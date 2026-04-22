"""Constants for the Mona integration."""
from datetime import timedelta

DOMAIN = "mona"

# Configuration keys
CONF_USERNAME = "username"
CONF_OTP = "otp"
CONF_MEMBER_NUMBER = "member_number"
CONF_SESSION_COOKIES = "session_cookies"

# API
BASE_URL = "https://member.secure.australianretirementtrust.com.au"
AUTH_ENDPOINT = "/api/feature/mfa/config/json/realms/root/realms/SharedLogin/authenticate"

# Update interval - 15 minutes to keep session alive (20 min timeout)
DEFAULT_SCAN_INTERVAL = timedelta(minutes=15)
