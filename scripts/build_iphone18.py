#!/usr/bin/env python3
"""
Fetches the 'raw' transaction sheet and a stock-balance sheet, and builds
data/iphone18.json for the iPhone 18 dashboard page:

  1. Per-staff QTY and NET_AMOUNT for iPhone 18 Pro / iPhone 18 Pro Max,
     restricted to ORDER_DATE between Sep 18 and Sep 30 (inclusive),
     grouped by shop.
  2. Per-shop summary comparing units sold (all-time from 'raw', not
     date-restricted) vs current stock balance, per model.

Key fields used to join: SHOP_CODE, SHOP_NAME (looked up), SALE_CODE,
SALE_NAME (from 'raw'); SHOP_CODE + product name (from the stock sheet).
"""
import csv
import datetime
import io
import json
import os
import re
import sys

import requests

RAW_CSV_URL = os.environ.get(
    "RAW_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRmXea3iF9clmxoUACQbJfMhRRbQasI5a2i3ceOYVPxSegUgq6gSTUxhSmo1TrGKFm4b3W0ksgG0hea/pub?gid=56102410&single=true&output=csv",
)
STOCK_CSV_URL = os.environ.get(
    "STOCK_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRmXea3iF9clmxoUACQbJfMhRRbQasI5a2i3ceOYVPxSegUgq6gSTUxhSmo1TrGKFm4b3W0ksgG0hea/pub?gid=1143369747&single=true&output=csv",
)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "iphone18.json")

MODELS = ["iPhone 18 Pro Max", "iPhone 18 Pro"]  # order matters: check Pro Max first

DATE_START = datetime.date(2026, 9, 18)
DATE_END = datetime.date(2026, 9, 30)

# Shop code -> display name lookup (extend as needed; falls back to the
# shop code itself if not listed, so new shops still show up).
SHOP_NAMES = {
    "80100805": "True Shop Lotus's Phatthanakan",
    "80101296": "True Shop Paradise Park Srinakarin",
    "80101632": "True Shop Lotus's Bangna-trad",
}


def normalize_code(code):
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


def match_model(text):
    """Returns the matched model label, or None. Checks 'Pro Max' before
    'Pro' since 'Pro' is a substring of 'Pro Max'."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text).upper()
    if "18" not in t:
        return None
    if "PRO MAX" in t or "PROMAX" in t:
        return "iPhone 18 Pro Max"
    if "PRO" in t:
        return "iPhone 18 Pro"
    return None


def parse_order_date(raw):
    """raw looks like '9/5/2026 18:24' or '9/1/2026 13:37:29' (M/D/YYYY ...)."""
    if not raw:
        return None
    date_part = raw.strip().split(" ")[0]
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue
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


def find_col(fieldnames, *keywords):
    """Find the first fieldname containing all given keywords (case-insensitive)."""
    if not fieldnames:
        return None
    for fn in fieldnames:
        if fn is None:
            continue
        up = fn.upper()
        if all(kw.upper() in up for kw in keywords):
            return fn
    return None


def match_suplife(text):
    """True if DESCRIPTION starts with 'ACC,H/S,SUPLIFE' (case-insensitive,
    tolerant of leading whitespace)."""
    if not text:
        return False
    return text.strip().upper().startswith("ACC,H/S,SUPLIFE")


def suplife_weight(text):
    """Suplife rows normally count as 1. If the description also mentions
    'BOX SET', that row counts as 3 instead. Returns 0 if not a Suplife
    row at all."""
    if not match_suplife(text):
        return 0
    if "BOX SET" in text.strip().upper():
        return 3
    return 1


def build_staff_sales(raw_csv_text):
    """Returns: { shop_code: { normalized_sale_code: {saleCode, saleNameCounts,
    byModel: {model: {qty, net}}} } }, an all-time sold total per shop+model
    (not date-restricted, for the sold-vs-stock comparison), and a per-shop
    Suplife count restricted to the same Sep 18-30 window as the staff
    breakdown."""
    reader = csv.DictReader(io.StringIO(raw_csv_text))
    fieldnames = reader.fieldnames or []

    col_shop = find_col(fieldnames, "SHOP", "CODE") or "SHOP_CODE"
    col_sale_code = find_col(fieldnames, "SALE", "CODE") or "SALE_CODE"
    col_sale_name = find_col(fieldnames, "SALE", "NAME") or "SALE_NAME"
    col_desc = find_col(fieldnames, "DESCRIPTION") or "DESCRIPTION"
    col_qty = find_col(fieldnames, "QTY") or "QTY"
    col_net = find_col(fieldnames, "NET_AMOUNT") or find_col(fieldnames, "NET", "AMOUNT") or "NET_AMOUNT"
    col_date = find_col(fieldnames, "ORDER", "DATE") or find_col(fieldnames, "DATE") or "ORDER_DATE"

    staff_by_shop = {}
    alltime_sold = {}  # (shop_code, model) -> {qty, net}
    suplife_by_shop = {}  # shop_code -> count (Sep 18-30 only)

    for row in reader:
        description = row.get(col_desc) or ""
        shop_code = (row.get(col_shop) or "").strip()

        # Suplife counting: independent of model match, still date-restricted
        # to Sep 18-30 (same window as the staff breakdown). Normal Suplife
        # rows count as 1; "BOX SET" Suplife rows count as 3.
        if shop_code and match_suplife(description):
            order_date = parse_order_date(row.get(col_date))
            if order_date is not None and DATE_START <= order_date <= DATE_END:
                suplife_by_shop[shop_code] = suplife_by_shop.get(shop_code, 0) + suplife_weight(description)

        model = match_model(description)
        if not model:
            continue

        if not shop_code:
            continue

        qty = to_number(row.get(col_qty))
        net_amount = to_number(row.get(col_net))

        # all-time sold (not date-restricted) for stock comparison
        key_at = (shop_code, model)
        if key_at not in alltime_sold:
            alltime_sold[key_at] = {"qty": 0, "net": 0}
        alltime_sold[key_at]["qty"] += qty
        alltime_sold[key_at]["net"] += net_amount

        # date-restricted staff breakdown
        order_date = parse_order_date(row.get(col_date))
        if order_date is None or not (DATE_START <= order_date <= DATE_END):
            continue

        sale_code_raw = (row.get(col_sale_code) or "").strip()
        sale_name = (row.get(col_sale_name) or "").strip()
        if not sale_code_raw:
            continue

        shop_bucket = staff_by_shop.setdefault(shop_code, {})
        norm_key = normalize_code(sale_code_raw)
        entry = shop_bucket.setdefault(
            norm_key,
            {"saleCode": sale_code_raw, "saleNameCounts": {}, "byModel": {m: {"qty": 0, "net": 0} for m in MODELS}},
        )
        if len(sale_code_raw) >= len(entry["saleCode"]):
            entry["saleCode"] = sale_code_raw
        if sale_name:
            entry["saleNameCounts"][sale_name] = entry["saleNameCounts"].get(sale_name, 0) + 1
        entry["byModel"][model]["qty"] += qty
        entry["byModel"][model]["net"] += net_amount

    return staff_by_shop, alltime_sold, suplife_by_shop


def build_stock(stock_csv_text):
    """Returns { (shop_code, model): balance_qty }."""
    reader = csv.DictReader(io.StringIO(stock_csv_text))
    fieldnames = reader.fieldnames or []

    col_shop = find_col(fieldnames, "SHOP", "CODE") or find_col(fieldnames, "SHOP") or "SHOP_CODE"
    col_product = find_col(fieldnames, "PRODUCT", "NAME") or find_col(fieldnames, "PRODUCT") or find_col(fieldnames, "NAME")
    col_balance = find_col(fieldnames, "BALANCE") or find_col(fieldnames, "STOCK") or find_col(fieldnames, "QTY")

    print(f"DEBUG: stock sheet columns detected -> shop={col_shop!r} product={col_product!r} balance={col_balance!r} (available: {fieldnames})", file=sys.stderr)

    stock = {}
    for row in reader:
        product_name = row.get(col_product) or ""
        model = match_model(product_name)
        if not model:
            continue
        shop_code = (row.get(col_shop) or "").strip()
        if not shop_code:
            continue
        balance = to_number(row.get(col_balance))
        key = (shop_code, model)
        stock[key] = stock.get(key, 0) + balance

    return stock


def main():
    try:
        raw_text = fetch_csv(RAW_CSV_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR fetching raw CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        stock_text = fetch_csv(STOCK_CSV_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR fetching stock CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    staff_by_shop, alltime_sold, suplife_by_shop = build_staff_sales(raw_text)
    stock = build_stock(stock_text)

    all_shop_codes = sorted(set(
        list(staff_by_shop.keys()) + [k[0] for k in alltime_sold] + [k[0] for k in stock] + list(suplife_by_shop.keys())
    ))

    shops_out = []
    for shop_code in all_shop_codes:
        shop_name = SHOP_NAMES.get(shop_code, shop_code)

        staff_list = []
        for entry in staff_by_shop.get(shop_code, {}).values():
            best_name = max(entry["saleNameCounts"].items(), key=lambda kv: kv[1])[0] if entry["saleNameCounts"] else entry["saleCode"]
            total_qty = sum(entry["byModel"][m]["qty"] for m in MODELS)
            total_net = sum(entry["byModel"][m]["net"] for m in MODELS)
            if total_qty == 0 and total_net == 0:
                continue  # skip staff with no iPhone 18 activity in the date range
            staff_list.append(
                {
                    "saleCode": entry["saleCode"],
                    "saleName": best_name,
                    "byModel": entry["byModel"],
                    "totalQty": total_qty,
                    "totalNet": total_net,
                }
            )
        staff_list.sort(key=lambda s: s["totalNet"], reverse=True)

        staff_totals = {m: {"qty": 0, "net": 0} for m in MODELS}
        for s in staff_list:
            for m in MODELS:
                staff_totals[m]["qty"] += s["byModel"][m]["qty"]
                staff_totals[m]["net"] += s["byModel"][m]["net"]

        model_summary = {}
        for m in MODELS:
            sold_qty = alltime_sold.get((shop_code, m), {"qty": 0}).get("qty", 0)
            stock_qty = stock.get((shop_code, m), 0)
            model_summary[m] = {"sold": sold_qty, "stock": stock_qty}

        iphone18_units = staff_totals["iPhone 18 Pro"]["qty"] + staff_totals["iPhone 18 Pro Max"]["qty"]
        suplife_count = suplife_by_shop.get(shop_code, 0)
        attach_rate = (suplife_count / iphone18_units * 100) if iphone18_units else 0

        shops_out.append(
            {
                "shopCode": shop_code,
                "shopName": shop_name,
                "staff": staff_list,
                "staffTotals": staff_totals,
                "modelSummary": model_summary,
                "suplife": {
                    "iphone18Units": iphone18_units,
                    "suplifeCount": suplife_count,
                    "attachRate": attach_rate,
                },
            }
        )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(shops_out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total_staff = sum(len(s["staff"]) for s in shops_out)
    print(f"Wrote {len(shops_out)} shops, {total_staff} staff records (with iPhone 18 activity Sep18-30) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
