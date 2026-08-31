"""Emit the JSON payload the dashboard Artifact reads: holdings, allocation, performance,
recent decisions, cash, last-updated. Degrades gracefully to an "awaiting import" state.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from generate_report import load_latest_fetch, load_todays_transactions
from utils import (
    REPO_ROOT,
    load_portfolio,
    load_settings,
    resolve_path,
    sector_pct,
    total_portfolio_value,
)


def load_recent_transactions(settings: dict[str, Any], repo_root: Path = REPO_ROOT, limit: int = 20) -> list[dict]:
    path = resolve_path(settings, "transactions", repo_root)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:][::-1]


def build_dashboard_payload(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    settings = load_settings(repo_root)
    portfolio = load_portfolio(settings, repo_root)
    fetch = load_latest_fetch(settings, repo_root)
    prices = fetch.get("prices", {})

    if portfolio.get("status") == "awaiting_import" or not portfolio.get("holdings"):
        return {
            "status": "awaiting_import",
            "last_updated": date.today().isoformat(),
            "cash": portfolio.get("cash", 0.0),
            "total_value": portfolio.get("cash", 0.0),
            "holdings": [],
            "sector_allocation": [],
            "recent_transactions": load_recent_transactions(settings, repo_root),
            "data_errors": fetch.get("errors", []),
        }

    total_value = total_portfolio_value(portfolio, prices)
    holdings_out = []
    for h in portfolio["holdings"]:
        price = prices.get(h["ticker"], h.get("cost_basis_per_share") or 0.0)
        value = h["shares"] * price
        cost_basis = h.get("cost_basis_per_share")
        holdings_out.append({
            "ticker": h["ticker"],
            "shares": h["shares"],
            "cost_basis_per_share": cost_basis,
            "price": price,
            "value": value,
            "return_pct": ((price - cost_basis) / cost_basis) if cost_basis else None,
            "pct_of_portfolio": (value / total_value) if total_value else 0.0,
            "sector": h.get("sector"),
            "thesis": h.get("thesis"),
        })
    holdings_out.sort(key=lambda x: x["value"], reverse=True)

    sectors = sorted({h.get("sector") for h in portfolio["holdings"] if h.get("sector")})
    sector_allocation = [
        {"sector": s, "pct": sector_pct(s, portfolio, prices, total_value)}
        for s in sectors
    ]

    return {
        "status": "active",
        "last_updated": date.today().isoformat(),
        "cash": portfolio.get("cash", 0.0),
        "total_value": total_value,
        "holdings": holdings_out,
        "sector_allocation": sector_allocation,
        "recent_transactions": load_recent_transactions(settings, repo_root),
        "data_errors": fetch.get("errors", []),
    }


def main() -> None:
    payload = build_dashboard_payload(REPO_ROOT)
    out_path = REPO_ROOT / "reports" / "dashboard_data.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
