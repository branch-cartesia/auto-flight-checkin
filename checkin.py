#!/usr/bin/env python3
"""
Auto Flight Check-In Tool

Automatically checks in to flights at exactly 24 hours before departure.
Currently supports Delta Airlines.

Usage:
    # Check in immediately:
    python checkin.py ABC123

    # Schedule check-in for a specific departure time:
    python checkin.py ABC123 --departure "2026-04-01 14:30"

    # Dry run (fills form but doesn't submit):
    python checkin.py ABC123 --dry-run
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    """Load saved config from setup.py, if it exists."""
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("auto-checkin")

SCREENSHOTS_DIR = Path("screenshots")

# Delta's legacy check-in app (Struts/Angular hybrid). Firefox bypasses Akamai
# bot detection on this endpoint, unlike the SPA at /flight-search/check-in.
DELTA_CHECKIN_URL = "https://www.delta.com/PCCOciWeb/findBy.action"


def _setup_browser(playwright, headless=True):
    """Launch Firefox with stealth for Delta check-in."""
    from playwright_stealth import Stealth

    stealth = Stealth()
    browser = playwright.firefox.launch(
        headless=headless,
        firefox_user_prefs={
            "dom.webdriver.enabled": False,
            "useAutomationExtension": False,
        },
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
    )
    # Set US location cookie to avoid geo-redirects
    context.add_cookies([
        {"name": "location", "value": "US++NEW+YORK", "domain": ".delta.com", "path": "/"},
    ])
    page = context.new_page()
    stealth.apply_stealth_sync(page)
    return browser, context, page


def checkin_delta(confirmation: str, first_name: str, last_name: str,
                  dry_run: bool = False, headless: bool = True,
                  max_retries: int = 3) -> bool:
    """
    Check in to Delta via browser automation (Firefox + stealth).

    The tool uses Delta's PCCOciWeb endpoint which is a legacy Angular app.
    Firefox with stealth bypasses Akamai bot detection on this endpoint.

    Args:
        confirmation: 6-character confirmation code (record locator)
        first_name: Passenger first name (stored but not always needed by form)
        last_name: Passenger last name (stored but not always needed by form)
        dry_run: If True, fill form but don't submit
        headless: Run browser without visible window
        max_retries: Number of retry attempts
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

    SCREENSHOTS_DIR.mkdir(exist_ok=True)

    for attempt in range(1, max_retries + 1):
        log.info(f"Attempt {attempt}/{max_retries} — "
                 f"{first_name} {last_name} ({confirmation})")
        try:
            with sync_playwright() as p:
                browser, context, page = _setup_browser(p, headless=headless)
                try:
                    result = _delta_checkin_flow(
                        page, confirmation, first_name, last_name, dry_run
                    )
                    if result:
                        return True
                finally:
                    browser.close()
        except PwTimeout as e:
            log.warning(f"Timeout on attempt {attempt}: {e}")
        except Exception as e:
            log.error(f"Error on attempt {attempt}: {e}")

        if attempt < max_retries:
            wait = 5 * attempt
            log.info(f"Retrying in {wait}s...")
            time.sleep(wait)

    log.error("All attempts exhausted.")
    return False


def _delta_checkin_flow(page, confirmation, first_name, last_name, dry_run):
    """Execute the Delta check-in flow via PCCOciWeb."""

    # Step 1: Build session via homepage (needed for Akamai cookies)
    log.info("Building session via homepage...")
    page.goto("https://www.delta.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)

    # Step 2: Navigate to check-in page
    log.info(f"Navigating to {DELTA_CHECKIN_URL}")
    page.goto(DELTA_CHECKIN_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(5000)

    page.screenshot(path=str(SCREENSHOTS_DIR / "01_landing.png"))
    page_url = page.url
    page_text = page.inner_text("body").lower()
    log.info(f"Landed on: {page_url}")

    # Check for blocks
    if any(x in page_text for x in [
        "access denied", "thanks for your patience", "temporary technical issues",
    ]):
        log.warning("Blocked by bot detection or site maintenance")
        page.screenshot(path=str(SCREENSHOTS_DIR / "blocked.png"))
        return False

    # Verify we're on the check-in page
    if "check in" not in page_text:
        log.warning(f"Unexpected page. URL: {page_url}")
        page.screenshot(path=str(SCREENSHOTS_DIR / "unexpected.png"))
        return False

    log.info("Check-in page loaded successfully")

    # Step 3: Wait for the Angular form to render, then fill confirmation
    # Wait for the confirmation input to appear (up to 15s)
    conf_filled = False
    try:
        page.wait_for_selector("#inputConfirmation, input[name='recordLocator']",
                               state="visible", timeout=15000)
    except Exception:
        pass  # Fall through to selector loop

    for sel in [
        "#inputConfirmation",
        "input[name='recordLocator']",
        "input[name='confirmationNumber']",
        "#confirmation",
    ]:
        try:
            elem = page.locator(sel)
            if elem.count() > 0 and elem.first.is_visible(timeout=1000):
                elem.first.click()
                elem.first.fill(confirmation.upper())
                conf_filled = True
                log.info(f"Filled confirmation: {sel}")
                break
        except Exception:
            continue

    if not conf_filled:
        # Fallback: try by label
        try:
            elem = page.get_by_label("Confirmation", exact=False)
            if elem.count() > 0:
                elem.first.fill(confirmation.upper())
                conf_filled = True
                log.info("Filled confirmation by label")
        except Exception:
            pass

    if not conf_filled:
        page.screenshot(path=str(SCREENSHOTS_DIR / "error_no_conf.png"))
        log.error("Could not find confirmation number field")
        return False

    # Step 4: Fill last name if field exists
    # The confirmation tab may not have a last name field — Delta uses
    # confirmation code alone on the PCCOciWeb form
    ln_selectors = [
        "#ociLastname", "input[name='lastName']",
        "#lastName", "#txtLastName",
    ]
    for sel in ln_selectors:
        try:
            elem = page.locator(sel)
            if elem.count() > 0 and elem.first.is_visible():
                elem.first.click()
                elem.first.fill(last_name)
                log.info(f"Filled last name: {sel}")
                break
        except Exception:
            continue

    page.screenshot(path=str(SCREENSHOTS_DIR / "02_filled.png"))

    if dry_run:
        log.info("DRY RUN — form filled, not submitting")
        return True

    # Step 5: Submit the form
    # Scroll back to top first — filling by label can scroll past the button
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)

    submit_clicked = False
    # Try Playwright's role-based locator first (most reliable)
    try:
        btn = page.get_by_role("button", name="SEARCH")
        if btn.count() > 0:
            btn.first.scroll_into_view_if_needed()
            btn.first.click()
            submit_clicked = True
            log.info("Clicked SEARCH button (by role)")
    except Exception:
        pass

    if not submit_clicked:
        submit_selectors = [
            "button:has-text('SEARCH')",
            "#checkInButton",
            "input[value='SEARCH']",
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Check In')",
        ]
        for sel in submit_selectors:
            try:
                btn = page.locator(sel)
                if btn.count() > 0:
                    btn.first.scroll_into_view_if_needed()
                    if btn.first.is_visible():
                        btn.first.click()
                        submit_clicked = True
                        log.info(f"Clicked submit: {sel}")
                        break
            except Exception:
                continue

    if not submit_clicked:
        page.screenshot(path=str(SCREENSHOTS_DIR / "error_no_submit.png"))
        log.error("Could not find submit button")
        return False

    # Step 6: Wait for response
    log.info("Waiting for response...")
    page.wait_for_timeout(5000)
    page.screenshot(path=str(SCREENSHOTS_DIR / "03_loading.png"))

    # Wait for loading to finish (up to 20s)
    for _ in range(4):
        result_text = page.inner_text("body").lower()
        if "just a moment" in result_text or "finding your trip" in result_text:
            page.wait_for_timeout(5000)
        else:
            break

    page.screenshot(path=str(SCREENSHOTS_DIR / "04_result.png"))
    result_text = page.inner_text("body").lower()

    # Step 7: Handle the result
    # Extract any visible error/alert messages from the page
    error_msgs = []
    for sel in [".error-message", ".alert", ".errorMsg", ".oci-error",
                "[class*='error']", "[class*='alert']", "[role='alert']"]:
        try:
            elems = page.locator(sel)
            for i in range(min(elems.count(), 5)):
                txt = elems.nth(i).inner_text().strip()
                if txt and len(txt) > 5:
                    error_msgs.append(txt)
        except Exception:
            pass

    if any(x in result_text for x in [
        "please correct", "we were unable", "not found", "invalid",
        "unable to locate", "no itinerary", "please try again",
        "not eligible", "outside", "not available",
    ]):
        page.screenshot(path=str(SCREENSHOTS_DIR / "04_validation_error.png"))
        if error_msgs:
            for msg in error_msgs:
                log.warning(f"Delta says: {msg}")
        else:
            log.warning("Check-in error — check screenshots/04_validation_error.png for details")

        # Hint: if the flight is >24h away, suggest scheduling
        if any(x in result_text for x in ["not eligible", "outside", "24 hour",
                                            "not available", "not yet"]):
            log.info("Hint: check-in may not be open yet. Use -d to schedule: "
                     "python checkin.py CODE -d 'YYYY-MM-DD HH:MM'")
        return False

    # Check for success — passenger selection or boarding pass
    if any(x in result_text for x in [
        "select passengers", "passenger details", "select all",
    ]):
        log.info("Got to passenger selection — selecting all passengers...")
        # Try to select all passengers and continue
        select_all = page.locator("input[type='checkbox']")
        if select_all.count() > 0:
            for i in range(select_all.count()):
                try:
                    if select_all.nth(i).is_visible() and not select_all.nth(i).is_checked():
                        select_all.nth(i).check()
                except Exception:
                    pass

        # Click continue/check-in
        for sel in ["button:has-text('Check In')", "button:has-text('Continue')",
                     "button:has-text('CONTINUE')", "button:has-text('CHECK IN')"]:
            try:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    log.info(f"Clicked: {sel}")
                    page.wait_for_timeout(10000)
                    break
            except Exception:
                continue

        page.screenshot(path=str(SCREENSHOTS_DIR / "05_after_continue.png"))
        result_text = page.inner_text("body").lower()

    # Check for final success
    if any(x in result_text for x in [
        "boarding pass", "checked in", "check-in complete",
        "you're checked in", "you are checked in",
    ]):
        log.info("CHECK-IN SUCCESSFUL!")
        page.screenshot(path=str(SCREENSHOTS_DIR / "06_success.png"), full_page=True)
        return True

    # Check for seat assignment / extras offered
    if any(x in result_text for x in ["seat", "upgrade", "bag"]):
        log.info("Check-in proceeding — handling extras...")
        # Skip optional extras
        for sel in ["button:has-text('No Thanks')", "button:has-text('Skip')",
                     "button:has-text('Continue')", "button:has-text('CONTINUE')"]:
            try:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    page.wait_for_timeout(5000)
                    break
            except Exception:
                continue

        page.screenshot(path=str(SCREENSHOTS_DIR / "06_extras.png"))

    log.warning("Result unclear — check screenshots in ./screenshots/")
    return True


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def schedule_checkin(airline: str, confirmation: str, first_name: str,
                     last_name: str, departure_str: str,
                     dry_run: bool = False):
    """Schedule check-in for 24 hours before departure."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    departure = datetime.strptime(departure_str, "%Y-%m-%d %H:%M")
    # Check-in opens 24h before departure. Start 5s early for pole position.
    checkin_time = departure - timedelta(hours=24) - timedelta(seconds=5)

    now = datetime.now()
    if checkin_time <= now:
        log.info("Check-in time already passed — running immediately!")
        run_checkin(airline, confirmation, first_name, last_name, dry_run)
        return

    wait = checkin_time - now
    log.info(f"Departure:  {departure_str}")
    log.info(f"Check-in:   {checkin_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Waiting:    {wait}")
    log.info("Keep this process running! It will check in automatically.")

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_checkin, "date", run_date=checkin_time,
        args=[airline, confirmation, first_name, last_name, dry_run],
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


def run_checkin(airline: str, confirmation: str, first_name: str,
                last_name: str, dry_run: bool = False) -> bool:
    """Run check-in for the specified airline."""
    if airline.lower() != "delta":
        log.error(f"Unsupported airline: {airline}. Supported: [delta]")
        return False

    return checkin_delta(
        confirmation=confirmation,
        first_name=first_name,
        last_name=last_name,
        dry_run=dry_run,
        headless=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Auto Flight Check-In Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("confirmation",
                        help="6-character confirmation code")
    parser.add_argument("--departure", "-d",
                        help="Departure time as 'YYYY-MM-DD HH:MM' (local). "
                             "Auto-schedules check-in for 24h before this time.")
    parser.add_argument("--airline", choices=["delta"], default="delta",
                        help="Airline (default: delta)")
    parser.add_argument("--first-name", default="",
                        help="Passenger first name (optional)")
    parser.add_argument("--last-name", default="",
                        help="Passenger last name (optional)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fill form but don't submit")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Merge saved config with CLI args (CLI wins)
    config = load_config()
    first_name = args.first_name or config.get("first_name", "")
    last_name = args.last_name or config.get("last_name", "")
    airline = args.airline or config.get("airline", "delta")

    if args.departure:
        schedule_checkin(
            airline=airline, confirmation=args.confirmation,
            first_name=first_name, last_name=last_name,
            departure_str=args.departure, dry_run=args.dry_run,
        )
    else:
        success = run_checkin(
            airline=airline, confirmation=args.confirmation,
            first_name=first_name, last_name=last_name,
            dry_run=args.dry_run,
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
