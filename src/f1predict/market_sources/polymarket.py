"""Normalize Polymarket market payloads into project market snapshots."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from f1predict.data_sources.http_clients import PolymarketMarketClient
from f1predict.domain import Driver, MarketSnapshot, RaceEvent, SeasonState, Team, parse_dt, utc_now
from f1predict.market_outcomes import (
    CONSTRUCTOR_DOUBLE_PODIUM,
    DRIVER_H2H,
    SUPPORTED_MARKET_TYPES,
    WINNER,
    driver_h2h_outcome_id,
)
from f1predict.storage import safe_name


MANUAL_EVENT_ALIASES = {
    "azerbaijan_gp": ("azerbaijan grand prix", "azerbijan grand prix", "baku grand prix"),
    "barcelona_gp": (
        "spanish grand prix",
        "spanish gp",
        "spain grand prix",
        "catalunya grand prix",
        "barcelona catalunya grand prix",
    ),
    "british_gp": ("british grand prix", "silverstone grand prix", "silverstone gp"),
    "mexico_city_gp": ("mexico city grand prix", "mexican grand prix", "mexico grand prix"),
    "sao_paulo_gp": ("sao paulo grand prix", "brazilian grand prix", "brazil grand prix"),
    "spanish_gp": ("spanish grand prix", "barcelona grand prix", "barcelona gp"),
    "united_states_gp": ("united states grand prix", "us grand prix", "u.s. grand prix", "austin grand prix"),
}


@dataclass(frozen=True)
class PolymarketNormalizationIssue:
    code: str
    severity: str
    market_id: str | None
    question: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class PolymarketDriverMarketDefinition:
    market_id: str
    event_id: str
    market_type: str
    outcome_id: str
    token_id: str
    source_market_id: str | None
    question: str
    liquidity: float
    spread_estimate: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class PolymarketNormalizationResult:
    event_id: str
    captured_at: str
    snapshots: tuple[MarketSnapshot, ...]
    definitions: tuple[PolymarketDriverMarketDefinition, ...]
    issues: tuple[PolymarketNormalizationIssue, ...]
    ignored_market_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "captured_at": self.captured_at,
            "snapshot_count": len(self.snapshots),
            "definition_count": len(self.definitions),
            "ignored_market_count": self.ignored_market_count,
            "snapshots": [snapshot.__dict__ for snapshot in self.snapshots],
            "definitions": [definition.to_dict() for definition in self.definitions],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PolymarketHistoryBackfillResult:
    event_id: str
    knowledge_cutoff: str
    snapshots: tuple[MarketSnapshot, ...]
    definitions: tuple[PolymarketDriverMarketDefinition, ...]
    issues: tuple[PolymarketNormalizationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "knowledge_cutoff": self.knowledge_cutoff,
            "snapshot_count": len(self.snapshots),
            "definition_count": len(self.definitions),
            "snapshots": [snapshot.__dict__ for snapshot in self.snapshots],
            "definitions": [definition.to_dict() for definition in self.definitions],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PolymarketSearchHistoryBackfillResult:
    event_id: str
    knowledge_cutoff: str
    market_type: str
    include_closed: bool
    limit: int
    lookback_hours: int
    fidelity_minutes: int
    queries: tuple[PolymarketSearchQueryResult, ...]
    unique_market_count: int
    search_payload: tuple[dict[str, Any], ...]
    snapshots: tuple[MarketSnapshot, ...]
    definitions: tuple[PolymarketDriverMarketDefinition, ...]
    issues: tuple[PolymarketNormalizationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "knowledge_cutoff": self.knowledge_cutoff,
            "market_type": self.market_type,
            "include_closed": self.include_closed,
            "limit": self.limit,
            "lookback_hours": self.lookback_hours,
            "fidelity_minutes": self.fidelity_minutes,
            "query_count": len(self.queries),
            "total_search_results": sum(query.result_count for query in self.queries),
            "unique_market_count": self.unique_market_count,
            "snapshot_count": len(self.snapshots),
            "definition_count": len(self.definitions),
            "issue_count": len(self.issues),
            "queries": [query.to_dict() for query in self.queries],
            "snapshots": [snapshot.__dict__ for snapshot in self.snapshots],
            "definitions": [definition.to_dict() for definition in self.definitions],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PolymarketOrderBookQuote:
    market_id: str
    outcome_id: str
    token_id: str
    status: str
    displayed_price: float | None
    best_bid: float | None
    best_ask: float | None
    midpoint: float | None
    last_trade_price: float | None
    spread: float | None
    bid_depth: float
    ask_depth: float
    book_timestamp: str | None
    book_hash: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class PolymarketLiveSnapshotResult:
    event_id: str
    captured_at: str
    market_type: str
    snapshots: tuple[MarketSnapshot, ...]
    definitions: tuple[PolymarketDriverMarketDefinition, ...]
    quotes: tuple[PolymarketOrderBookQuote, ...]
    issues: tuple[PolymarketNormalizationIssue, ...]
    queries: tuple[PolymarketSearchQueryResult, ...]
    unique_market_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "captured_at": self.captured_at,
            "market_type": self.market_type,
            "snapshot_count": len(self.snapshots),
            "definition_count": len(self.definitions),
            "quote_count": len(self.quotes),
            "unique_market_count": self.unique_market_count,
            "snapshots": [snapshot.__dict__ for snapshot in self.snapshots],
            "definitions": [definition.to_dict() for definition in self.definitions],
            "quotes": [quote.to_dict() for quote in self.quotes],
            "issues": [issue.to_dict() for issue in self.issues],
            "queries": [query.to_dict() for query in self.queries],
        }


@dataclass(frozen=True)
class PolymarketDiscoveryRow:
    event_id: str
    event_name: str
    round_number: int
    date: str
    completed: bool
    snapshot_count: int
    definition_count: int
    issue_counts: dict[str, int]
    definitions: tuple[PolymarketDriverMarketDefinition, ...]
    issues: tuple[PolymarketNormalizationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "round_number": self.round_number,
            "date": self.date,
            "completed": self.completed,
            "snapshot_count": self.snapshot_count,
            "definition_count": self.definition_count,
            "issue_counts": self.issue_counts,
            "definitions": [definition.to_dict() for definition in self.definitions],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PolymarketDiscoveryReport:
    season: int
    generated_at: str
    market_type: str
    include_closed: bool
    input_market_count: int
    event_count: int
    events_with_snapshots: int
    events_with_definitions: int
    total_snapshots: int
    total_definitions: int
    issue_counts: dict[str, int]
    rows: tuple[PolymarketDiscoveryRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "generated_at": self.generated_at,
            "market_type": self.market_type,
            "include_closed": self.include_closed,
            "input_market_count": self.input_market_count,
            "event_count": self.event_count,
            "events_with_snapshots": self.events_with_snapshots,
            "events_with_definitions": self.events_with_definitions,
            "total_snapshots": self.total_snapshots,
            "total_definitions": self.total_definitions,
            "issue_counts": self.issue_counts,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class PolymarketSearchQueryResult:
    query: str
    result_count: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class PolymarketSeasonSearchRow:
    event_id: str
    event_name: str
    round_number: int
    date: str
    completed: bool
    queries: tuple[PolymarketSearchQueryResult, ...]
    unique_market_count: int
    snapshot_count: int
    definition_count: int
    issue_counts: dict[str, int]
    definitions: tuple[PolymarketDriverMarketDefinition, ...]
    issues: tuple[PolymarketNormalizationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "round_number": self.round_number,
            "date": self.date,
            "completed": self.completed,
            "queries": [query.to_dict() for query in self.queries],
            "unique_market_count": self.unique_market_count,
            "snapshot_count": self.snapshot_count,
            "definition_count": self.definition_count,
            "issue_counts": self.issue_counts,
            "definitions": [definition.to_dict() for definition in self.definitions],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PolymarketSeasonSearchReport:
    season: int
    generated_at: str
    market_type: str
    include_closed: bool
    limit: int
    event_count: int
    query_count: int
    total_search_results: int
    total_unique_markets: int
    events_with_snapshots: int
    events_with_definitions: int
    total_snapshots: int
    total_definitions: int
    issue_counts: dict[str, int]
    rows: tuple[PolymarketSeasonSearchRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "generated_at": self.generated_at,
            "market_type": self.market_type,
            "include_closed": self.include_closed,
            "limit": self.limit,
            "event_count": self.event_count,
            "query_count": self.query_count,
            "total_search_results": self.total_search_results,
            "total_unique_markets": self.total_unique_markets,
            "events_with_snapshots": self.events_with_snapshots,
            "events_with_definitions": self.events_with_definitions,
            "total_snapshots": self.total_snapshots,
            "total_definitions": self.total_definitions,
            "issue_counts": self.issue_counts,
            "rows": [row.to_dict() for row in self.rows],
        }


class PolymarketGammaNormalizer:
    """Converts Gamma event/market responses into normalized snapshots.

    The normalizer is intentionally conservative. It only emits a snapshot when
    it can match the Polymarket text to a known F1 event and driver outcome.
    Ambiguous "another driver" or unsupported market types become review issues.
    """

    def __init__(self, season: SeasonState) -> None:
        self.season = season
        self.events_by_id = {event.event_id: event for event in season.events}
        self.driver_aliases = self._driver_aliases(season.drivers.values())
        self.team_aliases = self._team_aliases(season.teams.values())

    def normalize_payload(
        self,
        payload: Any,
        event_id: str,
        captured_at: str | None = None,
        market_type: str = "winner",
        event_aliases: Iterable[str] = (),
        include_closed: bool = False,
    ) -> PolymarketNormalizationResult:
        event = self.events_by_id.get(event_id)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")

        observed_at = captured_at or utc_now().replace(microsecond=0).isoformat()
        aliases = self._event_aliases(event, tuple(event_aliases))
        snapshots: list[MarketSnapshot] = []
        definitions: list[PolymarketDriverMarketDefinition] = []
        issues: list[PolymarketNormalizationIssue] = []
        ignored = 0

        for market, context in self._iter_markets(payload):
            question = self._market_text(market, context)
            if not self._matches_alias(question, aliases):
                ignored += 1
                continue
            market_years = self._market_years(self._market_text(market, ()))
            context_years = self._market_years(question)
            mismatch_years = market_years or context_years
            if mismatch_years and self.season.season not in mismatch_years:
                ignored += 1
                issues.append(
                    self._issue(
                        "season_mismatch",
                        "warning",
                        market,
                        question,
                        f"Matched event alias, but market text references years {sorted(mismatch_years)} not season {self.season.season}.",
                    )
                )
                continue
            if not include_closed and self._is_closed(market):
                ignored += 1
                issues.append(
                    self._issue(
                        "closed_market_ignored",
                        "info",
                        market,
                        question,
                        "Market is closed or inactive in this payload; pass include_closed for diagnostic normalization.",
                    )
                )
                continue
            if market_type == WINNER and not self._winnerish(question):
                ignored += 1
                issues.append(
                    self._issue(
                        "unsupported_market_type",
                        "review",
                        market,
                        question,
                        "Matched the event, but the text does not look like a winner market.",
                    )
                )
                continue
            if market_type == CONSTRUCTOR_DOUBLE_PODIUM and not self._constructor_double_podiumish(question):
                ignored += 1
                issues.append(
                    self._issue(
                        "unsupported_market_type",
                        "review",
                        market,
                        question,
                        "Matched the event, but the text does not look like a constructor double-podium market.",
                    )
                )
                continue
            if market_type == DRIVER_H2H and not self._driver_h2hish(question):
                ignored += 1
                issues.append(
                    self._issue(
                        "unsupported_market_type",
                        "review",
                        market,
                        question,
                        "Matched the event, but the text does not look like a driver head-to-head market.",
                    )
                )
                continue
            if market_type not in SUPPORTED_MARKET_TYPES:
                ignored += 1
                issues.append(
                    self._issue(
                        "unsupported_market_type",
                        "review",
                        market,
                        question,
                        f"Unsupported market_type={market_type!r}.",
                    )
                )
                continue

            outcome_prices = self._outcome_prices(market)
            if outcome_prices is None:
                issues.append(
                    self._issue(
                        "malformed_prices",
                        "warning",
                        market,
                        question,
                        "Could not parse aligned outcomes and outcomePrices arrays.",
                    )
                )
                continue

            if market_type == CONSTRUCTOR_DOUBLE_PODIUM:
                prices = self._team_binary_prices(question, outcome_prices, issues, market)
                definitions.extend(
                    self._team_binary_definitions(
                        question,
                        outcome_prices,
                        self._outcome_tokens(market),
                        issues,
                        market,
                        event_id,
                        market_type,
                    )
                )
            elif market_type == DRIVER_H2H:
                prices = self._driver_h2h_prices(question, outcome_prices, issues, market)
                definitions.extend(
                    self._driver_h2h_definitions(
                        question,
                        outcome_prices,
                        self._outcome_tokens(market),
                        issues,
                        market,
                        event_id,
                        market_type,
                    )
                )
            else:
                prices = self._driver_prices(question, outcome_prices, issues, market)
                definitions.extend(
                    self._driver_definitions(
                        question,
                        outcome_prices,
                        self._outcome_tokens(market),
                        issues,
                        market,
                        event_id,
                        market_type,
                    )
                )
            if not prices:
                ignored += 1
                continue

            snapshots.append(
                MarketSnapshot(
                    market_id=self._snapshot_market_id(market, event_id),
                    event_id=event_id,
                    market_type=market_type,
                    captured_at=observed_at,
                    prices=prices,
                    liquidity=self._liquidity(market),
                    spread_estimate=self._spread(market),
                )
            )

        return PolymarketNormalizationResult(
            event_id=event_id,
            captured_at=observed_at,
            snapshots=tuple(_dedupe_snapshots(snapshots)),
            definitions=tuple(_dedupe_definitions(definitions)),
            issues=tuple(_dedupe_issues(issues)),
            ignored_market_count=ignored,
        )

    def _driver_prices(
        self,
        question: str,
        outcome_prices: list[tuple[str, float]],
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
    ) -> dict[str, float]:
        outcome_names = [_compact(outcome) for outcome, _ in outcome_prices]
        if "yes" in outcome_names and "no" in outcome_names:
            driver_id = self._driver_from_text(question)
            if driver_id is None:
                issues.append(
                    self._issue(
                        "unrecognized_driver",
                        "review",
                        market,
                        question,
                        "Binary Yes/No market matched the event, but no known driver was identified.",
                    )
                )
                return {}
            yes_price = next(price for outcome, price in outcome_prices if _compact(outcome) == "yes")
            return {driver_id: yes_price}

        prices: dict[str, float] = {}
        for outcome, price in outcome_prices:
            driver_id = self._driver_from_text(outcome)
            if driver_id is None:
                issues.append(
                    self._issue(
                        "unrecognized_outcome",
                        "review",
                        market,
                        question,
                        f"Could not map outcome {outcome!r} to a known driver.",
                    )
                )
                continue
            prices[driver_id] = price
        return prices

    def _driver_h2h_prices(
        self,
        question: str,
        outcome_prices: list[tuple[str, float]],
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
    ) -> dict[str, float]:
        pair = self._driver_h2h_pair(question, issues, market)
        if pair is None:
            return {}
        driver_a, driver_b = pair
        outcome_names = [_compact(outcome) for outcome, _ in outcome_prices]
        if "yes" in outcome_names and "no" in outcome_names:
            if not self._binary_h2h_has_direction(question):
                issues.append(
                    self._issue(
                        "ambiguous_h2h_binary_market",
                        "review",
                        market,
                        question,
                        "Binary Yes/No H2H market did not clearly state that the first driver finishes ahead.",
                    )
                )
                return {}
            yes_price = next(price for outcome, price in outcome_prices if _compact(outcome) == "yes")
            return {driver_h2h_outcome_id(driver_a, driver_b): yes_price}

        prices: dict[str, float] = {}
        for outcome, price in outcome_prices:
            driver_id = self._driver_from_text(outcome)
            if driver_id is None or driver_id not in pair:
                issues.append(
                    self._issue(
                        "unrecognized_h2h_outcome",
                        "review",
                        market,
                        question,
                        f"Could not map H2H outcome {outcome!r} to one of the paired drivers.",
                    )
                )
                continue
            opponent_id = driver_b if driver_id == driver_a else driver_a
            prices[driver_h2h_outcome_id(driver_id, opponent_id)] = price
        return prices

    def _team_binary_prices(
        self,
        question: str,
        outcome_prices: list[tuple[str, float]],
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
    ) -> dict[str, float]:
        outcome_names = [_compact(outcome) for outcome, _ in outcome_prices]
        if "yes" in outcome_names and "no" in outcome_names:
            team_id = self._team_from_text(question)
            if team_id is None:
                issues.append(
                    self._issue(
                        "unrecognized_team",
                        "review",
                        market,
                        question,
                        "Binary Yes/No market matched the event, but no known constructor/team was identified.",
                    )
                )
                return {}
            yes_price = next(price for outcome, price in outcome_prices if _compact(outcome) == "yes")
            return {team_id: yes_price}

        prices: dict[str, float] = {}
        for outcome, price in outcome_prices:
            team_id = self._team_from_text(outcome)
            if team_id is None:
                issues.append(
                    self._issue(
                        "unrecognized_team_outcome",
                        "review",
                        market,
                        question,
                        f"Could not map outcome {outcome!r} to a known constructor/team.",
                    )
                )
                continue
            prices[team_id] = price
        return prices

    def _driver_definitions(
        self,
        question: str,
        outcome_prices: list[tuple[str, float]],
        token_ids: list[str],
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
        event_id: str,
        market_type: str,
    ) -> list[PolymarketDriverMarketDefinition]:
        outcome_names = [_compact(outcome) for outcome, _ in outcome_prices]
        if len(token_ids) != len(outcome_prices):
            issues.append(
                self._issue(
                    "missing_clob_token",
                    "review",
                    market,
                    question,
                    "Could not parse clobTokenIds aligned with outcomes; price-history backfill is disabled for this market.",
                )
            )
            return []

        rows: list[PolymarketDriverMarketDefinition] = []
        if "yes" in outcome_names and "no" in outcome_names:
            driver_id = self._driver_from_text(question)
            if driver_id is None:
                return []
            yes_index = outcome_names.index("yes")
            rows.append(self._definition(market, event_id, market_type, driver_id, token_ids[yes_index], question))
            return rows

        for index, (outcome, _) in enumerate(outcome_prices):
            driver_id = self._driver_from_text(outcome)
            if driver_id is None:
                continue
            rows.append(self._definition(market, event_id, market_type, driver_id, token_ids[index], question))
        return rows

    def _driver_h2h_definitions(
        self,
        question: str,
        outcome_prices: list[tuple[str, float]],
        token_ids: list[str],
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
        event_id: str,
        market_type: str,
    ) -> list[PolymarketDriverMarketDefinition]:
        if len(token_ids) != len(outcome_prices):
            issues.append(
                self._issue(
                    "missing_clob_token",
                    "review",
                    market,
                    question,
                    "Could not parse clobTokenIds aligned with H2H outcomes; price-history backfill is disabled.",
                )
            )
            return []
        pair = self._driver_h2h_pair(question, issues, market)
        if pair is None:
            return []
        driver_a, driver_b = pair
        outcome_names = [_compact(outcome) for outcome, _ in outcome_prices]
        rows: list[PolymarketDriverMarketDefinition] = []
        if "yes" in outcome_names and "no" in outcome_names:
            if not self._binary_h2h_has_direction(question):
                return []
            yes_index = outcome_names.index("yes")
            rows.append(
                self._definition(
                    market,
                    event_id,
                    market_type,
                    driver_h2h_outcome_id(driver_a, driver_b),
                    token_ids[yes_index],
                    question,
                )
            )
            return rows

        for index, (outcome, _) in enumerate(outcome_prices):
            driver_id = self._driver_from_text(outcome)
            if driver_id is None or driver_id not in pair:
                continue
            opponent_id = driver_b if driver_id == driver_a else driver_a
            rows.append(
                self._definition(
                    market,
                    event_id,
                    market_type,
                    driver_h2h_outcome_id(driver_id, opponent_id),
                    token_ids[index],
                    question,
                )
            )
        return rows

    def _team_binary_definitions(
        self,
        question: str,
        outcome_prices: list[tuple[str, float]],
        token_ids: list[str],
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
        event_id: str,
        market_type: str,
    ) -> list[PolymarketDriverMarketDefinition]:
        outcome_names = [_compact(outcome) for outcome, _ in outcome_prices]
        if len(token_ids) != len(outcome_prices):
            issues.append(
                self._issue(
                    "missing_clob_token",
                    "review",
                    market,
                    question,
                    "Could not parse clobTokenIds aligned with outcomes; price-history backfill is disabled for this market.",
                )
            )
            return []

        rows: list[PolymarketDriverMarketDefinition] = []
        if "yes" in outcome_names and "no" in outcome_names:
            team_id = self._team_from_text(question)
            if team_id is None:
                return []
            yes_index = outcome_names.index("yes")
            rows.append(self._definition(market, event_id, market_type, team_id, token_ids[yes_index], question))
            return rows

        for index, (outcome, _) in enumerate(outcome_prices):
            team_id = self._team_from_text(outcome)
            if team_id is None:
                continue
            rows.append(self._definition(market, event_id, market_type, team_id, token_ids[index], question))
        return rows

    @staticmethod
    def _iter_markets(payload: Any, context: tuple[dict[str, Any], ...] = ()) -> Iterable[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
        if isinstance(payload, list):
            for item in payload:
                yield from PolymarketGammaNormalizer._iter_markets(item, context)
            return
        if not isinstance(payload, dict):
            return
        for container_key in ("events", "data"):
            if isinstance(payload.get(container_key), list):
                for item in payload[container_key]:
                    yield from PolymarketGammaNormalizer._iter_markets(item, context)
        if isinstance(payload.get("markets"), list):
            next_context = context + (payload,)
            for item in payload["markets"]:
                yield from PolymarketGammaNormalizer._iter_markets(item, next_context)
        if "question" in payload and "outcomes" in payload:
            yield payload, context

    def _event_aliases(self, event: RaceEvent, extra: tuple[str, ...]) -> tuple[str, ...]:
        event_words = event.event_id.replace("_gp", "").replace("_", " ")
        aliases = {
            event.name,
            event.name.replace("Grand Prix", "GP"),
            event.event_id.replace("_", " "),
            f"{event_words} grand prix",
            f"{event_words} gp",
        }
        aliases.update(MANUAL_EVENT_ALIASES.get(event.event_id, ()))
        aliases.update(extra)
        return tuple(alias for alias in aliases if alias)

    @staticmethod
    def _matches_alias(text: str, aliases: tuple[str, ...]) -> bool:
        compact_text = _compact(text)
        return any(_compact(alias) in compact_text for alias in aliases)

    @staticmethod
    def _winnerish(text: str) -> bool:
        compact_text = _compact(text)
        return any(token in compact_text for token in ("winner", "winthe", "winf1", "grandprixwinner"))

    @staticmethod
    def _constructor_double_podiumish(text: str) -> bool:
        compact_text = _compact(text)
        return "doublepodium" in compact_text

    @staticmethod
    def _driver_h2hish(text: str) -> bool:
        compact_text = _compact(text)
        return any(
            token in compact_text
            for token in (
                "headtohead",
                "h2h",
                "finishahead",
                "finishesahead",
                "ahead",
                "beat",
                "beats",
                "versus",
            )
        ) or "vs" in compact_text

    @staticmethod
    def _binary_h2h_has_direction(text: str) -> bool:
        compact_text = _compact(text)
        return any(
            token in compact_text
            for token in (
                "finishahead",
                "finishesahead",
                "ahead",
                "beat",
                "beats",
                "outscore",
                "outscores",
            )
        )

    def _driver_h2h_pair(
        self,
        question: str,
        issues: list[PolymarketNormalizationIssue],
        market: dict[str, Any],
    ) -> tuple[str, str] | None:
        drivers = self._driver_mentions(question)
        if len(drivers) < 2:
            issues.append(
                self._issue(
                    "unrecognized_h2h_drivers",
                    "review",
                    market,
                    question,
                    "Driver H2H market matched the event, but two known drivers could not be identified.",
                )
            )
            return None
        return drivers[0], drivers[1]

    @staticmethod
    def _market_years(text: str) -> set[int]:
        return {int(item) for item in re.findall(r"\b20\d{2}\b", text)}

    def _driver_from_text(self, text: str) -> str | None:
        compact_text = _compact(text)
        matches = [
            driver_id
            for alias, driver_id in self.driver_aliases.items()
            if alias and alias in compact_text
        ]
        if not matches:
            return None
        unique = tuple(dict.fromkeys(matches))
        return unique[0] if len(unique) == 1 else None

    def _driver_mentions(self, text: str) -> list[str]:
        compact_text = _compact(text)
        positions: dict[str, tuple[int, int]] = {}
        for alias, driver_id in self.driver_aliases.items():
            if not alias:
                continue
            index = compact_text.find(alias)
            if index < 0:
                continue
            current = positions.get(driver_id)
            candidate = (index, len(alias))
            if current is None or index < current[0] or (index == current[0] and len(alias) > current[1]):
                positions[driver_id] = candidate
        return [
            driver_id
            for driver_id, _ in sorted(
                positions.items(),
                key=lambda item: (item[1][0], -item[1][1], item[0]),
            )
        ]

    def _team_from_text(self, text: str) -> str | None:
        compact_text = _compact(text)
        if "anotherteam" in compact_text or compact_text in {"other", "otherteam"}:
            return None
        matches = [
            team_id
            for alias, team_id in self.team_aliases.items()
            if alias and alias in compact_text
        ]
        if not matches:
            return None
        unique = tuple(dict.fromkeys(matches))
        return unique[0] if len(unique) == 1 else None

    @staticmethod
    def _driver_aliases(drivers: Iterable[Driver]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for driver in drivers:
            parts = driver.name.split()
            raw_aliases = {
                driver.driver_id,
                driver.name,
                parts[-1] if parts else "",
            }
            if driver.driver_id == "sainz":
                raw_aliases.add("Carlos Sainz Jr")
            if driver.driver_id == "antonelli":
                raw_aliases.add("Andrea Kimi Antonelli")
            for alias in raw_aliases:
                key = _compact(alias)
                if key:
                    aliases[key] = driver.driver_id
        return aliases

    @staticmethod
    def _team_aliases(teams: Iterable[Team]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        manual = {
            "red_bull": ("red bull", "red bull racing", "oracle red bull racing"),
            "racing_bulls": ("racing bulls", "visa cash app racing bulls"),
            "aston_martin": ("aston martin", "aston martin aramco"),
            "mclaren": ("mclaren", "mclaren f1 team"),
            "mercedes": ("mercedes", "mercedes-amg", "mercedes amg"),
            "audi": ("audi", "stake f1", "kick sauber", "sauber"),
        }
        for team in teams:
            raw_aliases = {
                team.team_id,
                team.team_id.replace("_", " "),
                team.name,
            }
            raw_aliases.update(manual.get(team.team_id, ()))
            for alias in raw_aliases:
                key = _compact(alias)
                if key and len(key) >= 3:
                    aliases[key] = team.team_id
        return aliases

    @staticmethod
    def _outcome_prices(market: dict[str, Any]) -> list[tuple[str, float]] | None:
        outcomes = _parse_array(market.get("outcomes"))
        prices = _parse_array(market.get("outcomePrices"))
        if not outcomes or not prices or len(outcomes) != len(prices):
            return None
        parsed: list[tuple[str, float]] = []
        for outcome, price in zip(outcomes, prices):
            numeric = _as_float(price)
            if numeric is None or numeric < 0.0 or numeric > 1.0:
                return None
            parsed.append((str(outcome), numeric))
        return parsed

    @staticmethod
    def _outcome_tokens(market: dict[str, Any]) -> list[str]:
        tokens = _parse_array(market.get("clobTokenIds"))
        if tokens:
            return [str(token) for token in tokens]
        token_rows = market.get("tokens")
        if isinstance(token_rows, list):
            parsed = []
            for row in token_rows:
                if not isinstance(row, dict):
                    return []
                token = row.get("token_id") or row.get("tokenId") or row.get("id")
                if token is None:
                    return []
                parsed.append(str(token))
            return parsed
        return []

    @staticmethod
    def _market_text(market: dict[str, Any], context: tuple[dict[str, Any], ...]) -> str:
        fields: list[str] = []
        for item in (*context, market):
            for key in ("title", "question", "slug", "description", "groupItemTitle"):
                value = item.get(key)
                if value:
                    fields.append(str(value))
        return " ".join(fields)

    @staticmethod
    def _is_closed(market: dict[str, Any]) -> bool:
        active = market.get("active")
        closed = market.get("closed")
        accepting_orders = market.get("acceptingOrders")
        if closed is True:
            return True
        if active is False:
            return True
        if accepting_orders is False and market.get("umaResolutionStatus"):
            return True
        return False

    @staticmethod
    def _liquidity(market: dict[str, Any]) -> float:
        for field in ("liquidityNum", "liquidity", "liquidityClob"):
            value = _as_float(market.get(field))
            if value is not None:
                return max(0.0, value)
        return 0.0

    @staticmethod
    def _spread(market: dict[str, Any]) -> float:
        explicit = _as_float(market.get("spread"))
        if explicit is not None:
            return max(0.0, explicit)
        bid = _as_float(market.get("bestBid"))
        ask = _as_float(market.get("bestAsk"))
        if bid is not None and ask is not None and ask >= bid:
            return ask - bid
        return 0.0

    @staticmethod
    def _snapshot_market_id(market: dict[str, Any], event_id: str) -> str:
        raw_id = str(
            market.get("id")
            or market.get("conditionId")
            or market.get("questionID")
            or market.get("slug")
            or market.get("question")
            or "unknown"
        )
        return safe_name(f"polymarket_{event_id}_{raw_id}")

    def _definition(
        self,
        market: dict[str, Any],
        event_id: str,
        market_type: str,
        driver_id: str,
        token_id: str,
        question: str,
    ) -> PolymarketDriverMarketDefinition:
        raw_id = market.get("id") or market.get("conditionId") or market.get("questionID")
        return PolymarketDriverMarketDefinition(
            market_id=self._snapshot_market_id(market, event_id),
            event_id=event_id,
            market_type=market_type,
            outcome_id=driver_id,
            token_id=str(token_id),
            source_market_id=str(raw_id) if raw_id else None,
            question=question[:240],
            liquidity=self._liquidity(market),
            spread_estimate=self._spread(market),
        )

    @staticmethod
    def _issue(
        code: str,
        severity: str,
        market: dict[str, Any],
        question: str,
        detail: str,
    ) -> PolymarketNormalizationIssue:
        raw_id = market.get("id") or market.get("conditionId") or market.get("questionID")
        return PolymarketNormalizationIssue(
            code=code,
            severity=severity,
            market_id=str(raw_id) if raw_id else None,
            question=question[:240],
            detail=detail,
        )


class PolymarketSeasonSearchAuditor:
    """Searches Polymarket Gamma markets by event name, then normalizes hits."""

    def __init__(
        self,
        season: SeasonState,
        client: PolymarketMarketClient | None = None,
    ) -> None:
        self.season = season
        self.client = client or PolymarketMarketClient()

    def build(
        self,
        limit: int = 20,
        market_type: str = "winner",
        include_closed: bool = False,
        event_ids: Iterable[str] | None = None,
    ) -> PolymarketSeasonSearchReport:
        selected = set(event_ids or [])
        normalizer = PolymarketGammaNormalizer(self.season)
        rows: list[PolymarketSeasonSearchRow] = []

        for event in self.season.events:
            if selected and event.event_id not in selected:
                continue
            query_results: list[PolymarketSearchQueryResult] = []
            payloads: list[Any] = []
            for query in self._event_queries(event, market_type):
                try:
                    payload = self.client.search_markets(query, limit=limit, include_closed=include_closed)
                except Exception as exc:  # noqa: BLE001 - surface per-query failures.
                    query_results.append(PolymarketSearchQueryResult(query=query, result_count=0, error=str(exc)))
                    continue
                count = _payload_market_count(payload)
                query_results.append(PolymarketSearchQueryResult(query=query, result_count=count))
                payloads.append(payload)

            markets = _dedupe_market_payloads(payloads)
            result = normalizer.normalize_payload(
                markets,
                event_id=event.event_id,
                market_type=market_type,
                include_closed=include_closed,
            )
            issues = list(result.issues)
            if markets and not result.snapshots and not result.definitions and not issues:
                issues.append(
                    PolymarketNormalizationIssue(
                        code="no_matching_event_alias",
                        severity="info",
                        market_id=None,
                        question=event.name,
                        detail=(
                            f"Search returned {len(markets)} unique market candidates, but none matched "
                            "the configured event aliases for this race."
                        ),
                    )
                )
            rows.append(
                PolymarketSeasonSearchRow(
                    event_id=event.event_id,
                    event_name=event.name,
                    round_number=event.round_number,
                    date=event.date,
                    completed=event.completed,
                    queries=tuple(query_results),
                    unique_market_count=len(markets),
                    snapshot_count=len(result.snapshots),
                    definition_count=len(result.definitions),
                    issue_counts=_issue_counts(issues),
                    definitions=result.definitions,
                    issues=tuple(issues),
                )
            )

        all_issues = [issue for row in rows for issue in row.issues]
        all_queries = [query for row in rows for query in row.queries]
        return PolymarketSeasonSearchReport(
            season=self.season.season,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            market_type=market_type,
            include_closed=include_closed,
            limit=limit,
            event_count=len(rows),
            query_count=len(all_queries),
            total_search_results=sum(query.result_count for query in all_queries),
            total_unique_markets=sum(row.unique_market_count for row in rows),
            events_with_snapshots=sum(1 for row in rows if row.snapshot_count > 0),
            events_with_definitions=sum(1 for row in rows if row.definition_count > 0),
            total_snapshots=sum(row.snapshot_count for row in rows),
            total_definitions=sum(row.definition_count for row in rows),
            issue_counts=_issue_counts(all_issues),
            rows=tuple(rows),
        )

    def _event_queries(self, event: RaceEvent, market_type: str = "winner") -> tuple[str, ...]:
        base = event.name
        short = event.name.replace("Grand Prix", "GP")
        words = event.event_id.replace("_gp", "").replace("_", " ")
        if market_type == CONSTRUCTOR_DOUBLE_PODIUM:
            raw = [
                f"{self.season.season} {base} double podium",
                f"{base} double podium",
                f"{short} double podium",
                f"F1 {base} double podium",
                f"constructor to double podium {base}",
                f"{words} grand prix double podium",
            ]
        elif market_type == DRIVER_H2H:
            raw = [
                f"{self.season.season} {base} head to head",
                f"{base} head to head",
                f"{short} h2h",
                f"F1 {base} head to head matchups",
                f"F1 {base} finish ahead",
                f"{words} grand prix h2h",
            ]
        else:
            raw = [
                f"{self.season.season} {base} winner",
                f"{base} winner",
                f"{short} winner",
                f"F1 {base}",
                f"{words} grand prix winner",
            ]
        raw.extend(MANUAL_EVENT_ALIASES.get(event.event_id, ()))
        deduped = tuple(dict.fromkeys(query for query in raw if query))
        return deduped


class PolymarketLiveSnapshotter:
    """Captures same-time Polymarket snapshots for future cutoffs.

    Gamma search is used to discover candidate F1 markets and CLOB order books
    are used for the point-in-time price whenever token definitions are present.
    If a book cannot be read, the snapshot falls back to the Gamma outcome price
    and records an explicit issue so replay can distinguish real book-backed
    quotes from lower-confidence fallback rows.
    """

    def __init__(
        self,
        season: SeasonState,
        client: PolymarketMarketClient | None = None,
    ) -> None:
        self.season = season
        self.client = client or PolymarketMarketClient()

    def capture_event(
        self,
        event_id: str,
        limit: int = 20,
        market_type: str = "winner",
        include_closed: bool = False,
        event_aliases: Iterable[str] = (),
        captured_at: str | None = None,
        wide_spread_threshold: float = 0.10,
    ) -> PolymarketLiveSnapshotResult:
        event = next((row for row in self.season.events if row.event_id == event_id), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")
        observed_at = captured_at or utc_now().replace(microsecond=0).isoformat()
        aliases = tuple(event_aliases)

        searcher = PolymarketSeasonSearchAuditor(self.season, client=self.client)
        query_results: list[PolymarketSearchQueryResult] = []
        payloads: list[Any] = []
        queries = tuple(dict.fromkeys((*searcher._event_queries(event, market_type), *aliases)))  # noqa: SLF001
        for query in queries:
            try:
                payload = self.client.search_markets(query, limit=limit, include_closed=include_closed)
            except Exception as exc:  # noqa: BLE001 - surface per-query failures.
                query_results.append(PolymarketSearchQueryResult(query=query, result_count=0, error=str(exc)))
                continue
            query_results.append(PolymarketSearchQueryResult(query=query, result_count=_payload_market_count(payload)))
            payloads.append(payload)

        markets = _dedupe_market_payloads(payloads)
        normalized = PolymarketGammaNormalizer(self.season).normalize_payload(
            markets,
            event_id=event_id,
            captured_at=observed_at,
            market_type=market_type,
            event_aliases=aliases,
            include_closed=include_closed,
        )

        issues = list(normalized.issues)
        if markets and not normalized.snapshots and not normalized.definitions and not issues:
            issues.append(
                PolymarketNormalizationIssue(
                    code="no_matching_event_alias",
                    severity="info",
                    market_id=None,
                    question=event.name,
                    detail=(
                        f"Search returned {len(markets)} unique market candidates, but none matched "
                        "the configured event aliases for this race."
                    ),
                )
            )

        groups = _snapshot_groups(normalized.snapshots, observed_at)
        gamma_prices = {
            (snapshot.market_id, outcome_id): price
            for snapshot in normalized.snapshots
            for outcome_id, price in snapshot.prices.items()
        }
        quotes: list[PolymarketOrderBookQuote] = []
        for definition in normalized.definitions:
            gamma_price = gamma_prices.get((definition.market_id, definition.outcome_id))
            try:
                book = self.client.order_book(definition.token_id)
                quote = self._quote_from_book(definition, book, gamma_price, wide_spread_threshold)
            except Exception as exc:  # noqa: BLE001 - keep capture usable with fallback prices.
                issues.append(
                    PolymarketNormalizationIssue(
                        code="order_book_fetch_failed",
                        severity="warning",
                        market_id=definition.source_market_id,
                        question=definition.question,
                        detail=str(exc),
                    )
                )
                quote = self._fallback_quote(definition, gamma_price, status="gamma_price_fallback", error=str(exc))
            quotes.append(quote)
            if quote.displayed_price is not None:
                group = groups.setdefault(
                    definition.market_id,
                    {
                        "event_id": definition.event_id,
                        "market_type": definition.market_type,
                        "prices": {},
                        "liquidity": definition.liquidity,
                        "spread_estimate": definition.spread_estimate,
                    },
                )
                group["prices"][definition.outcome_id] = quote.displayed_price
                group["liquidity"] = max(float(group["liquidity"]), definition.liquidity)
                if quote.spread is not None:
                    group["spread_estimate"] = max(float(group["spread_estimate"]), quote.spread)

        if normalized.snapshots and not normalized.definitions:
            issues.append(
                PolymarketNormalizationIssue(
                    code="gamma_only_snapshot",
                    severity="warning",
                    market_id=None,
                    question=event.name,
                    detail=(
                        "A Gamma outcome-price snapshot was normalized, but no CLOB token definitions were "
                        "available, so live order-book verification could not run."
                    ),
                )
            )

        snapshots = tuple(
            MarketSnapshot(
                market_id=market_id,
                event_id=str(group["event_id"]),
                market_type=str(group["market_type"]),
                captured_at=observed_at,
                prices={key: round(float(value), 4) for key, value in dict(group["prices"]).items()},
                liquidity=round(float(group["liquidity"]), 4),
                spread_estimate=round(float(group["spread_estimate"]), 4),
            )
            for market_id, group in sorted(groups.items())
            if group["prices"]
        )
        return PolymarketLiveSnapshotResult(
            event_id=event_id,
            captured_at=observed_at,
            market_type=market_type,
            snapshots=snapshots,
            definitions=normalized.definitions,
            quotes=tuple(quotes),
            issues=tuple(issues),
            queries=tuple(query_results),
            unique_market_count=len(markets),
        )

    def _quote_from_book(
        self,
        definition: PolymarketDriverMarketDefinition,
        book: Any,
        gamma_price: float | None,
        wide_spread_threshold: float,
    ) -> PolymarketOrderBookQuote:
        if not isinstance(book, dict):
            return self._fallback_quote(definition, gamma_price, status="gamma_price_fallback", error="Malformed order book payload")

        best_bid = _best_order_price(book.get("bids"), side="bid")
        best_ask = _best_order_price(book.get("asks"), side="ask")
        last_trade_price = _first_float(book, ("last_trade_price", "lastTradePrice", "lastPrice"))
        midpoint: float | None = None
        spread: float | None = None
        displayed_price: float | None = None
        status = "missing_book_price"
        if best_bid is not None and best_ask is not None and best_ask >= best_bid:
            midpoint = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            if spread <= wide_spread_threshold:
                displayed_price = midpoint
                status = "book_midpoint"
            elif last_trade_price is not None:
                displayed_price = last_trade_price
                status = "book_last_trade_wide_spread"
            else:
                displayed_price = midpoint
                status = "book_midpoint_wide_no_last"
        elif last_trade_price is not None:
            displayed_price = last_trade_price
            status = "book_last_trade_no_quote"
        elif gamma_price is not None:
            displayed_price = gamma_price
            status = "gamma_price_fallback"

        return PolymarketOrderBookQuote(
            market_id=definition.market_id,
            outcome_id=definition.outcome_id,
            token_id=definition.token_id,
            status=status,
            displayed_price=round(displayed_price, 4) if displayed_price is not None else None,
            best_bid=round(best_bid, 4) if best_bid is not None else None,
            best_ask=round(best_ask, 4) if best_ask is not None else None,
            midpoint=round(midpoint, 4) if midpoint is not None else None,
            last_trade_price=round(last_trade_price, 4) if last_trade_price is not None else None,
            spread=round(spread, 4) if spread is not None else None,
            bid_depth=round(_order_depth(book.get("bids")), 4),
            ask_depth=round(_order_depth(book.get("asks")), 4),
            book_timestamp=_book_timestamp(book),
            book_hash=str(book.get("hash") or "") or None,
        )

    @staticmethod
    def _fallback_quote(
        definition: PolymarketDriverMarketDefinition,
        gamma_price: float | None,
        status: str,
        error: str | None = None,
    ) -> PolymarketOrderBookQuote:
        return PolymarketOrderBookQuote(
            market_id=definition.market_id,
            outcome_id=definition.outcome_id,
            token_id=definition.token_id,
            status=status,
            displayed_price=round(gamma_price, 4) if gamma_price is not None else None,
            best_bid=None,
            best_ask=None,
            midpoint=None,
            last_trade_price=None,
            spread=None,
            bid_depth=0.0,
            ask_depth=0.0,
            book_timestamp=None,
            book_hash=None,
            error=error,
        )


class PolymarketDiscoveryAuditor:
    """Scans one Polymarket payload against all season events."""

    def __init__(self, season: SeasonState) -> None:
        self.season = season

    def build(
        self,
        payload: Any,
        market_type: str = "winner",
        include_closed: bool = False,
        event_ids: Iterable[str] | None = None,
    ) -> PolymarketDiscoveryReport:
        selected = set(event_ids or [])
        normalizer = PolymarketGammaNormalizer(self.season)
        rows: list[PolymarketDiscoveryRow] = []
        for event in self.season.events:
            if selected and event.event_id not in selected:
                continue
            result = normalizer.normalize_payload(
                payload,
                event_id=event.event_id,
                market_type=market_type,
                include_closed=include_closed,
            )
            rows.append(
                PolymarketDiscoveryRow(
                    event_id=event.event_id,
                    event_name=event.name,
                    round_number=event.round_number,
                    date=event.date,
                    completed=event.completed,
                    snapshot_count=len(result.snapshots),
                    definition_count=len(result.definitions),
                    issue_counts=_issue_counts(result.issues),
                    definitions=result.definitions,
                    issues=result.issues,
                )
            )

        all_issues = [issue for row in rows for issue in row.issues]
        return PolymarketDiscoveryReport(
            season=self.season.season,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            market_type=market_type,
            include_closed=include_closed,
            input_market_count=sum(1 for _ in PolymarketGammaNormalizer._iter_markets(payload)),
            event_count=len(rows),
            events_with_snapshots=sum(1 for row in rows if row.snapshot_count > 0),
            events_with_definitions=sum(1 for row in rows if row.definition_count > 0),
            total_snapshots=sum(row.snapshot_count for row in rows),
            total_definitions=sum(row.definition_count for row in rows),
            issue_counts=_issue_counts(all_issues),
            rows=tuple(rows),
        )


class PolymarketPriceHistoryBackfiller:
    """Backfills cutoff market snapshots from reviewed Polymarket definitions."""

    def __init__(
        self,
        season: SeasonState,
        client: PolymarketMarketClient | None = None,
    ) -> None:
        self.season = season
        self.client = client or PolymarketMarketClient()

    def backfill_payload(
        self,
        payload: Any,
        event_id: str,
        knowledge_cutoff: str,
        lookback_hours: int = 168,
        market_type: str = "winner",
        event_aliases: Iterable[str] = (),
        include_closed: bool = False,
        fidelity_minutes: int = 1,
    ) -> PolymarketHistoryBackfillResult:
        cutoff = _utc_dt(knowledge_cutoff)
        if cutoff is None:
            raise ValueError(f"Invalid knowledge_cutoff datetime: {knowledge_cutoff}")
        start = cutoff - timedelta(hours=lookback_hours)
        normalized = PolymarketGammaNormalizer(self.season).normalize_payload(
            payload,
            event_id=event_id,
            captured_at=knowledge_cutoff,
            market_type=market_type,
            event_aliases=event_aliases,
            include_closed=include_closed,
        )

        issues = list(normalized.issues)
        snapshots: list[MarketSnapshot] = []
        for definition in normalized.definitions:
            try:
                history = self.client.price_history(
                    definition.token_id,
                    start_ts=int(start.timestamp()),
                    end_ts=int(cutoff.timestamp()),
                    fidelity=fidelity_minutes,
                )
            except Exception as exc:  # noqa: BLE001 - surface per-market fetch failure.
                issues.append(
                    PolymarketNormalizationIssue(
                        code="price_history_fetch_failed",
                        severity="warning",
                        market_id=definition.source_market_id,
                        question=definition.question,
                        detail=str(exc),
                    )
                )
                continue
            point = self._latest_history_point(history, cutoff)
            if point is None:
                issues.append(
                    PolymarketNormalizationIssue(
                        code="price_history_empty",
                        severity="warning",
                        market_id=definition.source_market_id,
                        question=definition.question,
                        detail="No price-history point was available at or before the cutoff within the lookback window.",
                    )
                )
                continue
            timestamp, price = point
            snapshots.append(
                MarketSnapshot(
                    market_id=definition.market_id,
                    event_id=definition.event_id,
                    market_type=definition.market_type,
                    captured_at=timestamp.isoformat(),
                    prices={definition.outcome_id: price},
                    liquidity=definition.liquidity,
                    spread_estimate=definition.spread_estimate,
                )
            )

        return PolymarketHistoryBackfillResult(
            event_id=event_id,
            knowledge_cutoff=knowledge_cutoff,
            snapshots=tuple(snapshots),
            definitions=normalized.definitions,
            issues=tuple(issues),
        )

    @staticmethod
    def _latest_history_point(payload: Any, cutoff: datetime) -> tuple[datetime, float] | None:
        points: list[tuple[datetime, float]] = []
        for row in _history_rows(payload):
            timestamp = _history_timestamp(row)
            raw_price = row["p"] if "p" in row else row.get("price")
            price = _as_float(raw_price)
            if timestamp is None or price is None or not (0.0 <= price <= 1.0):
                continue
            if timestamp <= cutoff:
                points.append((timestamp, price))
        if not points:
            return None
        points.sort(key=lambda item: item[0])
        return points[-1]


class PolymarketSearchHistoryBackfiller:
    """Searches Gamma candidates, then backfills cutoff prices from CLOB history."""

    def __init__(
        self,
        season: SeasonState,
        client: PolymarketMarketClient | None = None,
    ) -> None:
        self.season = season
        self.client = client or PolymarketMarketClient()

    def backfill_event(
        self,
        event_id: str,
        knowledge_cutoff: str,
        limit: int = 20,
        lookback_hours: int = 168,
        market_type: str = "winner",
        event_aliases: Iterable[str] = (),
        include_closed: bool = False,
        fidelity_minutes: int = 1,
    ) -> PolymarketSearchHistoryBackfillResult:
        event = next((row for row in self.season.events if row.event_id == event_id), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")

        searcher = PolymarketSeasonSearchAuditor(self.season, client=self.client)
        queries = tuple(dict.fromkeys((*searcher._event_queries(event, market_type), *event_aliases)))  # noqa: SLF001
        query_results: list[PolymarketSearchQueryResult] = []
        payloads: list[Any] = []
        for query in queries:
            try:
                payload = self.client.search_markets(query, limit=limit, include_closed=include_closed)
            except Exception as exc:  # noqa: BLE001 - keep other query attempts usable.
                query_results.append(PolymarketSearchQueryResult(query=query, result_count=0, error=str(exc)))
                continue
            query_results.append(PolymarketSearchQueryResult(query=query, result_count=_payload_market_count(payload)))
            payloads.append(payload)

        markets = tuple(_dedupe_market_payloads(payloads))
        backfill = PolymarketPriceHistoryBackfiller(self.season, client=self.client).backfill_payload(
            list(markets),
            event_id=event_id,
            knowledge_cutoff=knowledge_cutoff,
            lookback_hours=lookback_hours,
            market_type=market_type,
            event_aliases=event_aliases,
            include_closed=include_closed,
            fidelity_minutes=fidelity_minutes,
        )
        issues = list(backfill.issues)
        if not markets:
            issues.append(
                PolymarketNormalizationIssue(
                    code="no_search_results",
                    severity="info",
                    market_id=None,
                    question=event.name,
                    detail="No Polymarket Gamma candidates were returned for the generated event queries.",
                )
            )
        elif not backfill.snapshots and not backfill.definitions and not issues:
            issues.append(
                PolymarketNormalizationIssue(
                    code="no_matching_event_alias",
                    severity="info",
                    market_id=None,
                    question=event.name,
                    detail=(
                        f"Search returned {len(markets)} unique market candidates, but none matched "
                        "the configured event aliases and market type."
                    ),
                )
            )

        return PolymarketSearchHistoryBackfillResult(
            event_id=event_id,
            knowledge_cutoff=knowledge_cutoff,
            market_type=market_type,
            include_closed=include_closed,
            limit=limit,
            lookback_hours=lookback_hours,
            fidelity_minutes=fidelity_minutes,
            queries=tuple(query_results),
            unique_market_count=len(markets),
            search_payload=markets,
            snapshots=backfill.snapshots,
            definitions=backfill.definitions,
            issues=tuple(issues),
        )


def _parse_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(row: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        if key in row:
            value = _as_float(row.get(key))
            if value is not None:
                return value
    return None


def _compact(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _issue_counts(issues: Iterable[PolymarketNormalizationIssue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.code] = counts.get(issue.code, 0) + 1
    return dict(sorted(counts.items()))


def _utc_dt(value: str | None) -> datetime | None:
    parsed = parse_dt(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _history_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("history")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _history_timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("t") or row.get("timestamp") or row.get("time")
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    parsed = parse_dt(str(value))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload_market_count(payload: Any) -> int:
    if isinstance(payload, list):
        market_count = sum(1 for _ in PolymarketGammaNormalizer._iter_markets(payload))
        return market_count if market_count else len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("markets"), list):
        return len(payload["markets"])
    return sum(1 for _ in PolymarketGammaNormalizer._iter_markets(payload))


def _dedupe_snapshots(snapshots: Iterable[MarketSnapshot]) -> list[MarketSnapshot]:
    by_key: dict[tuple[str, str, tuple[tuple[str, float], ...]], MarketSnapshot] = {}
    for snapshot in snapshots:
        price_key = tuple(sorted((outcome_id, round(float(price), 8)) for outcome_id, price in snapshot.prices.items()))
        by_key[(snapshot.market_id, snapshot.market_type, price_key)] = snapshot
    return list(by_key.values())


def _dedupe_definitions(
    definitions: Iterable[PolymarketDriverMarketDefinition],
) -> list[PolymarketDriverMarketDefinition]:
    by_key: dict[tuple[str, str, str, str], PolymarketDriverMarketDefinition] = {}
    for definition in definitions:
        by_key[
            (
                definition.market_id,
                definition.market_type,
                definition.outcome_id,
                definition.token_id,
            )
        ] = definition
    return list(by_key.values())


def _dedupe_issues(issues: Iterable[PolymarketNormalizationIssue]) -> list[PolymarketNormalizationIssue]:
    by_key: dict[tuple[str, str | None, str], PolymarketNormalizationIssue] = {}
    for issue in issues:
        by_key[(issue.code, issue.market_id, issue.question)] = issue
    return list(by_key.values())


def _dedupe_market_payloads(payloads: Iterable[Any]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for market, context in PolymarketGammaNormalizer._iter_markets(payload):
            key = str(
                market.get("id")
                or market.get("conditionId")
                or market.get("questionID")
                or market.get("slug")
                or market.get("question")
                or len(by_key)
            )
            preserved = dict(market)
            context_text = _context_text(context)
            if context_text:
                market_title = preserved.get("title")
                preserved["title"] = f"{context_text} {market_title or ''}".strip()
            by_key[key] = preserved
    return list(by_key.values())


def _context_text(context: tuple[dict[str, Any], ...]) -> str:
    fields: list[str] = []
    for item in context:
        for key in ("title", "question", "slug", "description", "groupItemTitle"):
            value = item.get(key)
            if value:
                fields.append(str(value))
    return " ".join(fields)


def _snapshot_groups(
    snapshots: Iterable[MarketSnapshot],
    captured_at: str,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        groups[snapshot.market_id] = {
            "event_id": snapshot.event_id,
            "market_type": snapshot.market_type,
            "captured_at": captured_at,
            "prices": dict(snapshot.prices),
            "liquidity": snapshot.liquidity,
            "spread_estimate": snapshot.spread_estimate,
        }
    return groups


def _best_order_price(rows: Any, side: str) -> float | None:
    prices = []
    for row in _order_rows(rows):
        price = _as_float(row.get("price") or row.get("p"))
        size = _as_float(row.get("size") or row.get("s"))
        if price is None or size is None or size <= 0.0 or not (0.0 <= price <= 1.0):
            continue
        prices.append(price)
    if not prices:
        return None
    return max(prices) if side == "bid" else min(prices)


def _order_depth(rows: Any) -> float:
    total = 0.0
    for row in _order_rows(rows):
        size = _as_float(row.get("size") or row.get("s"))
        if size is not None and size > 0.0:
            total += size
    return total


def _order_rows(rows: Any) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _book_timestamp(book: dict[str, Any]) -> str | None:
    value = None
    for key in ("timestamp", "ts", "updated_at", "updatedAt"):
        if key in book:
            value = book.get(key)
            break
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()
    parsed = parse_dt(str(value))
    if parsed is None:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
