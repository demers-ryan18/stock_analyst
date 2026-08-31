"""Append (or update) today's row in data/history.csv: total portfolio value, cash,
and the benchmark's price, so the dashboard can chart performance over time and against
a simple index-fund comparison. Idempotent per day — re-running on the same date replaces
that day's row rather than duplicating it, since a run can regenerate state more than once
(e.g. correcting a cap violation mid-run).
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

from generate_report import load_latest_fetch
from utils import REPO_ROOT, load_portfolio, load_settings, resolve_path, total_portfolio_value

FIELDS = ["date", "total_value", "cash", "benchmark_price"]


def load_history(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def record_today(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    settings = load_settings(repo_root)
    portfolio = load_portfolio(settings, repo_root)
    fetch = load_latest_fetch(settings, repo_root)
    prices = fetch.get("prices", {})

    total_value = total_portfolio_value(portfolio, prices)
    benchmark_ticker = settings.get("benchmark_ticker")
    benchmark_price = prices.get(benchmark_ticker) if benchmark_ticker else None

    today = date.today().isoformat()
    row = {
        "date": today,
        "total_value": f"{total_value:.2f}",
        "cash": f"{portfolio.get('cash', 0.0):.2f}",
        "benchmark_price": f"{benchmark_price:.2f}" if benchmark_price is not None else "",
    }

    history_path = resolve_path(settings, "history", repo_root)
    rows = [r for r in load_history(history_path) if r.get("date") != today]
    rows.append(row)
    rows.sort(key=lambda r: r["date"])

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    return row


def main() -> None:
    row = record_today()
    print(f"Recorded {row['date']}: total_value=${row['total_value']}, "
          f"cash=${row['cash']}, benchmark_price={row['benchmark_price'] or 'n/a'}")


if __name__ == "__main__":
    main()
