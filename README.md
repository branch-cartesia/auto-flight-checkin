# Auto Flight Check-In

Automatically checks in to flights at exactly 24 hours before departure.

## Setup

```bash
pip install -r requirements.txt
playwright install firefox
python setup.py
```

`setup.py` saves your name and preferred airline to `config.json` so you never have to type them again.

## Usage

```bash
# Check in now
python checkin.py ABC123

# Schedule for 24h before departure
python checkin.py ABC123 -d "2026-04-15 14:30"

# Dry run (fills form, doesn't submit)
python checkin.py ABC123 --dry-run
```

Just the confirmation code. That's it.

## Supported Airlines

- **Delta Airlines**

## How it works

1. Launches headless Firefox with stealth patches (bypasses Akamai bot detection)
2. Builds a session via Delta's homepage
3. Navigates to the check-in form, fills confirmation code, submits
4. Handles passenger selection and boarding pass retrieval
5. Screenshots saved to `./screenshots/` for verification

## All options

```
python checkin.py CONF_CODE [-d "YYYY-MM-DD HH:MM"] [--dry-run] [--airline delta] [--first-name X] [--last-name X] [-v]
```
