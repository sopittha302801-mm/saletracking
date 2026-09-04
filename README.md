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

- Repository secret `SHEET_CSV_URL` — points at the sheet's **Publish to
  web → CSV** link. If you republish the sheet or change tabs, update this
  secret under **Settings → Secrets and variables → Actions**.
- GitHub Pages — set to deploy from GitHub Actions.

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
