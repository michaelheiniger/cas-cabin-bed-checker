"""
Check bed availability at Konkordiahütte SAC on hut-reservation.org.

Navigates the booking wizard, selects the target date and number of
dormitory beds, then reports availability.

Requirements:
    pip install playwright
    playwright install firefox
"""

import sys
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

HUT_URL = "https://www.hut-reservation.org/reservation/book-hut/12/wizard"
TARGET_DATE = datetime(2026, 5, 25)
DEPARTURE_DATE = TARGET_DATE + timedelta(days=1)
NUM_BEDS = 1


def check_availability():
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        page = browser.new_page()

        print(f"Checking availability at Konkordiahütte SAC")
        print(f"  Date:  {TARGET_DATE.strftime('%d.%m.%Y')} – {DEPARTURE_DATE.strftime('%d.%m.%Y')}")
        print(f"  Beds:  {NUM_BEDS} (Massenlager / dormitory)")
        print()

        # --- Load the booking wizard ---
        page.goto(HUT_URL, wait_until="networkidle")
        time.sleep(2)

        # --- Step 1: Select dates in the calendar ---
        arrival_label = TARGET_DATE.strftime("%B %d, %Y")
        departure_label = DEPARTURE_DATE.strftime("%B %d, %Y")
        print(arrival_label)
        print(departure_label)

        page.click("mat-datepicker-toggle button")
        time.sleep(1)

        # Navigate to the correct month if needed
        _navigate_to_month(page, TARGET_DATE)

        page.click(f"button[aria-label='{arrival_label}']")
        time.sleep(0.5)

        # If departure is in the next month, navigate forward
        if DEPARTURE_DATE.month != TARGET_DATE.month or DEPARTURE_DATE.year != TARGET_DATE.year:
            _navigate_to_month(page, DEPARTURE_DATE)

        page.click(f"button[aria-label='{departure_label}']")
        time.sleep(1)

        # Close the calendar overlay
        close_btn = page.query_selector("button.mat-datepicker-close-button")
        if close_btn and close_btn.is_visible():
            close_btn.click()
            time.sleep(0.5)

        # --- Step 2: Set number of dormitory beds ---
        # The persons panel auto-expands after date selection
        panel_header = page.query_selector("#mat-expansion-panel-header-0")
        if panel_header and panel_header.get_attribute("aria-expanded") != "true":
            panel_header.click()
            time.sleep(1)

        # Fill the dormitory (Massenlager) person count via JS to work with Angular
        page.evaluate(f"""
            const input = document.querySelector('input[data-test="0-people-input"]');
            if (input) {{
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(input, '{NUM_BEDS}');
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        """)
        time.sleep(2)

        # --- Step 3: Read availability results ---
        body_text = page.inner_text("body")

        # Extract the availability table for the target date
        date_str = TARGET_DATE.strftime("%d.%m.%Y")
        available = _parse_availability(body_text, date_str)

        print("=" * 50)
        print(f"  Results for {date_str}")
        print("=" * 50)

        if available is None:
            print("  Could not parse availability from the page.")
            print("  Raw page text (excerpt):")
            print(body_text[:1500])
            browser.close()
            return 1

        total_free = available.get("total", "?")
        dorm_free = available.get("Massenlager", "?")
        room_free = available.get("2-er Zimmer", "?")

        print(f"  Total free beds:      {total_free}")
        print(f"  Massenlager (dorm):   {dorm_free}")
        print(f"  2-er Zimmer (room):   {room_free}")
        print()

        try:
            dorm_int = int(dorm_free)
        except (ValueError, TypeError):
            dorm_int = -1

        if dorm_int >= NUM_BEDS:
            print(f"  >>> AVAILABLE – {dorm_int} dormitory beds free (need {NUM_BEDS})")
        elif dorm_int == 0:
            print(f"  >>> NOT AVAILABLE – 0 dormitory beds free")
            if "Warteliste" in body_text:
                print("  >>> Waitlist option is offered by the hut.")
        else:
            print(f"  >>> NOT ENOUGH – only {dorm_int} dormitory beds free (need {NUM_BEDS})")

        browser.close()
        return 0 if dorm_int >= NUM_BEDS else 1


def _navigate_to_month(page, target: datetime):
    """Click the next/previous month buttons until the calendar shows the target month."""
    for _ in range(24):  # safety limit
        period_btn = page.query_selector("button.mat-calendar-period-button")
        if not period_btn:
            break
        label = period_btn.inner_text().strip()  # e.g. "4/2026"
        try:
            parts = label.split("/")
            cal_month = int(parts[0])
            cal_year = int(parts[1])
        except (IndexError, ValueError):
            break

        if cal_year == target.year and cal_month == target.month:
            return  # already on the right month

        if (cal_year, cal_month) < (target.year, target.month):
            page.click("button.mat-calendar-next-button")
        else:
            page.click("button.mat-calendar-previous-button")
        time.sleep(0.5)


def _parse_availability(text: str, date_str: str) -> dict | None:
    """Parse the availability summary from the page body text.

    The page renders a small table like:
        Datum           Freie Plätze
        Sa 25.04.2026   0 !
        Massenlager:    0 !
        2-er Zimmer:    0
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = {}

    # Find the line with the target date
    date_idx = None
    for i, line in enumerate(lines):
        if date_str in line:
            date_idx = i
            break

    if date_idx is None:
        return None

    # The number right after the date line is the total free beds
    for j in range(date_idx + 1, min(date_idx + 3, len(lines))):
        val = lines[j].rstrip("!").strip()
        if val.isdigit():
            result["total"] = int(val)
            break

    # Look for category lines after the date
    for j in range(date_idx, min(date_idx + 10, len(lines))):
        line = lines[j]
        if "Massenlager" in line:
            # Next line(s) should have the number
            for k in range(j + 1, min(j + 3, len(lines))):
                val = lines[k].rstrip("!").strip()
                if val.isdigit():
                    result["Massenlager"] = int(val)
                    break
            # Also check same line: "Massenlager:  0 !"
            parts = line.split(":")
            if len(parts) > 1:
                val = parts[-1].rstrip("!").strip()
                if val.isdigit():
                    result["Massenlager"] = int(val)

        if "2-er Zimmer" in line:
            for k in range(j + 1, min(j + 3, len(lines))):
                val = lines[k].rstrip("!").strip()
                if val.isdigit():
                    result["2-er Zimmer"] = int(val)
                    break
            parts = line.split(":")
            if len(parts) > 1:
                val = parts[-1].rstrip("!").strip()
                if val.isdigit():
                    result["2-er Zimmer"] = int(val)

    return result if result else None


if __name__ == "__main__":
    sys.exit(check_availability())
