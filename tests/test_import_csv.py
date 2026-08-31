from pathlib import Path

from import_csv import detect_columns, parse_broker_csv
import pandas as pd

SAMPLE_CSV = Path(__file__).parent / "sample_broker_export.csv"


def test_detect_columns_maps_broker_synonyms():
    df = pd.read_csv(SAMPLE_CSV)
    mapping = detect_columns(df)
    assert mapping["ticker"] == "Symbol"
    assert mapping["shares"] == "Quantity"
    assert mapping["cost_basis_per_share"] == "Average Cost"


def test_parse_broker_csv_skips_zero_share_rows():
    holdings = parse_broker_csv(SAMPLE_CSV)
    tickers = {h["ticker"] for h in holdings}
    assert tickers == {"AAPL", "NVDA"}
    assert "XYZ" not in tickers


def test_parse_broker_csv_extracts_cost_basis():
    holdings = {h["ticker"]: h for h in parse_broker_csv(SAMPLE_CSV)}
    assert holdings["AAPL"]["shares"] == 10.0
    assert holdings["AAPL"]["cost_basis_per_share"] == 150.25
    assert holdings["NVDA"]["shares"] == 5.0


def test_detect_columns_raises_on_missing_required_fields():
    import pytest

    df = pd.DataFrame({"Foo": [1], "Bar": [2]})
    with pytest.raises(ValueError):
        detect_columns(df)
