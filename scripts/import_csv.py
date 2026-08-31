"""Import a broker CSV export into data/portfolio.json.

Two modes:
  --seed <file>       First-time population. Fails loudly if portfolio.json already
                       has holdings, to avoid silently overwriting tracked state.
  --reconcile <file>  Diff a fresh export against current portfolio.json (added/removed
                       tickers, share-count deltas). Prints the diff; only writes with
                       --apply. Intentionally simple: diff + human confirm, not an
                       automatic merge engine.

Broker exports vary (Fidelity/Schwab/Robinhood/etc. all use different headers), so
columns are matched by a case-insensitive synonym table rather than hardcoded names.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from utils import REPO_ROOT, load_settings, resolve_path

COLUMN_SYNONYMS = {
    "ticker": {"symbol", "ticker", "stock", "security"},
    "shares": {"quantity", "shares", "qty", "share quantity"},
    "cost_basis_total": {"cost basis", "cost basis total", "total cost basis", "book value"},
    "cost_basis_per_share": {"average cost", "avg cost", "cost per share", "average cost basis"},
    "current_value": {"current value", "market value", "value"},
}


def _normalize(col: str) -> str:
    return col.strip().lower()


def detect_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map our canonical field names to whatever column name the broker actually used."""
    normalized = {_normalize(c): c for c in df.columns}
    mapping: dict[str, str] = {}
    for field, synonyms in COLUMN_SYNONYMS.items():
        for syn in synonyms:
            if syn in normalized:
                mapping[field] = normalized[syn]
                break
    missing_required = [f for f in ("ticker", "shares") if f not in mapping]
    if missing_required:
        raise ValueError(
            f"Could not find columns for required fields {missing_required} in CSV headers "
            f"{list(df.columns)}. Add a synonym to COLUMN_SYNONYMS in scripts/import_csv.py "
            f"if this broker uses different header names."
        )
    return mapping


def parse_broker_csv(path: Path) -> list[dict]:
    df = pd.read_csv(path)
    mapping = detect_columns(df)
    holdings = []
    for _, row in df.iterrows():
        ticker = str(row[mapping["ticker"]]).strip().upper()
        if not ticker or ticker.lower() in ("nan", "cash", "sweep"):
            continue
        shares = float(row[mapping["shares"]])
        if shares <= 0:
            continue

        if "cost_basis_per_share" in mapping and pd.notna(row.get(mapping["cost_basis_per_share"])):
            cost_basis_per_share = float(row[mapping["cost_basis_per_share"]])
        elif "cost_basis_total" in mapping and pd.notna(row.get(mapping["cost_basis_total"])):
            cost_basis_per_share = float(row[mapping["cost_basis_total"]]) / shares
        else:
            cost_basis_per_share = None

        holdings.append({
            "ticker": ticker,
            "shares": shares,
            "cost_basis_per_share": cost_basis_per_share,
            "date_added": date.today().isoformat(),
            "sector": None,
            "thesis": "Imported from broker export; awaiting first research review.",
            "last_review": None,
            "status": "active",
        })
    return holdings


def backup_portfolio(portfolio_path: Path) -> Path:
    backup_path = portfolio_path.with_name(f"{portfolio_path.name}.bak-{date.today().isoformat()}")
    shutil.copy2(portfolio_path, backup_path)
    return backup_path


def seed(csv_path: Path, repo_root: Path) -> None:
    settings = load_settings(repo_root)
    portfolio_path = resolve_path(settings, "portfolio", repo_root)
    with open(portfolio_path, encoding="utf-8") as f:
        current = json.load(f)

    if current.get("holdings"):
        raise SystemExit(
            "portfolio.json already has holdings. --seed is for first-time import only. "
            "Use --reconcile to update an existing tracked portfolio instead."
        )

    holdings = parse_broker_csv(csv_path)
    backup = backup_portfolio(portfolio_path)
    new_portfolio = {
        "status": "active",
        "cash": current.get("cash", 0.0),
        "last_updated": date.today().isoformat(),
        "holdings": holdings,
    }
    with open(portfolio_path, "w", encoding="utf-8") as f:
        json.dump(new_portfolio, f, indent=2)
        f.write("\n")

    print(f"Backed up previous state to {backup}")
    print(f"Seeded {len(holdings)} holdings from {csv_path}")
    for h in holdings:
        print(f"  {h['ticker']}: {h['shares']} shares")


def reconcile(csv_path: Path, repo_root: Path, apply: bool) -> None:
    settings = load_settings(repo_root)
    portfolio_path = resolve_path(settings, "portfolio", repo_root)
    with open(portfolio_path, encoding="utf-8") as f:
        current = json.load(f)

    fresh_holdings = {h["ticker"]: h for h in parse_broker_csv(csv_path)}
    current_holdings = {h["ticker"]: h for h in current.get("holdings", [])}

    added = sorted(set(fresh_holdings) - set(current_holdings))
    removed = sorted(set(current_holdings) - set(fresh_holdings))
    changed = []
    for ticker in sorted(set(fresh_holdings) & set(current_holdings)):
        old_shares = current_holdings[ticker]["shares"]
        new_shares = fresh_holdings[ticker]["shares"]
        if abs(old_shares - new_shares) > 1e-6:
            changed.append((ticker, old_shares, new_shares))

    print(f"Reconciliation diff against {csv_path}:")
    print(f"  New tickers not currently tracked: {added or 'none'}")
    print(f"  Tracked tickers missing from export (sold/closed?): {removed or 'none'}")
    if changed:
        print("  Share count deltas:")
        for ticker, old, new in changed:
            print(f"    {ticker}: {old} -> {new}")
    else:
        print("  Share count deltas: none")

    if not apply:
        print("\nDry run only. Re-run with --apply to write these changes.")
        return

    backup = backup_portfolio(portfolio_path)
    for ticker in added:
        current_holdings[ticker] = fresh_holdings[ticker]
    for ticker in removed:
        del current_holdings[ticker]
    for ticker, _, new_shares in changed:
        current_holdings[ticker]["shares"] = new_shares

    current["holdings"] = list(current_holdings.values())
    current["last_updated"] = date.today().isoformat()
    with open(portfolio_path, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
        f.write("\n")
    print(f"\nBacked up previous state to {backup}")
    print("Applied reconciliation changes to portfolio.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", metavar="CSV_PATH", help="First-time import into an empty portfolio")
    group.add_argument("--reconcile", metavar="CSV_PATH", help="Diff a fresh export against tracked state")
    parser.add_argument("--apply", action="store_true", help="With --reconcile, write the diffed changes")
    args = parser.parse_args()

    if args.seed:
        seed(Path(args.seed), REPO_ROOT)
    else:
        reconcile(Path(args.reconcile), REPO_ROOT, apply=args.apply)


if __name__ == "__main__":
    main()
