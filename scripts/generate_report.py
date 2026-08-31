"""Build reports/latest.md and reports/archive/<date>.md from current state.

Reads data/portfolio.json, data/transactions.csv, and the latest fetch_data.py cache
(data/price_cache/latest_fetch.json) for prices. Must run cleanly even when the
portfolio has no holdings yet (pre-CSV-import).
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from utils import (
    REPO_ROOT,
    load_portfolio,
    load_settings,
    resolve_path,
    sector_pct,
    total_portfolio_value,
)


def load_latest_fetch(settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    path = resolve_path(settings, "price_cache", repo_root) / "latest_fetch.json"
    if not path.exists():
        return {"as_of": None, "prices": {}, "fundamentals": {}, "errors": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_todays_transactions(settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[dict[str, str]]:
    path = resolve_path(settings, "transactions", repo_root)
    if not path.exists():
        return []
    today = date.today().isoformat()
    with open(path, encoding="utf-8", newline="") as f:
        return [row for row in csv.DictReader(f) if row.get("date") == today]


def build_report(repo_root: Path = REPO_ROOT) -> str:
    settings = load_settings(repo_root)
    portfolio = load_portfolio(settings, repo_root)
    fetch = load_latest_fetch(settings, repo_root)
    prices = fetch.get("prices", {})
    todays_tx = load_todays_transactions(settings, repo_root)

    today = date.today().isoformat()
    lines = [f"# Portfolio Report — {today}", ""]

    if portfolio.get("status") == "awaiting_import" or not portfolio.get("holdings"):
        lines += [
            "**Portfolio not yet funded — awaiting broker CSV import.**",
            "",
            "Run `python scripts/import_csv.py --seed <path-to-export.csv>` once a broker "
            "export is available in `data/imports/`. Until then this report only tracks "
            "watchlist research.",
            "",
        ]
        if fetch.get("errors"):
            lines += ["## Data fetch errors", ""] + [f"- {e}" for e in fetch["errors"]] + [""]
        return "\n".join(lines)

    total_value = total_portfolio_value(portfolio, prices)
    cash = portfolio.get("cash", 0.0)

    lines += [
        f"**Total portfolio value:** ${total_value:,.2f}  ",
        f"**Cash:** ${cash:,.2f} ({(cash / total_value * 100) if total_value else 0:.1f}%)",
        "",
        "## Today's decisions",
        "",
    ]
    if todays_tx:
        lines.append("| Action | Ticker | Shares | Price | Rationale |")
        lines.append("|---|---|---|---|---|")
        for tx in todays_tx:
            lines.append(
                f"| {tx['action']} | {tx['ticker']} | {tx['shares']} | ${float(tx['price']):.2f} | {tx['rationale']} |"
            )
    else:
        lines.append("No BUY/SELL/TRIM/ADD decisions today — all positions held.")
    lines.append("")

    lines += ["## Current holdings", "", "| Ticker | Shares | Cost Basis | Price | Value | Return | % of Portfolio |",
               "|---|---|---|---|---|---|---|"]
    for h in sorted(portfolio["holdings"], key=lambda x: x["ticker"]):
        price = prices.get(h["ticker"], h.get("cost_basis_per_share") or 0.0)
        value = h["shares"] * price
        cost_basis = h.get("cost_basis_per_share")
        ret = f"{((price - cost_basis) / cost_basis * 100):.1f}%" if cost_basis else "n/a"
        pct = (value / total_value * 100) if total_value else 0.0
        lines.append(
            f"| {h['ticker']} | {h['shares']} | "
            f"{f'${cost_basis:.2f}' if cost_basis else 'n/a'} | ${price:.2f} | "
            f"${value:,.2f} | {ret} | {pct:.1f}% |"
        )
    lines.append("")

    sectors = sorted({h.get("sector") for h in portfolio["holdings"] if h.get("sector")})
    if sectors:
        lines += ["## Sector allocation", "", "| Sector | % of Portfolio |", "|---|---|"]
        for s in sectors:
            lines.append(f"| {s} | {sector_pct(s, portfolio, prices, total_value) * 100:.1f}% |")
        lines.append("")

    if fetch.get("errors"):
        lines += ["## Data fetch errors", ""] + [f"- {e}" for e in fetch["errors"]] + [""]

    return "\n".join(lines)


def main() -> None:
    settings = load_settings(REPO_ROOT)
    report = build_report(REPO_ROOT)

    latest_path = resolve_path(settings, "reports_latest", REPO_ROOT)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(report)

    archive_dir = resolve_path(settings, "reports_archive", REPO_ROOT)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{date.today().isoformat()}.md"
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Wrote {latest_path} and {archive_path}")


if __name__ == "__main__":
    main()
