"""Emit the JSON payload the dashboard Artifact reads: holdings (with fundamentals and
cap-usage), sector allocation, performance history vs. a benchmark, watchlist candidate
scores, recent decisions, cash, last-updated. Degrades gracefully to an "awaiting import"
state.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from evaluate import screen_candidates
from generate_report import load_latest_fetch, load_todays_transactions
from record_history import load_history
from utils import (
    REPO_ROOT,
    load_portfolio,
    load_settings,
    resolve_path,
    sector_pct,
    total_portfolio_value,
)

FUNDAMENTALS_DISPLAY_FIELDS = ["trailingPE", "forwardPE", "revenueGrowth", "earningsGrowth", "marketCap"]


def load_recent_transactions(settings: dict[str, Any], repo_root: Path = REPO_ROOT, limit: int = 20) -> list[dict]:
    path = resolve_path(settings, "transactions", repo_root)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:][::-1]


def load_active_watchlist(settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, dict[str, str]]:
    """ticker -> {sector, notes} for active watchlist.csv rows."""
    path = resolve_path(settings, "watchlist", repo_root)
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status", "active") == "active":
                out[row["ticker"].strip().upper()] = {
                    "sector": row.get("sector"),
                    "notes": row.get("notes"),
                }
    return out


def build_performance_history(settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    history_path = resolve_path(settings, "history", repo_root)
    rows = load_history(history_path)
    if not rows:
        return []

    baseline_value = float(rows[0]["total_value"])
    baseline_benchmark = float(rows[0]["benchmark_price"]) if rows[0].get("benchmark_price") else None

    out = []
    for row in rows:
        total_value = float(row["total_value"])
        benchmark_price = float(row["benchmark_price"]) if row.get("benchmark_price") else None
        entry = {
            "date": row["date"],
            "total_value": total_value,
            "portfolio_return_pct": (total_value - baseline_value) / baseline_value if baseline_value else None,
            "benchmark_return_pct": None,
        }
        if benchmark_price is not None and baseline_benchmark:
            entry["benchmark_return_pct"] = (benchmark_price - baseline_benchmark) / baseline_benchmark
        out.append(entry)
    return out


def build_watchlist_view(
    settings: dict[str, Any],
    portfolio: dict[str, Any],
    prices: dict[str, float],
    fundamentals: dict[str, dict[str, Any]],
    repo_root: Path = REPO_ROOT,
    top_n: int = 10,
) -> dict[str, Any]:
    active = load_active_watchlist(settings, repo_root)
    tickers = list(active.keys())
    scored = screen_candidates(tickers, portfolio, prices, fundamentals, settings)
    top = []
    for c in scored[:top_n]:
        top.append({
            "ticker": c.ticker,
            "sector": c.sector,
            "score": c.score,
            "reasons": c.reasons,
            "notes": active.get(c.ticker, {}).get("notes"),
        })
    return {"total_screened": len(tickers), "top_candidates": top}


def build_dashboard_payload(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    settings = load_settings(repo_root)
    portfolio = load_portfolio(settings, repo_root)
    fetch = load_latest_fetch(settings, repo_root)
    prices = fetch.get("prices", {})
    fundamentals = fetch.get("fundamentals", {})
    cap_warning = settings.get("cap_warning_threshold_pct", 0.85)

    if portfolio.get("status") == "awaiting_import" or not portfolio.get("holdings"):
        return {
            "status": "awaiting_import",
            "last_updated": date.today().isoformat(),
            "cash": portfolio.get("cash", 0.0),
            "total_value": portfolio.get("cash", 0.0),
            "holdings": [],
            "sector_allocation": [],
            "recent_transactions": load_recent_transactions(settings, repo_root),
            "performance_history": build_performance_history(settings, repo_root),
            "benchmark_ticker": settings.get("benchmark_ticker"),
            "watchlist": build_watchlist_view(settings, portfolio, prices, fundamentals, repo_root),
            "data_errors": fetch.get("errors", []),
        }

    total_value = total_portfolio_value(portfolio, prices)
    max_position_pct = settings.get("max_position_pct", 1.0)
    holdings_out = []
    for h in portfolio["holdings"]:
        price = prices.get(h["ticker"], h.get("cost_basis_per_share") or 0.0)
        value = h["shares"] * price
        cost_basis = h.get("cost_basis_per_share")
        pct_of_portfolio = (value / total_value) if total_value else 0.0
        cap_usage = (pct_of_portfolio / max_position_pct) if max_position_pct else 0.0
        f = fundamentals.get(h["ticker"], {})
        holdings_out.append({
            "ticker": h["ticker"],
            "shares": h["shares"],
            "cost_basis_per_share": cost_basis,
            "price": price,
            "value": value,
            "return_pct": ((price - cost_basis) / cost_basis) if cost_basis else None,
            "pct_of_portfolio": pct_of_portfolio,
            "position_cap_usage_pct": cap_usage,
            "near_position_cap": cap_usage >= cap_warning,
            "sector": h.get("sector"),
            "thesis": h.get("thesis"),
            "fundamentals": {k: f.get(k) for k in FUNDAMENTALS_DISPLAY_FIELDS},
        })
    holdings_out.sort(key=lambda x: x["value"], reverse=True)

    sector_max_pct = settings.get("sector_max_pct", 1.0)
    sectors = sorted({h.get("sector") for h in portfolio["holdings"] if h.get("sector")})
    sector_allocation = []
    for s in sectors:
        pct = sector_pct(s, portfolio, prices, total_value)
        cap_usage = (pct / sector_max_pct) if sector_max_pct else 0.0
        sector_allocation.append({
            "sector": s,
            "pct": pct,
            "sector_cap_usage_pct": cap_usage,
            "near_sector_cap": cap_usage >= cap_warning,
        })

    return {
        "status": "active",
        "last_updated": date.today().isoformat(),
        "cash": portfolio.get("cash", 0.0),
        "total_value": total_value,
        "holdings": holdings_out,
        "sector_allocation": sector_allocation,
        "recent_transactions": load_recent_transactions(settings, repo_root),
        "performance_history": build_performance_history(settings, repo_root),
        "benchmark_ticker": settings.get("benchmark_ticker"),
        "watchlist": build_watchlist_view(settings, portfolio, prices, fundamentals, repo_root),
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
