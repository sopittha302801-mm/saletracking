#!/usr/bin/env python3
"""
Fetches the published Google Sheet CSV for the Sale Tracking sheet and
rebuilds data/data.json in the shape the dashboard expects.

The sheet is organized as stacked sections, each starting with a category
row (e.g. "POSTPAY,,,,...") followed by a header row and then shop rows,
until the next category row or the end of the sheet.

IMPORTANT: the sheet grows its date columns over time (e.g. "Date 31",
"Date 1", "Date 2", ... one new column per day as the week progresses).
Column POSITIONS are therefore NOT stable — everything is located by
HEADER NAME instead, so this keeps working correctly as columns are added.
"""
import csv
import datetime
import io
import json
import os
import re
import sys

import requests

CSV_URL = os.environ.get(
    "SHEET_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRmXea3iF9clmxoUACQbJfMhRRbQasI5a2i3ceOYVPxSegUgq6gSTUxhSmo1TrGKFm4b3W0ksgG0hea/pub?output=csv",
)
KNOWN_CATEGORIES = {"POSTPAY", "TOL", "DEVICE"}
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "data.json")

# Week 1 is defined as starting on this date; each subsequent week is a
# consecutive 7-day block. Matches the business's week definition:
#   Week 1: Aug 31 - Sep 6   Week 2: Sep 7-13   Week 3: Sep 14-20
#   Week 4: Sep 21-27        Week 5: Sep 28 - Oct 4
WEEK1_START = datetime.date(2026, 8, 31)


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


def normalize_header(h):
    return re.sub(r"\s+", " ", (h or "").strip()).upper()


def classify_columns(header_row):
    """Locate each known column role by header text (not position).
    Returns (idx_map, date_cols) where idx_map maps role -> column index,
    and date_cols is a list of (index, day_number) in sheet order."""
    idx = {}
    date_cols = []
    for i, cell in enumerate(header_row):
        h = normalize_header(cell)
        if h == "SHOP CODE":
            idx["shopCode"] = i
        elif h == "SHOP NAME":
            idx["shopName"] = i
        elif h == "TYPE SHOP":
            idx["typeShop"] = i
        elif h.startswith("TARGET") and "DAY" in h and "WEEK" not in h:
            idx["targetDay"] = i
        elif h.startswith("TARGET") and "WEEK" in h:
            idx["targetWeek"] = i
        elif h.startswith("DATE"):
            m = re.search(r"(\d+)", h)
            if m:
                date_cols.append((i, int(m.group(1))))
        elif h.startswith("SUM"):
            idx["sumWk"] = i
        elif "ACH" in h:
            idx["pctAch"] = i
        elif h.startswith("GAP"):
            idx["gapWeek"] = i
        elif "RRWEEK" in h.replace(" ", ""):
            idx["rrWeek"] = i
        elif "LWEEK" in h.replace(" ", ""):
            idx["lWeek"] = i
        elif h == "WOW":
            idx["wow"] = i
    return idx, date_cols


def assign_calendar_dates(date_cols):
    """date_cols: [(col_index, day_number), ...] in left-to-right sheet
    order. Reconstructs actual calendar dates, starting from the month of
    WEEK1_START and rolling the month forward whenever the day number
    decreases (e.g. ...,30,31,1,2,... crossing a month boundary)."""
    result = []
    if not date_cols:
        return result
    year, month = WEEK1_START.year, WEEK1_START.month
    prev_day = None
    for i, day in date_cols:
        if prev_day is not None and day < prev_day:
            month += 1
            if month > 12:
                month = 1
                year += 1
        prev_day = day
        try:
            result.append((i, datetime.date(year, month, day)))
        except ValueError:
            continue  # skip invalid constructed dates defensively
    return result


def build_records(rows):
    records = []
    current_category = None
    col_idx = None
    dated_cols = None

    for row in rows:
        if not row:
            continue
        first = (row[0] or "").strip()

        if first.upper() in KNOWN_CATEGORIES and all(
            (c or "").strip() == "" for c in row[1:5]
        ):
            current_category = first.upper()
            col_idx = None
            dated_cols = None
            continue

        if first.upper() == "SHOP CODE":
            col_idx, date_cols = classify_columns(row)
            dated_cols = assign_calendar_dates(date_cols)
            continue

        if current_category is None or col_idx is None:
            continue
        if first == "":
            continue

        def get(key):
            i = col_idx.get(key)
            return row[i] if i is not None and i < len(row) else None

        shop_code = first
        if not shop_code:
            continue

        shop_name = (get("shopName") or "").strip()
        type_shop = (get("typeShop") or "").strip()
        target_day = to_number(get("targetDay")) or 0
        target_week = to_number(get("targetWeek")) or 0

        days = []
        for i, d in dated_cols:
            val = to_number(row[i]) if i < len(row) else None
            days.append({"date": d.isoformat(), "value": val or 0})

        sum_wk = to_number(get("sumWk")) or 0
        pct_ach = to_number(get("pctAch"))
        gap_week = to_number(get("gapWeek")) or 0
        rr_week = to_number(get("rrWeek")) or 0
        l_week = to_number(get("lWeek")) or 0
        wow = to_number(get("wow"))

        records.append(
            {
                "category": current_category,
                "shopCode": shop_code,
                "shopName": shop_name,
                "typeShop": type_shop,
                "targetDay": target_day,
                "targetWeek": target_week,
                "days": days,
                "sumWk1": sum_wk,
                "pctAch": pct_ach if pct_ach is not None else 0,
                "gapWeek": gap_week,
                "rrWeek": rr_week,
                "lWeek": l_week,
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
