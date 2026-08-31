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
import csv
import io
import json
import re
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

# Tickers used by brokers as cash-sweep / money-market vehicles rather than tracked
# holdings (Fidelity SPAXX/FDRXX/FZFXX/SPRXX being the most common). Rows with a
# blank share count are already treated as cash below; this is a belt-and-suspenders
# catch for exports that fill in a share count for the sweep fund too.
_CASH_SWEEP_TICKERS = {"SPAXX", "FDRXX", "FZFXX", "SPRXX", "FCASH", "FDIC"}


def _clean_data_block(raw_text: str) -> str:
    """Isolate the actual position rows from a real-world broker export.

    Handles the mess these exports commonly contain: a UTF-8 BOM, a trailing
    empty field on every data row (header has N columns, rows have N+1 with an
    empty last value) that shifts every later column by one under a strict
    parser, and pages of legal-boilerplate footer text after a blank line
    following the data.
    """
    raw_text = raw_text.lstrip("﻿")
    lines = raw_text.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return raw_text
    header_fields = next(csv.reader([non_empty[0]]))
    header_len = len(header_fields)

    cleaned_lines = [non_empty[0]]
    for line in lines[lines.index(non_empty[0]) + 1:]:
        if not line.strip():
            break  # blank line marks the end of the data block
        fields = next(csv.reader([line]))
        if len(fields) == header_len + 1 and fields[-1] == "":
            fields = fields[:-1]
        if len(fields) != header_len:
            # Doesn't match the data shape (e.g. a stray note) - stop rather than
            # feed a misaligned row to the parser.
            break
        writer_buf = io.StringIO()
        csv.writer(writer_buf).writerow(fields)
        cleaned_lines.append(writer_buf.getvalue().rstrip("\r\n"))

    return "\n".join(cleaned_lines)


def _normalize(col: str) -> str:
    return col.strip().lower()


def _parse_money(value) -> float | None:
    """Parse a broker's currency-formatted string ('$1,234.56', '-$42.22') to float."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    text = text.replace("$", "").replace(",", "").replace("+", "")
    try:
        return float(text)
    except ValueError:
        return None


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


def parse_broker_csv(path: Path) -> tuple[list[dict], float]:
    """Returns (holdings, cash) - cash-sweep/money-market rows are pulled out of the
    holdings list and their value reported separately rather than treated as a stock."""
    raw_text = path.read_text(encoding="utf-8-sig")
    df = pd.read_csv(io.StringIO(_clean_data_block(raw_text)))
    mapping = detect_columns(df)
    holdings = []
    cash = 0.0
    for _, row in df.iterrows():
        ticker = str(row[mapping["ticker"]]).strip().upper().rstrip("*")
        if not ticker or ticker.lower() in ("nan", "cash", "sweep"):
            continue

        shares_raw = row[mapping["shares"]]
        is_blank_shares = pd.isna(shares_raw) or str(shares_raw).strip() == ""
        if is_blank_shares or ticker in _CASH_SWEEP_TICKERS:
            # No share count (or a known sweep fund) -> cash-equivalent, not a holding.
            value = _parse_money(row.get(mapping.get("current_value", ""), None))
            if value:
                cash += value
            continue

        shares = float(shares_raw)
        if shares <= 0:
            continue

        cost_basis_per_share = None
        if "cost_basis_per_share" in mapping:
            cost_basis_per_share = _parse_money(row.get(mapping["cost_basis_per_share"]))
        if cost_basis_per_share is None and "cost_basis_total" in mapping:
            total = _parse_money(row.get(mapping["cost_basis_total"]))
            if total is not None:
                cost_basis_per_share = total / shares

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
    return holdings, cash


def _enrich_sectors(holdings: list[dict]) -> None:
    """Best-effort fill of each holding's sector via yfinance, so the dashboard's
    sector allocation view isn't empty on day one. Never fatal - a ticker that fails
    just keeps sector=None, same as before this ran."""
    try:
        import yfinance as yf
    except ImportError:
        return
    for h in holdings:
        try:
            info = yf.Ticker(h["ticker"]).info
            sector = info.get("sector")
            if sector:
                h["sector"] = sector
        except Exception:
            continue


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

    holdings, cash_from_csv = parse_broker_csv(csv_path)
    print(f"Fetching sector data for {len(holdings)} tickers (best-effort)...")
    _enrich_sectors(holdings)

    backup = backup_portfolio(portfolio_path)
    new_portfolio = {
        "status": "active",
        "cash": current.get("cash", 0.0) + cash_from_csv,
        "last_updated": date.today().isoformat(),
        "holdings": holdings,
    }
    with open(portfolio_path, "w", encoding="utf-8") as f:
        json.dump(new_portfolio, f, indent=2)
        f.write("\n")

    print(f"Backed up previous state to {backup}")
    print(f"Seeded {len(holdings)} holdings from {csv_path} (cash: ${cash_from_csv:,.2f})")
    for h in holdings:
        cb = f"${h['cost_basis_per_share']:.2f}" if h["cost_basis_per_share"] is not None else "n/a"
        print(f"  {h['ticker']}: {h['shares']} shares @ {cb} cost basis, sector={h['sector'] or 'unknown'}")


def reconcile(csv_path: Path, repo_root: Path, apply: bool) -> None:
    settings = load_settings(repo_root)
    portfolio_path = resolve_path(settings, "portfolio", repo_root)
    with open(portfolio_path, encoding="utf-8") as f:
        current = json.load(f)

    fresh_list, fresh_cash = parse_broker_csv(csv_path)
    fresh_holdings = {h["ticker"]: h for h in fresh_list}
    current_holdings = {h["ticker"]: h for h in current.get("holdings", [])}

    added = sorted(set(fresh_holdings) - set(current_holdings))
    removed = sorted(set(current_holdings) - set(fresh_holdings))
    changed = []
    for ticker in sorted(set(fresh_holdings) & set(current_holdings)):
        old_shares = current_holdings[ticker]["shares"]
        new_shares = fresh_holdings[ticker]["shares"]
        if abs(old_shares - new_shares) > 1e-6:
            changed.append((ticker, old_shares, new_shares))

    old_cash = current.get("cash", 0.0)
    print(f"Reconciliation diff against {csv_path}:")
    print(f"  New tickers not currently tracked: {added or 'none'}")
    print(f"  Tracked tickers missing from export (sold/closed?): {removed or 'none'}")
    if changed:
        print("  Share count deltas:")
        for ticker, old, new in changed:
            print(f"    {ticker}: {old} -> {new}")
    else:
        print("  Share count deltas: none")
    print(f"  Cash: ${old_cash:,.2f} -> ${fresh_cash:,.2f}")

    if not apply:
        print("\nDry run only. Re-run with --apply to write these changes.")
        return

    backup = backup_portfolio(portfolio_path)
    if added:
        print(f"Fetching sector data for {len(added)} new ticker(s) (best-effort)...")
        _enrich_sectors([fresh_holdings[t] for t in added])
    for ticker in added:
        current_holdings[ticker] = fresh_holdings[ticker]
    for ticker in removed:
        del current_holdings[ticker]
    for ticker, _, new_shares in changed:
        current_holdings[ticker]["shares"] = new_shares

    current["holdings"] = list(current_holdings.values())
    current["cash"] = fresh_cash
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
