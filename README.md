# Mona - Super Fund Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration to fetch your super fund data including account balance and investment performance.

## Features

- **Account Balance**: Current super balance with date
- **Investment Earnings**: Year-to-date investment returns in dollars
- **Contributions**: YTD contributions and contribution cap tracking
- **Investment Performance**: 1, 3, 5, 7, 10 year and FYTD returns as percentages

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → Custom repositories
3. Add `https://github.com/ekul135/mona` with category "Integration"
4. Install "Mona"
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/mona` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Mona"
3. Enter your member portal credentials
4. An OTP verification code will be sent to your registered phone/email
5. Enter the OTP to complete setup

## Sensors Created

| Sensor | Description | Unit |
|--------|-------------|------|
| Account Balance | Current super balance | AUD |
| Investment Earnings | Investment returns YTD | AUD |
| Contributions YTD | Total contributions this financial year | AUD |
| Contribution Cap | Concessional contribution cap | AUD |
| 1 Year Return | Investment option 1 year return | % |
| 3 Year Return | Investment option 3 year return | % |
| 5 Year Return | Investment option 5 year return | % |
| 7 Year Return | Investment option 7 year return | % |
| 10 Year Return | Investment option 10 year return | % |
| FYTD Return | Financial year to date return | % |

## Session Management

- Data is polled every 15 minutes to keep the session alive (20-minute timeout)
- If HA restarts and session expires, you'll receive a notification to re-authenticate
- Re-authentication only requires entering the OTP - your credentials are securely stored

## Troubleshooting

### "Session expired - please re-authenticate"

This notification appears when your session has expired (e.g., after HA restart longer than 20 minutes). Click the notification and enter the new OTP sent to your phone/email.

### "Unable to connect"

Check your internet connection. The service may also be undergoing maintenance.

## Privacy & Security

- Credentials are stored encrypted in Home Assistant's config
- Session cookies are stored to maintain login between polls
- All communication is over HTTPS
- No data is sent to any third parties

## Disclaimer

This is an unofficial integration. Use at your own risk.

## License

MIT License - see [LICENSE](LICENSE) for details.
