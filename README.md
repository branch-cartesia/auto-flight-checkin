# Auto Flight Check-In

Checks in to Delta flights automatically at 24h before departure using browser automation (Firefox + stealth).

## Setup

```bash
pip install -r requirements.txt
playwright install firefox
python setup.py  # one-time: saves your name/airline to config.json
```

## Usage

```bash
python checkin.py ABC123                         # check in now
python checkin.py ABC123 -d "2026-04-15 14:30"   # schedule for 24h before departure
python checkin.py ABC123 --dry-run               # fill form, don't submit
```

Just the confirmation code. Name/airline loaded from config.

## How it works

Firefox with playwright-stealth bypasses Akamai bot detection on Delta's PCCOciWeb legacy check-in endpoint. Visits homepage first for session cookies, navigates to check-in form, fills confirmation code, submits, handles passenger selection and boarding pass. Screenshots saved to `./screenshots/`.

## All options

```
python checkin.py CONF_CODE [-d "YYYY-MM-DD HH:MM"] [--dry-run] [--airline delta] [--first-name X] [--last-name X] [--airport JFK] [-v]
```
