from evaluate import evaluate_holding, score_candidate

SETTINGS = {
    "max_position_pct": 0.15,
    "sector_max_pct": 0.30,
    "trim_over_cap_tolerance_pct": 0.02,
    "stop_loss_pct": -0.25,
}


def test_evaluate_holding_flags_stop_loss():
    holding = {"ticker": "AAA", "shares": 10, "cost_basis_per_share": 100.0, "sector": "Technology"}
    flag = evaluate_holding(holding, price=70.0, fundamentals=None, settings=SETTINGS, total_value=10000.0)
    assert "STOP_LOSS_THRESHOLD" in flag.flags
    assert flag.suggested_action == "REVIEW"


def test_evaluate_holding_flags_over_position_cap():
    # 10 shares * 200 = 2000, out of total 10000 = 20% > 15% cap + 2% tolerance
    holding = {"ticker": "AAA", "shares": 10, "cost_basis_per_share": 100.0, "sector": "Technology"}
    flag = evaluate_holding(holding, price=200.0, fundamentals=None, settings=SETTINGS, total_value=10000.0)
    assert "OVER_POSITION_CAP" in flag.flags
    assert flag.suggested_action == "TRIM"


def test_evaluate_holding_no_price_data():
    holding = {"ticker": "AAA", "shares": 10, "cost_basis_per_share": 100.0, "sector": "Technology"}
    flag = evaluate_holding(holding, price=None, fundamentals=None, settings=SETTINGS, total_value=10000.0)
    assert flag.suggested_action == "REVIEW"
    assert "NO_PRICE_DATA" in flag.flags


def test_evaluate_holding_healthy_position_holds():
    holding = {"ticker": "AAA", "shares": 10, "cost_basis_per_share": 100.0, "sector": "Technology"}
    fundamentals = {"revenueGrowth": 0.15, "earningsGrowth": 0.20}
    flag = evaluate_holding(holding, price=105.0, fundamentals=fundamentals, settings=SETTINGS, total_value=10000.0)
    assert flag.suggested_action == "HOLD"
    assert flag.flags == []


def test_score_candidate_skips_already_held():
    portfolio = {"holdings": [{"ticker": "AAA", "shares": 1, "cost_basis_per_share": 1.0, "sector": "Technology"}]}
    fundamentals = {"revenueGrowth": 0.20, "earningsGrowth": 0.20, "forwardPE": 30, "sector": "Technology"}
    result = score_candidate("AAA", fundamentals, portfolio, {}, SETTINGS, total_value=10000.0)
    assert result is None


def test_score_candidate_scores_growth_positively():
    portfolio = {"holdings": []}
    fundamentals = {"revenueGrowth": 0.25, "earningsGrowth": 0.30, "forwardPE": 25, "sector": "Technology"}
    result = score_candidate("BBB", fundamentals, portfolio, {}, SETTINGS, total_value=10000.0)
    assert result is not None
    assert result.score > 0
    assert result.max_buy_value > 0


def test_score_candidate_no_fundamentals_returns_none():
    portfolio = {"holdings": []}
    result = score_candidate("BBB", None, portfolio, {}, SETTINGS, total_value=10000.0)
    assert result is None
