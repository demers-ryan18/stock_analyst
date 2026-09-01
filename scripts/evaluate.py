"""Decision logic: sell/trim criteria for holdings, buy screening for candidates.

Pure functions with no I/O side effects — they take portfolio/fetch data in and return
structured decisions out. The daily agent workflow (see AGENT.md) is responsible for
combining these quantitative flags with WebSearch/WebFetch news research before finalizing
a decision, and for actually writing the results to portfolio.json / transactions.csv.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils import (
    is_opportunity_tier,
    max_new_position_value,
    position_pct,
    room_in_opportunity_bucket,
    room_in_sector,
    total_portfolio_value,
)


@dataclass
class HoldingFlag:
    ticker: str
    flags: list[str] = field(default_factory=list)
    suggested_action: str = "HOLD"  # HOLD | TRIM | SELL | REVIEW
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_holding(
    holding: dict[str, Any],
    price: float | None,
    fundamentals: dict[str, Any] | None,
    settings: dict[str, Any],
    total_value: float,
) -> HoldingFlag:
    flag = HoldingFlag(ticker=holding["ticker"])

    if price is None:
        flag.flags.append("NO_PRICE_DATA")
        flag.suggested_action = "REVIEW"
        return flag

    cost_basis = holding.get("cost_basis_per_share")
    if cost_basis:
        pct_return = (price - cost_basis) / cost_basis
        flag.details["return_pct"] = round(pct_return, 4)
        if pct_return <= settings.get("stop_loss_pct", -0.25):
            flag.flags.append("STOP_LOSS_THRESHOLD")
            flag.suggested_action = "REVIEW"

    pos_pct = position_pct(holding, price, total_value)
    flag.details["position_pct"] = round(pos_pct, 4)
    cap = settings["max_position_pct"]
    tolerance = settings.get("trim_over_cap_tolerance_pct", 0.02)
    if pos_pct > cap + tolerance:
        flag.flags.append("OVER_POSITION_CAP")
        flag.suggested_action = "TRIM"

    if fundamentals:
        rev_growth = fundamentals.get("revenueGrowth")
        earn_growth = fundamentals.get("earningsGrowth")
        if rev_growth is not None and rev_growth < 0:
            flag.flags.append("NEGATIVE_REVENUE_GROWTH")
            if flag.suggested_action == "HOLD":
                flag.suggested_action = "REVIEW"
        if earn_growth is not None and earn_growth < -0.10:
            flag.flags.append("EARNINGS_DECLINING")
            if flag.suggested_action == "HOLD":
                flag.suggested_action = "REVIEW"
        flag.details["revenue_growth"] = rev_growth
        flag.details["earnings_growth"] = earn_growth

    return flag


def evaluate_all_holdings(
    portfolio: dict[str, Any],
    prices: dict[str, float],
    fundamentals: dict[str, dict[str, Any]],
    settings: dict[str, Any],
) -> list[HoldingFlag]:
    total_value = total_portfolio_value(portfolio, prices)
    return [
        evaluate_holding(h, prices.get(h["ticker"]), fundamentals.get(h["ticker"]), settings, total_value)
        for h in portfolio["holdings"]
    ]


@dataclass
class CandidateScore:
    ticker: str
    sector: str | None
    score: float
    reasons: list[str] = field(default_factory=list)
    max_buy_value: float = 0.0
    opportunity_tier: bool = False


def score_candidate(
    ticker: str,
    fundamentals: dict[str, Any] | None,
    portfolio: dict[str, Any],
    prices: dict[str, float],
    settings: dict[str, Any],
    total_value: float,
    all_fundamentals: dict[str, dict[str, Any]] | None = None,
) -> CandidateScore | None:
    """Simple growth-oriented quantitative screen. Returns None if fundamentals are
    missing/unusable; the agent's news research is what turns a positive score into
    an actual buy decision, this just narrows the field.

    No market-cap floor is applied here on purpose — small/micro-cap growth names score
    the same way large caps do. `opportunity_tier` candidates (below
    settings.opportunity_market_cap_threshold) are additionally gated by remaining room in
    the combined opportunity_bucket_max_pct, so the portfolio doesn't over-concentrate in
    smaller, less-established names even as it actively looks beyond blue chips for them.
    """
    if not fundamentals:
        return None

    already_held = any(h["ticker"] == ticker for h in portfolio["holdings"])
    if already_held:
        return None

    sector = fundamentals.get("sector")
    room = room_in_sector(settings, sector, portfolio, prices, total_value) if sector else float("inf")
    if room <= 0:
        return None

    opportunity_tier = is_opportunity_tier(fundamentals.get("marketCap"), settings)
    if opportunity_tier:
        opp_room = room_in_opportunity_bucket(portfolio, prices, all_fundamentals or {}, settings, total_value)
        if opp_room <= 0:
            return None
        room = min(room, opp_room)

    rev_growth = fundamentals.get("revenueGrowth") or 0.0
    earn_growth = fundamentals.get("earningsGrowth") or 0.0
    fwd_pe = fundamentals.get("forwardPE")

    reasons = []
    score = 0.0
    if rev_growth > 0.10:
        score += rev_growth * 10
        reasons.append(f"revenue growth {rev_growth:.1%}")
    if earn_growth > 0.10:
        score += earn_growth * 5
        reasons.append(f"earnings growth {earn_growth:.1%}")
    if fwd_pe and 0 < fwd_pe < 60:
        score += max(0, (60 - fwd_pe) / 60) * 3
        reasons.append(f"forward P/E {fwd_pe:.1f}")

    if score <= 0:
        return None

    max_buy = min(max_new_position_value(settings, total_value), room)
    return CandidateScore(
        ticker=ticker, sector=sector, score=score, reasons=reasons,
        max_buy_value=max_buy, opportunity_tier=opportunity_tier,
    )


def screen_candidates(
    watchlist_tickers: list[str],
    portfolio: dict[str, Any],
    prices: dict[str, float],
    fundamentals: dict[str, dict[str, Any]],
    settings: dict[str, Any],
) -> list[CandidateScore]:
    total_value = total_portfolio_value(portfolio, prices)
    scored = []
    for ticker in watchlist_tickers:
        result = score_candidate(
            ticker, fundamentals.get(ticker), portfolio, prices, settings, total_value,
            all_fundamentals=fundamentals,
        )
        if result:
            scored.append(result)
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored
