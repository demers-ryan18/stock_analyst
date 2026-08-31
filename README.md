# Growth Portfolio Manager

An autonomous, recommendation-only growth-stock portfolio manager. A scheduled cloud
agent runs daily: it researches your holdings and a candidate watchlist, decides what to
hold/trim/sell/buy, updates a tracked "model" portfolio with logged rationale, and reports
the results to you via email and a live dashboard. **It never places real trades** — you
execute manually in your own brokerage account based on its recommendations.

Start with [AGENT.md](AGENT.md) — that's the agent's full identity: its job, its exact
steps in order, its hard constraints, and its definition of done. Every scheduled run reads
that file first.

## How it works

```
config/settings.yaml   Position-sizing / sector-cap rules (edit to change strategy limits)
config/watchlist.csv   Candidate buy universe; the agent adds to this as it researches
config/artifact_id.txt Dashboard Artifact URL, reused so the same link updates each run

data/portfolio.json    The tracked "model" portfolio: cash + holdings, with cost basis,
                        sector, and thesis notes per holding
data/transactions.csv  Append-only log of every BUY/SELL/TRIM/ADD with rationale
data/history.csv        One row per day: total value, cash, benchmark price — powers the
                        dashboard's performance chart and vs-benchmark comparison

scripts/import_csv.py       Import/reconcile your real broker CSV export
scripts/fetch_data.py       Pull prices + fundamentals (yfinance), including the benchmark
scripts/evaluate.py         Quantitative hold/trim/sell/buy screening logic
scripts/record_history.py   Appends/updates today's row in data/history.csv
scripts/generate_report.py  Builds reports/latest.md + a dated archive copy
scripts/dashboard_data.py   Builds the JSON payload the dashboard Artifact reads (holdings
                             with fundamentals/cap-usage, sector allocation, performance
                             history, watchlist candidate scores, recent decisions)

reports/latest.md            Most recent report
reports/archive/YYYY-MM-DD.md  Full history, one file per day
```

## One-time setup you still need to do

1. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```
2. **Import your real holdings.** Export your current positions as a CSV from your
   broker (most brokers have a "download holdings/positions" option), save it into
   `data/imports/`, then run:
   ```
   python scripts/import_csv.py --seed data/imports/your_export.csv
   ```
   This works with any broker's column naming (Fidelity, Schwab, Robinhood, etc.) via a
   flexible synonym match — see `COLUMN_SYNONYMS` in `scripts/import_csv.py` if a new
   broker's headers aren't recognized and need a synonym added.

   Until this step is done, `data/portfolio.json` stays in `"awaiting_import"` status —
   the daily agent will still run and research the watchlist, but skips evaluating
   holdings that don't exist yet, and the report/dashboard say so clearly.

3. **Keep it honest over time.** Since this is recommendation-only, your real portfolio
   can drift from the tracked one (you might not execute a recommendation immediately, or
   you trade something outside the system). Periodically re-export your holdings and run:
   ```
   python scripts/import_csv.py --reconcile data/imports/your_export.csv
   ```
   This prints a diff (added/removed tickers, share-count changes) without writing
   anything. Add `--apply` once you've reviewed the diff and want it written.

4. **The daily cron** is registered separately via the `schedule` skill, pointed at this
   repo, running `AGENT.md`'s steps once per weekday after market close. See
   `AGENT.md` for exactly what each run does.

## Running things manually / testing

```
python scripts/fetch_data.py          # refresh prices + fundamentals (+ benchmark)
python scripts/record_history.py      # record today's value/benchmark snapshot
python scripts/generate_report.py     # rebuild reports/latest.md
python scripts/dashboard_data.py      # rebuild reports/dashboard_data.json
pytest tests/                          # run the test suite (no network required)
```

Python 3.14 is very new — if a dependency ever fails to install a wheel for it, fall back
to a 3.11/3.12 virtual environment:
```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Hard limits (see AGENT.md for the authoritative list)

- Recommendation-only — no brokerage API, no real order execution, ever.
- US equities and ETFs only — no options, crypto, or margin.
- No single position above ~15% of portfolio value; target 15-25 holdings; no sector
  above ~30% (exact numbers in `config/settings.yaml`).
