from utils import (
    holdings_value,
    is_opportunity_tier,
    opportunity_bucket_pct,
    position_pct,
    room_in_opportunity_bucket,
    room_in_sector,
    sector_pct,
    total_portfolio_value,
)

PORTFOLIO = {
    "cash": 1000.0,
    "holdings": [
        {"ticker": "AAA", "shares": 10, "cost_basis_per_share": 100.0, "sector": "Technology"},
        {"ticker": "BBB", "shares": 5, "cost_basis_per_share": 200.0, "sector": "Health Care"},
    ],
}
PRICES = {"AAA": 110.0, "BBB": 220.0}


def test_holdings_value_uses_price_map():
    assert holdings_value(PORTFOLIO, PRICES) == 10 * 110.0 + 5 * 220.0


def test_holdings_value_falls_back_to_cost_basis_on_missing_price():
    partial_prices = {"AAA": 110.0}
    value = holdings_value(PORTFOLIO, partial_prices)
    assert value == 10 * 110.0 + 5 * 200.0  # BBB falls back to cost basis


def test_total_portfolio_value_includes_cash():
    total = total_portfolio_value(PORTFOLIO, PRICES)
    assert total == holdings_value(PORTFOLIO, PRICES) + 1000.0


def test_position_pct():
    total = total_portfolio_value(PORTFOLIO, PRICES)
    pct = position_pct(PORTFOLIO["holdings"][0], PRICES["AAA"], total)
    assert abs(pct - (1100.0 / total)) < 1e-9


def test_sector_pct():
    total = total_portfolio_value(PORTFOLIO, PRICES)
    pct = sector_pct("Technology", PORTFOLIO, PRICES, total)
    assert abs(pct - (1100.0 / total)) < 1e-9


def test_room_in_sector_respects_cap():
    settings = {"sector_max_pct": 0.30}
    total = total_portfolio_value(PORTFOLIO, PRICES)
    room = room_in_sector(settings, "Technology", PORTFOLIO, PRICES, total)
    expected = max(0.0, 0.30 * total - 1100.0)
    assert abs(room - expected) < 1e-6


def test_room_in_sector_zero_value_portfolio_no_crash():
    empty_portfolio = {"cash": 0.0, "holdings": []}
    settings = {"sector_max_pct": 0.30}
    room = room_in_sector(settings, "Technology", empty_portfolio, {}, 0.0)
    assert room == 0.0


OPP_SETTINGS = {"opportunity_market_cap_threshold": 10_000_000_000, "opportunity_bucket_max_pct": 0.20}


def test_is_opportunity_tier_below_threshold():
    assert is_opportunity_tier(2_000_000_000, OPP_SETTINGS) is True


def test_is_opportunity_tier_above_threshold():
    assert is_opportunity_tier(500_000_000_000, OPP_SETTINGS) is False


def test_is_opportunity_tier_unknown_market_cap():
    assert is_opportunity_tier(None, OPP_SETTINGS) is False


def test_opportunity_bucket_pct_only_counts_sub_threshold_holdings():
    fundamentals = {
        "AAA": {"marketCap": 2_000_000_000},   # Technology, small-cap -> counts
        "BBB": {"marketCap": 500_000_000_000},  # Health Care, mega-cap -> doesn't count
    }
    total = total_portfolio_value(PORTFOLIO, PRICES)
    pct = opportunity_bucket_pct(PORTFOLIO, PRICES, fundamentals, OPP_SETTINGS, total)
    assert abs(pct - (1100.0 / total)) < 1e-9  # only AAA's value (10 * 110)


def test_room_in_opportunity_bucket_respects_cap():
    fundamentals = {
        "AAA": {"marketCap": 2_000_000_000},
        "BBB": {"marketCap": 500_000_000_000},
    }
    total = total_portfolio_value(PORTFOLIO, PRICES)
    room = room_in_opportunity_bucket(PORTFOLIO, PRICES, fundamentals, OPP_SETTINGS, total)
    expected = max(0.0, 0.20 * total - 1100.0)
    assert abs(room - expected) < 1e-6


def test_room_in_opportunity_bucket_no_cap_configured():
    room = room_in_opportunity_bucket(PORTFOLIO, PRICES, {}, {}, total_portfolio_value(PORTFOLIO, PRICES))
    assert room == float("inf")
