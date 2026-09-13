#!/usr/bin/env python3
"""
Fetches the published 'raw' sheet CSV and builds data/indy_performance.json:
for each of 3 named shops, a per-staff breakdown of transaction count and
NET_AMOUNT sum, split by TYPE (column P), restricted to TYPE in
{GIA, DEVICE, PREPAY} only (other TYPE values like TOLUP or numeric SIM
promo codes are excluded per business rule).

Key fields used to join: SHOP_CODE, SHOP_NAME (via SALE_NAME/shop lookup),
SALE_CODE, SALE_NAME.
"""
import csv
import io
import json
import os
import sys

import requests

RAW_CSV_URL = os.environ.get(
    "RAW_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRmXea3iF9clmxoUACQbJfMhRRbQasI5a2i3ceOYVPxSegUgq6gSTUxhSmo1TrGKFm4b3W0ksgG0hea/pub?gid=56102410&single=true&output=csv",
)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "indy_performance.json")

# The 3 shops ("main topics") this page covers, keyed by SHOP_CODE.
TARGET_SHOPS = {
    "80100805": "True Shop Lotus's Phatthanakan",
    "80101296": "True Shop Paradise Park Srinakarin",
    "80101632": "True Shop Lotus's Bangna-trad",
}

# Only these TYPE values count; anything else (TOLUP, numeric SIM promo
# codes, etc.) is excluded.
VALID_TYPES = ["GIA", "DEVICE", "PREPAY"]


def normalize_code(code):
    """Normalize a SALE_CODE for matching: trim, uppercase, strip leading
    zeros from purely-numeric codes (raw sheet drops leading zeros in some
    rows but not others for the same person)."""
    if code is None:
        return ""
    c = code.strip().upper()
    if c.isdigit():
        c = c.lstrip("0") or "0"
    return c


def to_number(raw):
    if raw is None:
        return 0
    s = raw.strip().replace(",", "")
    if s == "":
        return 0
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return 0


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


def build_performance(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))

    # staff_data[shop_code][normalized_sale_code] = {
    #   saleCode, saleNameCounts: {name: n}, byType: {TYPE: {count, net}}
    # }
    staff_data = {shop_code: {} for shop_code in TARGET_SHOPS}

    for row in reader:
        shop_code = (row.get("SHOP_CODE") or "").strip()
        if shop_code not in TARGET_SHOPS:
            continue

        type_val = (row.get("TYPE") or "").strip().upper()
        if type_val not in VALID_TYPES:
            continue

        sale_code_raw = (row.get("SALE_CODE") or "").strip()
        sale_name = (row.get("SALE_NAME") or "").strip()
        if not sale_code_raw:
            continue

        qty = to_number(row.get("QTY"))
        net_amount = to_number(row.get("NET_AMOUNT"))

        key = normalize_code(sale_code_raw)
        shop_bucket = staff_data[shop_code]
        if key not in shop_bucket:
            shop_bucket[key] = {
                "saleCode": sale_code_raw,
                "saleNameCounts": {},
                "byType": {t: {"count": 0, "net": 0} for t in VALID_TYPES},
            }
        entry = shop_bucket[key]
        # Keep the shortest/most-recent-looking display SALE_CODE (some rows
        # have leading zeros, some don't — prefer the longer/original form).
        if len(sale_code_raw) >= len(entry["saleCode"]):
            entry["saleCode"] = sale_code_raw
        if sale_name:
            entry["saleNameCounts"][sale_name] = entry["saleNameCounts"].get(sale_name, 0) + 1
        entry["byType"][type_val]["count"] += qty
        entry["byType"][type_val]["net"] += net_amount

    # Build final structure
    shops_out = []
    for shop_code, shop_name in TARGET_SHOPS.items():
        staff_list = []
        shop_totals = {t: {"count": 0, "net": 0} for t in VALID_TYPES}

        for key, entry in staff_data[shop_code].items():
            # pick the most frequently seen display name for this sale code
            best_name = max(entry["saleNameCounts"].items(), key=lambda kv: kv[1])[0] if entry["saleNameCounts"] else entry["saleCode"]
            total_count = sum(entry["byType"][t]["count"] for t in VALID_TYPES)
            total_net = sum(entry["byType"][t]["net"] for t in VALID_TYPES)
            staff_list.append(
                {
                    "saleCode": entry["saleCode"],
                    "saleName": best_name,
                    "byType": entry["byType"],
                    "totalCount": total_count,
                    "totalNet": total_net,
                }
            )
            for t in VALID_TYPES:
                shop_totals[t]["count"] += entry["byType"][t]["count"]
                shop_totals[t]["net"] += entry["byType"][t]["net"]

        staff_list.sort(key=lambda s: s["totalNet"], reverse=True)

        shops_out.append(
            {
                "shopCode": shop_code,
                "shopName": shop_name,
                "staff": staff_list,
                "shopTotals": {
                    "byType": shop_totals,
                    "totalCount": sum(shop_totals[t]["count"] for t in VALID_TYPES),
                    "totalNet": sum(shop_totals[t]["net"] for t in VALID_TYPES),
                },
            }
        )

    return shops_out


def main():
    try:
        text = fetch_csv(RAW_CSV_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR fetching CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    shops = build_performance(text)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(shops, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total_staff = sum(len(s["staff"]) for s in shops)
    print(f"Wrote {len(shops)} shops, {total_staff} staff records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
