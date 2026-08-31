"""Pull fresh prices + fundamentals for every current holding and watchlist ticker.

Two-tier fetch: one batched price-history call (cheap), then per-ticker fundamentals
via Ticker.info, cached to disk for a few days since fundamentals don't change
intraday. Tickers that error (delisted/renamed/bad data) are logged and skipped
rather than aborting the whole run.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# yfinance defaults to curl_cffi for browser TLS fingerprinting, which ships its
# own trust store and does not honor the proxy CA bundle a sandboxed cloud run
# injects via the standard env vars — every request fails with a connection
# reset even against an allowlisted host. Falling back to plain `requests` (which
# does honor those env vars) fixes this; this must be set before `import
# yfinance` since _http.py picks the HTTP backend at import time. Only kicks in
# when a proxy is actually configured (i.e. the cloud sandbox), so local runs are
# unaffected and keep using curl_cffi.
if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
    os.environ.setdefault("YF_DISABLE_CURL_CFFI", "1")

import pandas as pd
import yfinance as yf

from utils import REPO_ROOT, load_portfolio, load_settings, resolve_path

FUNDAMENTALS_FIELDS = [
    "currentPrice", "regularMarketPrice", "trailingPE", "forwardPE",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    "marketCap", "sector", "industry", "shortName",
]


def load_universe_tickers(settings: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    portfolio = load_portfolio(settings, repo_root)
    tickers = {h["ticker"] for h in portfolio.get("holdings", [])}

    watchlist_path = resolve_path(settings, "watchlist", repo_root)
    with open(watchlist_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "active") == "active":
                tickers.add(row["ticker"].strip().upper())
    return sorted(tickers)


def _cache_path(cache_dir: Path, ticker: str) -> Path:
    return cache_dir / f"{ticker}.json"


def _is_cache_fresh(cache_file: Path, max_age_days: int) -> bool:
    if not cache_file.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
    return age < timedelta(days=max_age_days)


def fetch_fundamentals(ticker: str, cache_dir: Path, max_age_days: int, errors: list[str]) -> dict[str, Any] | None:
    cache_file = _cache_path(cache_dir, ticker)
    if _is_cache_fresh(cache_file, max_age_days):
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)

    try:
        info = yf.Ticker(ticker).info
        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            raise ValueError("no price data returned")
    except Exception as exc:  # noqa: BLE001 - yfinance raises a variety of exception types
        errors.append(f"{ticker}: fundamentals fetch failed ({exc})")
        return None

    data = {field: info.get(field) for field in FUNDAMENTALS_FIELDS}
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def fetch_price_history(tickers: list[str], errors: list[str]) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    try:
        raw = yf.download(tickers, period="6mo", group_by="ticker", progress=False, threads=True)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"batch price download failed for all tickers ({exc})")
        return {}

    histories: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            df = raw[ticker] if len(tickers) > 1 else raw
            if df.dropna(how="all").empty:
                raise ValueError("empty history")
            histories[ticker] = df
        except (KeyError, ValueError) as exc:
            errors.append(f"{ticker}: price history missing ({exc})")
    return histories


def fetch_all(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    settings = load_settings(repo_root)
    cache_dir = resolve_path(settings, "price_cache", repo_root)
    max_age_days = settings.get("fundamentals_cache_days", 3)

    tickers = load_universe_tickers(settings, repo_root)
    errors: list[str] = []

    histories = fetch_price_history(tickers, errors)

    fundamentals: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        data = fetch_fundamentals(ticker, cache_dir, max_age_days, errors)
        if data is not None:
            fundamentals[ticker] = data
        time.sleep(0.25)  # be polite to Yahoo's endpoint, reduce throttling risk

    prices: dict[str, float] = {}
    for ticker, df in histories.items():
        if "Close" in df.columns and not df["Close"].dropna().empty:
            prices[ticker] = float(df["Close"].dropna().iloc[-1])
        elif ticker in fundamentals:
            p = fundamentals[ticker].get("currentPrice") or fundamentals[ticker].get("regularMarketPrice")
            if p is not None:
                prices[ticker] = float(p)

    result = {
        "as_of": date.today().isoformat(),
        "prices": prices,
        "fundamentals": fundamentals,
        "errors": errors,
    }

    out_path = cache_dir / "latest_fetch.json"
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def main() -> None:
    result = fetch_all()
    print(f"Fetched data for {len(result['prices'])} tickers as of {result['as_of']}")
    if result["errors"]:
        print(f"{len(result['errors'])} error(s):", file=sys.stderr)
        for err in result["errors"]:
            print(f"  - {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
