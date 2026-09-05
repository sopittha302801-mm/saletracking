#!/usr/bin/env python3
"""
Fetches the published Google Sheet CSV for the Sale Tracking sheet and
rebuilds data/data.json in the shape the dashboard expects.

The sheet is organized as stacked sections, each starting with a category
row (e.g. "POSTPAY,,,,...") followed by a header row and then shop rows,
until the next category row or the end of the sheet.
"""
import csv
import io
import json
import os
import sys

import requests

CSV_URL = os.environ.get(
    "SHEET_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRmXea3iF9clmxoUACQbJfMhRRbQasI5a2i3ceOYVPxSegUgq6gSTUxhSmo1TrGKFm4b3W0ksgG0hea/pub?output=csv",
)
KNOWN_CATEGORIES = {"POSTPAY", "TOL", "DEVICE"}
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "data.json")


def to_number(raw):
    """Parse a spreadsheet cell into a number, or None if blank/invalid."""
    if raw is None:
        return None
    s = raw.strip().replace(",", "")
    if s == "" or s.upper().startswith("#DIV"):
        return None
    s = s.rstrip("%")
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def fetch_csv(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/csv,*/*",
    }
    resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
    print(f"DEBUG: GET {url} -> HTTP {resp.status_code}, content-type={resp.headers.get('content-type')}", file=sys.stderr)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    if "<html" in text[:200].lower():
        print("DEBUG: response looks like HTML, not CSV. First 500 chars:", file=sys.stderr)
        print(text[:500], file=sys.stderr)
        raise ValueError("Sheet did not return CSV (got HTML) — check the sheet is published to web")
    return text


def parse_rows(text):
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader]


def build_records(rows):
    records = []
    current_category = None
    header = None

    for row in rows:
        if not row:
            continue
        first = (row[0] or "").strip()

        if first.upper() in KNOWN_CATEGORIES and all(
            (c or "").strip() == "" for c in row[1:5]
        ):
            current_category = first.upper()
            header = None
            continue

        if first.upper() == "SHOP CODE":
            header = row
            continue

        if current_category is None or header is None:
            continue

        if first == "" :
            continue

        # Expect: SHOP CODE, SHOP NAME, TYPE SHOP, TARGET/DAY, TARGET WEEK1,
        #         Date1..Date8, sum wk1, %ACH WEEK1, Gap Week, RRWeek, LWeek, WOW
        try:
            shop_code = row[0].strip()
            shop_name = row[1].strip()
            type_shop = row[2].strip()
            target_day = to_number(row[3])
            target_week = to_number(row[4])
            days = [to_number(row[i]) for i in range(5, 13)]
            days = [d if d is not None else 0 for d in days[:4]]  # Date1-4 only, matching dashboard
            sum_wk1 = to_number(row[13])
            pct_ach_raw = to_number(row[14])
            gap_week = to_number(row[15])
            rr_week = to_number(row[16])
            l_week = to_number(row[17])
            wow = to_number(row[18]) if len(row) > 18 else None
        except IndexError:
            continue

        if not shop_code:
            continue

        records.append(
            {
                "category": current_category,
                "shopCode": shop_code,
                "shopName": shop_name,
                "typeShop": type_shop,
                "targetDay": target_day or 0,
                "targetWeek": target_week or 0,
                "days": days,
                "sumWk1": sum_wk1 or 0,
                "pctAch": pct_ach_raw if pct_ach_raw is not None else 0,
                "gapWeek": gap_week or 0,
                "rrWeek": rr_week or 0,
                "lWeek": l_week or 0,
                "wow": wow,
            }
        )

    return records


def main():
    try:
        text = fetch_csv(CSV_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR fetching CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    rows = parse_rows(text)
    records = build_records(rows)

    if not records:
        print("ERROR: no records parsed from sheet, aborting to avoid wiping data.json", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
