"""Shared helpers: settings loading, portfolio math, sizing/sector-cap checks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_settings(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    with open(repo_root / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(settings: dict[str, Any], key: str, repo_root: Path = REPO_ROOT) -> Path:
    return repo_root / settings["paths"][key]


def load_portfolio(settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    path = resolve_path(settings, "portfolio", repo_root)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_portfolio(portfolio: dict[str, Any], settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> None:
    path = resolve_path(settings, "portfolio", repo_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2)
        f.write("\n")


def holdings_value(portfolio: dict[str, Any], prices: dict[str, float]) -> float:
    """Total market value of all holdings using the given ticker->price map.

    A holding whose price is missing falls back to its cost basis so a bad/missing
    quote doesn't silently zero out that position's contribution to the total.
    """
    total = 0.0
    for h in portfolio["holdings"]:
        price = prices.get(h["ticker"])
        if price is None:
            price = h["cost_basis_per_share"]
        total += h["shares"] * price
    return total


def total_portfolio_value(portfolio: dict[str, Any], prices: dict[str, float]) -> float:
    return holdings_value(portfolio, prices) + portfolio.get("cash", 0.0)


def position_pct(holding: dict[str, Any], price: float, total_value: float) -> float:
    if total_value <= 0:
        return 0.0
    return (holding["shares"] * price) / total_value


def sector_pct(sector: str, portfolio: dict[str, Any], prices: dict[str, float], total_value: float) -> float:
    if total_value <= 0:
        return 0.0
    sector_value = sum(
        h["shares"] * prices.get(h["ticker"], h["cost_basis_per_share"])
        for h in portfolio["holdings"]
        if h.get("sector") == sector
    )
    return sector_value / total_value


def max_new_position_value(settings: dict[str, Any], total_value: float) -> float:
    """Largest dollar amount a single new/added position may reach under the size cap."""
    return settings["max_position_pct"] * total_value


def room_in_sector(settings: dict[str, Any], sector: str, portfolio: dict[str, Any],
                    prices: dict[str, float], total_value: float) -> float:
    """Remaining dollar room in a sector before hitting the sector cap."""
    cap_value = settings["sector_max_pct"] * total_value
    current = sector_pct(sector, portfolio, prices, total_value) * total_value
    return max(0.0, cap_value - current)
