#!/usr/bin/env python3
"""One-time setup — saves your info so you don't have to type it every time."""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def setup():
    print("Auto Flight Check-In — Setup")
    print("=" * 40)
    print("This saves your info locally so you only need your confirmation code to check in.\n")

    config = {}
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        print(f"Existing config found. Press Enter to keep current values.\n")

    config["first_name"] = (
        input(f"First name [{config.get('first_name', '')}]: ").strip()
        or config.get("first_name", "")
    )
    config["last_name"] = (
        input(f"Last name [{config.get('last_name', '')}]: ").strip()
        or config.get("last_name", "")
    )
    config["airline"] = (
        input(f"Default airline [{config.get('airline', 'delta')}]: ").strip()
        or config.get("airline", "delta")
    )
    config["departure_airport"] = (
        input(f"Home airport code, e.g. JFK, LAX [{config.get('departure_airport', '')}]: ").strip()
        or config.get("departure_airport", "")
    )

    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"\nSaved to {CONFIG_PATH}")
    print(f"\nYou're all set! Usage:")
    print(f"  python checkin.py ABC123                         # check in now")
    print(f"  python checkin.py ABC123 -d '2026-04-15 14:30'   # schedule for 24h before departure")


if __name__ == "__main__":
    setup()
