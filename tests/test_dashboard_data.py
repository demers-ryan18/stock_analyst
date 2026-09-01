import csv
import json
from pathlib import Path

import yaml

from dashboard_data import build_dashboard_payload, build_performance_history, build_watchlist_view


def _write_settings(tmp_path: Path) -> None:
    settings = {
        "max_position_pct": 0.15,
        "sector_max_pct": 0.30,
        "cap_warning_threshold_pct": 0.85,
        "benchmark_ticker": "SPY",
        "trim_over_cap_tolerance_pct": 0.02,
        "stop_loss_pct": -0.25,
        "opportunity_market_cap_threshold": 10_000_000_000,
        "opportunity_bucket_max_pct": 0.20,
        "paths": {
            "portfolio": "data/portfolio.json",
            "transactions": "data/transactions.csv",
            "watchlist": "config/watchlist.csv",
            "price_cache": "data/price_cache",
            "history": "data/history.csv",
        },
    }
    with open(tmp_path / "config" / "settings.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f)


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data" / "price_cache").mkdir(parents=True, exist_ok=True)
    _write_settings(tmp_path)

    portfolio = {
        "status": "active",
        "cash": 100.0,
        "holdings": [
            {"ticker": "AAA", "shares": 1, "cost_basis_per_share": 100.0, "sector": "Technology"},
        ],
    }
    with open(tmp_path / "data" / "portfolio.json", "w", encoding="utf-8") as f:
        json.dump(portfolio, f)

    with open(tmp_path / "data" / "transactions.csv", "w", encoding="utf-8", newline="") as f:
        f.write("date,action,ticker,shares,price,amount,rationale,portfolio_value_after,cash_after\n")

    with open(tmp_path / "config" / "watchlist.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "sector", "added_date", "source", "status", "notes"])
        writer.writerow(["BBB", "Health Care", "2026-01-01", "seed", "active", "candidate note"])

    fetch = {
        "as_of": "2026-01-02",
        "prices": {"AAA": 120.0, "SPY": 500.0, "BBB": 50.0},
        "fundamentals": {
            "AAA": {"trailingPE": 30, "forwardPE": 25, "revenueGrowth": 0.2, "earningsGrowth": 0.3, "marketCap": 1e9},
            "BBB": {"revenueGrowth": 0.25, "earningsGrowth": 0.3, "forwardPE": 20, "sector": "Health Care"},
        },
        "errors": [],
    }
    with open(tmp_path / "data" / "price_cache" / "latest_fetch.json", "w", encoding="utf-8") as f:
        json.dump(fetch, f)

    return tmp_path


def test_build_performance_history_computes_returns_relative_to_first_row(tmp_path):
    repo = _make_repo(tmp_path)
    with open(repo / "data" / "history.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "total_value", "cash", "benchmark_price"])
        writer.writerow(["2026-01-01", "1000.00", "100.00", "500.00"])
        writer.writerow(["2026-01-02", "1100.00", "100.00", "550.00"])

    settings = yaml.safe_load(open(repo / "config" / "settings.yaml", encoding="utf-8"))
    history = build_performance_history(settings, repo)

    assert len(history) == 2
    assert history[0]["portfolio_return_pct"] == 0.0
    assert history[1]["portfolio_return_pct"] == 0.1
    assert history[1]["benchmark_return_pct"] == 0.1


def test_build_performance_history_empty_when_no_file(tmp_path):
    repo = _make_repo(tmp_path)
    settings = yaml.safe_load(open(repo / "config" / "settings.yaml", encoding="utf-8"))
    assert build_performance_history(settings, repo) == []


def test_build_watchlist_view_excludes_held_tickers_and_scores_candidates(tmp_path):
    repo = _make_repo(tmp_path)
    settings = yaml.safe_load(open(repo / "config" / "settings.yaml", encoding="utf-8"))
    portfolio = json.load(open(repo / "data" / "portfolio.json", encoding="utf-8"))
    fetch = json.load(open(repo / "data" / "price_cache" / "latest_fetch.json", encoding="utf-8"))

    view = build_watchlist_view(settings, portfolio, fetch["prices"], fetch["fundamentals"], repo)
    assert view["total_screened"] == 1
    assert len(view["top_candidates"]) == 1
    assert view["top_candidates"][0]["ticker"] == "BBB"
    assert view["top_candidates"][0]["notes"] == "candidate note"
    assert "opportunity_tier" in view["top_candidates"][0]


def test_build_dashboard_payload_includes_new_sections(tmp_path):
    repo = _make_repo(tmp_path)
    payload = build_dashboard_payload(repo)

    assert payload["benchmark_ticker"] == "SPY"
    assert "watchlist" in payload
    assert "performance_history" in payload
    holding = payload["holdings"][0]
    assert "fundamentals" in holding
    assert "position_cap_usage_pct" in holding
    assert "sector_cap_usage_pct" in payload["sector_allocation"][0]
    assert holding["opportunity_tier"] is True  # AAA's marketCap (1e9) is below the $10B threshold
    assert "opportunity_bucket" in payload
    assert payload["opportunity_bucket"]["cap_pct"] == 0.20
