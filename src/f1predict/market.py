"""Market edge analysis."""

from __future__ import annotations

from datetime import datetime, timezone

from f1predict.domain import DriverRaceProbability, MarketEdge, MarketSnapshot, parse_dt


def event_market_snapshots(
    markets: list[MarketSnapshot],
    event_id: str,
    knowledge_cutoff: datetime | None = None,
    market_type: str | None = None,
) -> list[MarketSnapshot]:
    """Return the latest event market snapshots available at the cutoff."""

    latest_by_market_id: dict[str, MarketSnapshot] = {}
    for market in markets:
        if market.event_id != event_id:
            continue
        if market_type is not None and market.market_type != market_type:
            continue
        if market.is_available(knowledge_cutoff):
            current = latest_by_market_id.get(market.market_id)
            if current is None or _captured_sort_key(market) >= _captured_sort_key(current):
                latest_by_market_id[market.market_id] = market
    rows = list(latest_by_market_id.values())
    return sorted(rows, key=lambda market: (_captured_sort_key(market), market.market_id))


def after_cutoff_market_count(
    markets: list[MarketSnapshot],
    event_id: str,
    knowledge_cutoff: datetime | None = None,
    market_type: str | None = None,
) -> int:
    if knowledge_cutoff is None:
        return 0
    return sum(
        1
        for market in markets
        if market.event_id == event_id
        and (market_type is None or market.market_type == market_type)
        and not market.is_available(knowledge_cutoff)
    )


def _captured_sort_key(market: MarketSnapshot) -> datetime:
    parsed = parse_dt(market.captured_at)
    if parsed is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MarketAnalyzer:
    def __init__(
        self,
        fee_rate: float = 0.015,
        uncertainty_buffer: float = 0.025,
        calibration_shrinkage: float = 0.25,
    ) -> None:
        self.fee_rate = fee_rate
        self.uncertainty_buffer = uncertainty_buffer
        self.calibration_shrinkage = calibration_shrinkage

    def compare_winner_market(
        self,
        market: MarketSnapshot,
        probabilities: list[DriverRaceProbability],
    ) -> list[MarketEdge]:
        by_driver = {item.driver_id: item for item in probabilities}
        model_probabilities = {
            outcome_id: by_driver[outcome_id].win
            for outcome_id in market.prices
            if outcome_id in by_driver
        }
        return self.compare_probability_market(market, model_probabilities)

    def compare_probability_market(
        self,
        market: MarketSnapshot,
        model_probabilities: dict[str, float],
    ) -> list[MarketEdge]:
        edges: list[MarketEdge] = []
        market_outcomes = [outcome_id for outcome_id in market.prices if outcome_id in model_probabilities]
        uniform_probability = 1.0 / len(market_outcomes) if market_outcomes else 0.0
        for outcome_id, market_probability in market.prices.items():
            if outcome_id not in model_probabilities:
                continue
            model_probability = model_probabilities[outcome_id]
            calibration_baseline = self._calibration_baseline(
                market,
                outcome_count=len(market_outcomes),
                uniform_probability=uniform_probability,
                market_probability=market_probability,
            )
            conservative_probability = self._conservative_probability(model_probability, calibration_baseline)
            estimated_cost = self._cost(market_probability, market.spread_estimate)
            edge_before_cost = model_probability - market_probability
            edge_after_cost = edge_before_cost - estimated_cost
            conservative_edge_after_cost = conservative_probability - market_probability - estimated_cost
            risk_flags = self._risk_flags(edge_after_cost, conservative_edge_after_cost, market, len(market_outcomes))
            edges.append(
                MarketEdge(
                    market_id=market.market_id,
                    market_type=market.market_type,
                    outcome_id=outcome_id,
                    model_probability=round(model_probability, 4),
                    market_probability=round(market_probability, 4),
                    edge_before_cost=round(edge_before_cost, 4),
                    estimated_cost=round(estimated_cost, 4),
                    edge_after_cost=round(edge_after_cost, 4),
                    recommendation=self._recommendation(conservative_edge_after_cost),
                    conservative_model_probability=round(conservative_probability, 4),
                    conservative_edge_after_cost=round(conservative_edge_after_cost, 4),
                    calibration_adjustment=round(conservative_probability - model_probability, 4),
                    risk_flags=risk_flags,
                )
            )
        edges.sort(
            key=lambda item: (
                item.conservative_edge_after_cost if item.conservative_edge_after_cost is not None else item.edge_after_cost
            ),
            reverse=True,
        )
        return edges

    def _cost(self, probability: float, spread: float) -> float:
        taker_fee = self.fee_rate * probability * (1.0 - probability)
        return taker_fee + spread / 2.0 + self.uncertainty_buffer

    @staticmethod
    def _calibration_baseline(
        market: MarketSnapshot,
        outcome_count: int,
        uniform_probability: float,
        market_probability: float,
    ) -> float:
        if market.market_type == "winner" and outcome_count > 1:
            return uniform_probability
        return market_probability

    def _conservative_probability(self, probability: float, uniform_probability: float) -> float:
        shrinkage = min(0.95, max(0.0, self.calibration_shrinkage))
        return probability * (1.0 - shrinkage) + uniform_probability * shrinkage

    @staticmethod
    def _risk_flags(
        raw_edge_after_cost: float,
        conservative_edge_after_cost: float,
        market: MarketSnapshot,
        outcome_count: int,
    ) -> tuple[str, ...]:
        flags = ["diagnostic_conservative_calibration"]
        if market.market_type != "winner":
            flags.append("non_winner_market_diagnostic_only")
        if outcome_count <= 1:
            flags.append("single_outcome_market_shrunk_to_price")
        if raw_edge_after_cost > 0.0 and conservative_edge_after_cost <= 0.0:
            flags.append("raw_edge_removed_by_calibration")
        if raw_edge_after_cost >= 0.035 and conservative_edge_after_cost < 0.035:
            flags.append("recommendation_downgraded_by_calibration")
        return tuple(flags)

    @staticmethod
    def _recommendation(edge_after_cost: float) -> str:
        if edge_after_cost >= 0.06:
            return "paper_taker_candidate"
        if edge_after_cost >= 0.035:
            return "paper_maker_only"
        return "no_trade"
