import json
from pathlib import Path

import yaml

from record_history import load_history, record_today


def _make_repo(tmp_path: Path, total_holdings_value: float, cash: float, benchmark_price: float) -> Path:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data" / "price_cache").mkdir(parents=True, exist_ok=True)

    settings = {
        "benchmark_ticker": "SPY",
        "paths": {
            "portfolio": "data/portfolio.json",
            "price_cache": "data/price_cache",
            "history": "data/history.csv",
        },
    }
    with open(tmp_path / "config" / "settings.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f)

    portfolio = {
        "status": "active",
        "cash": cash,
        "holdings": [
            {"ticker": "AAA", "shares": 10, "cost_basis_per_share": 100.0, "sector": "Technology"},
        ],
    }
    with open(tmp_path / "data" / "portfolio.json", "w", encoding="utf-8") as f:
        json.dump(portfolio, f)

    fetch = {
        "as_of": "2026-01-01",
        "prices": {"AAA": total_holdings_value / 10, "SPY": benchmark_price},
        "fundamentals": {},
        "errors": [],
    }
    with open(tmp_path / "data" / "price_cache" / "latest_fetch.json", "w", encoding="utf-8") as f:
        json.dump(fetch, f)

    return tmp_path


def test_record_today_writes_row(tmp_path):
    repo = _make_repo(tmp_path, total_holdings_value=1000.0, cash=50.0, benchmark_price=500.0)
    row = record_today(repo)
    assert row["cash"] == "50.00"
    assert row["total_value"] == "1050.00"
    assert row["benchmark_price"] == "500.00"

    history = load_history(repo / "data" / "history.csv")
    assert len(history) == 1


def test_record_today_is_idempotent_per_day(tmp_path):
    repo = _make_repo(tmp_path, total_holdings_value=1000.0, cash=50.0, benchmark_price=500.0)
    record_today(repo)
    # Simulate a second run the same day with a changed value (e.g. a mid-run correction)
    _make_repo(tmp_path, total_holdings_value=1100.0, cash=40.0, benchmark_price=505.0)
    record_today(repo)

    history = load_history(repo / "data" / "history.csv")
    assert len(history) == 1  # replaced, not duplicated
    assert history[0]["total_value"] == "1140.00"
