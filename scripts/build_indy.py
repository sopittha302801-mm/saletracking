#!/usr/bin/env python3
"""
Fetches the published 'raw' sheet CSV, counts qualifying "Entry Model"
transactions per salesperson (matched via SALE_CODE), and rebuilds
data/indy_data.json in the shape the INDY page expects.

Entry Model match rule (per business definition):
  DESCRIPTION contains any of: A06, Y05, A7 PRO, X5C  (case-insensitive)

The team roster (who belongs to RR Multi vs RR Retention, and each team's
Entry Model target) is not present in 'raw' and must be maintained here.
Edit ROSTER / TARGETS below if staff or targets change.
"""
import csv
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

MATCH_KEYWORDS = ["A06", "Y05", "A7 PRO", "X5C"]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "indy_data.json")

# Team roster. Entry Model target is a TEAM-level target (not per person),
# taken from the sheet's team header row (RR Multi: 15, RR Retention: 10).
TEAM_TARGETS = {"RR Multi": 15, "RR Retention": 10}

ROSTER = [
    {"team": "RR Multi", "saleCode": "010J4920", "name": "จรรยาภรณ์"},
    {"team": "RR Multi", "saleCode": "010Q6125", "name": "ปสันน์ธรรศ"},
    {"team": "RR Multi", "saleCode": "12808188", "name": "อินทิรา"},
    {"team": "RR Multi", "saleCode": "010L6084", "name": "นัฑเศรษฐ์"},
    {"team": "RR Multi", "saleCode": "NEW OS", "name": "พัทน์ธีรา"},
    {"team": "RR Multi", "saleCode": "12808761", "name": "ณัฐธยาน์"},
    {"team": "RR Multi", "saleCode": "01075327", "name": "ศุภลักษณ์"},
    {"team": "RR Multi", "saleCode": "010N6112", "name": "เมธาพร"},
    {"team": "RR Multi", "saleCode": "010J9581", "name": "จุฬาลักษณ์"},
    {"team": "RR Multi", "saleCode": "12807924", "name": "คงฤทธิ์"},
    {"team": "RR Multi", "saleCode": "12810390", "name": "ดลภัทร"},
    {"team": "RR Multi", "saleCode": "010L6770", "name": "สุนีย์"},
    {"team": "RR Multi", "saleCode": "010O2425", "name": "อลงกรณ์"},
    {"team": "RR Multi", "saleCode": "12809845", "name": "ขนิษฐ์"},
    {"team": "RR Retention", "saleCode": "01055175", "name": "นภัสนันท์"},
    {"team": "RR Retention", "saleCode": "010E3992", "name": "ธนัฏฐา"},
]


def normalize_code(code):
    """Normalize a SALE_CODE for matching: trim, uppercase, strip leading zeros
    from purely-numeric codes (raw sheet drops leading zeros, INDY keeps them)."""
    if code is None:
        return ""
    c = code.strip().upper()
    if c.isdigit():
        c = c.lstrip("0") or "0"
    return c


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


def count_entry_model(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    counts = {}
    pattern = re.compile("|".join(re.escape(k) for k in MATCH_KEYWORDS), re.IGNORECASE)

    for row in reader:
        sale_code = row.get("SALE_CODE") or row.get("SALE CODE") or ""
        description = row.get("DESCRIPTION") or ""
        if not sale_code or not description:
            continue
        if pattern.search(description):
            key = normalize_code(sale_code)
            counts[key] = counts.get(key, 0) + 1

    return counts


def build_records(counts):
    records = []
    for person in ROSTER:
        key = normalize_code(person["saleCode"])
        entryModel = counts.get(key, 0)
        records.append(
            {
                "team": person["team"],
                "saleCode": person["saleCode"],
                "name": person["name"],
                "entryModel": entryModel,
            }
        )
    return records


def build_output(records):
    teams = {}
    for team, target in TEAM_TARGETS.items():
        members = [r for r in records if r["team"] == team]
        teams[team] = {
            "target": target,
            "achieved": sum(m["entryModel"] for m in members),
            "members": members,
        }
    return teams


def main():
    try:
        csv_text = fetch_csv(RAW_CSV_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR fetching raw CSV: {exc}", file=sys.stderr)
        sys.exit(1)

    counts = count_entry_model(csv_text)
    records = build_records(counts)
    output = build_output(records)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(t["achieved"] for t in output.values())
    print(f"Wrote {len(records)} roster records across {len(output)} teams to {OUTPUT_PATH} (total Entry Model: {total})")


if __name__ == "__main__":
    main()
