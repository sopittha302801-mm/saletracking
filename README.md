# Sale Tracking Dashboard — BMAIV

Self-contained, light-themed sales dashboard for the POSTPAY / TOL / DEVICE
weekly sale tracking sheet, auto-refreshed hourly and hosted on GitHub Pages.

## How it works

- `index.html` — the dashboard. Fetches `data/data.json` at load time and
  reloads itself every hour so it always reflects the latest data.
- `data/data.json` — the parsed dataset. Rebuilt automatically.
- `scripts/build_data.py` — fetches the published Google Sheet CSV and
  rewrites `data/data.json`.
- `.github/workflows/refresh.yml` — GitHub Actions workflow that:
  1. Runs every hour (`cron: '0 * * * *'`, UTC) or on manual trigger
  2. Re-runs `build_data.py` to pull the latest sheet data
  3. Commits `data/data.json` if it changed
  4. Deploys the site to GitHub Pages

## One-time setup already done

- Repository secret `SHEET_CSV_URL` — Week 1's **Publish to web → CSV** link.
- Repository secrets `SHEET_CSV_URL_WEEK2` .. `SHEET_CSV_URL_WEEK5` — each
  additional week's own sheet tab, published the same way. Each week lives
  in its **own tab** (own `gid`), not just more columns in one tab — add a
  new secret whenever a new week's tab is published and it'll be picked up
  and merged in automatically on the next hourly run.
- GitHub Pages — set to deploy from GitHub Actions.

## Adding a new week

1. In Google Sheets, publish the new week's tab to the web as CSV (File →
   Share → Publish to web → select that week's tab → CSV → Publish).
2. Add the resulting URL as a new repo secret named `SHEET_CSV_URL_WEEK<N>`
   (e.g. `SHEET_CSV_URL_WEEK3`) under **Settings → Secrets and variables →
   Actions**.
3. That's it — `scripts/build_data.py` fetches every configured week source
   and merges them into one dataset, and the dashboard's Week filter will
   show real data for it automatically.

## Updating the source sheet

If the sheet structure changes (new columns, renamed sections, etc.), edit
`scripts/build_data.py` — it expects three stacked sections
(`POSTPAY`, `TOL`, `DEVICE`), each with a `SHOP CODE` header row followed by
shop rows, matching the original spreadsheet layout.

## Running the refresh manually

Go to the **Actions** tab → **Refresh Sale Tracking Data** → **Run workflow**.

## Local preview

Just open `index.html` in a browser — it fetches `data/data.json` via a
relative path, so serve the folder locally if your browser blocks local
`fetch()` of JSON files, e.g.:

```bash
python3 -m http.server 8000
# then open http://localhost:8000
```
