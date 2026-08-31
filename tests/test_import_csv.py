from pathlib import Path

from import_csv import detect_columns, parse_broker_csv
import pandas as pd

SAMPLE_CSV = Path(__file__).parent / "sample_broker_export.csv"
MESSY_CSV = Path(__file__).parent / "sample_broker_export_messy.csv"


def test_detect_columns_maps_broker_synonyms():
    df = pd.read_csv(SAMPLE_CSV)
    mapping = detect_columns(df)
    assert mapping["ticker"] == "Symbol"
    assert mapping["shares"] == "Quantity"
    assert mapping["cost_basis_per_share"] == "Average Cost"


def test_parse_broker_csv_skips_zero_share_rows():
    holdings, _ = parse_broker_csv(SAMPLE_CSV)
    tickers = {h["ticker"] for h in holdings}
    assert tickers == {"AAPL", "NVDA"}
    assert "XYZ" not in tickers


def test_parse_broker_csv_extracts_cost_basis():
    holdings, _ = parse_broker_csv(SAMPLE_CSV)
    holdings = {h["ticker"]: h for h in holdings}
    assert holdings["AAPL"]["shares"] == 10.0
    assert holdings["AAPL"]["cost_basis_per_share"] == 150.25
    assert holdings["NVDA"]["shares"] == 5.0


def test_detect_columns_raises_on_missing_required_fields():
    import pytest

    df = pd.DataFrame({"Foo": [1], "Bar": [2]})
    with pytest.raises(ValueError):
        detect_columns(df)


def test_parse_broker_csv_handles_messy_fidelity_export():
    """Real Fidelity exports have a BOM, a trailing empty field on every data row
    (shifting columns under a naive parser), $-formatted currency strings, and
    legal-boilerplate footer text after a blank line - all present in this fixture."""
    holdings, cash = parse_broker_csv(MESSY_CSV)
    tickers = {h["ticker"] for h in holdings}
    assert tickers == {"AGX", "CRDO"}
    assert "SPAXX" not in tickers  # money-market sweep -> cash, not a holding

    by_ticker = {h["ticker"]: h for h in holdings}
    assert by_ticker["AGX"]["shares"] == 0.506
    assert by_ticker["AGX"]["cost_basis_per_share"] == 614.82
    assert by_ticker["CRDO"]["shares"] == 4.49
    assert by_ticker["CRDO"]["cost_basis_per_share"] == 270.52

    assert cash == 40.27
