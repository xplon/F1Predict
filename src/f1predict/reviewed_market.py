"""Reviewed market snapshot packets for Codex-normalized market inputs."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import MarketSnapshot, SeasonState, parse_dt, utc_now
from f1predict.market import after_cutoff_market_count, event_market_snapshots
from f1predict.market_outcomes import DRIVER_H2H, driver_h2h_outcome_id
from f1predict.market_store import MarketSnapshotStore


ACCEPTED_REVIEW_STATUSES = {"accepted", "verified", "supports_market", "supports_claim"}


class ReviewedMarketSnapshotValidationError(ValueError):
    """Raised when a reviewed market packet fails audit checks."""


@dataclass(frozen=True)
class ReviewedMarketSnapshotResult:
    event_id: str
    market_id: str
    market_type: str
    archived_path: str | None
    snapshot_count: int
    cutoff_valid_snapshot_count: int
    after_cutoff_snapshot_count: int
    warnings: tuple[str, ...]
    review: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "market_id": self.market_id,
            "market_type": self.market_type,
            "archived_path": self.archived_path,
            "snapshot_count": self.snapshot_count,
            "cutoff_valid_snapshot_count": self.cutoff_valid_snapshot_count,
            "after_cutoff_snapshot_count": self.after_cutoff_snapshot_count,
            "warnings": list(self.warnings),
            "review": self.review,
        }


class ReviewedMarketSnapshotArchiver:
    """Validates and archives Codex-reviewed market snapshots.

    This is the audited manual/LLM-normalized ingress path. It is intentionally
    stricter than the generic MarketSnapshotStore so reviewed market data cannot
    bypass source, reviewer, cutoff, and outcome-mapping checks.
    """

    def __init__(
        self,
        season: SeasonState,
        store: MarketSnapshotStore | None = None,
    ) -> None:
        self.season = season
        self.store = store or MarketSnapshotStore()

    def archive_packet(
        self,
        event_id: str,
        input_path: Path | str,
        knowledge_cutoff: str | None = None,
        require_cutoff_valid: bool = False,
        write: bool = True,
    ) -> ReviewedMarketSnapshotResult:
        packet_path = Path(input_path)
        packet = self._read_packet(packet_path)
        snapshot = self._snapshot(event_id, packet)
        review = self._review(packet)
        warnings = list(self._validate_review(review, knowledge_cutoff))
        warnings.extend(self._validate_outcomes(snapshot, review))
        warnings.extend(self._validate_cutoff(snapshot, knowledge_cutoff, require_cutoff_valid))

        archived_path = None
        if write:
            archived = self.store.write_event_snapshots(
                event_id,
                [snapshot],
                params={
                    "source": "reviewed_market_snapshot",
                    "input": str(packet_path),
                    "knowledge_cutoff": knowledge_cutoff,
                    "require_cutoff_valid": require_cutoff_valid,
                    "review": review,
                    "warnings": warnings,
                },
            )
            archived_path = str(archived)

        cutoff_dt = parse_dt(knowledge_cutoff)
        return ReviewedMarketSnapshotResult(
            event_id=event_id,
            market_id=snapshot.market_id,
            market_type=snapshot.market_type,
            archived_path=archived_path,
            snapshot_count=1,
            cutoff_valid_snapshot_count=len(
                event_market_snapshots([snapshot], event_id, cutoff_dt, market_type=snapshot.market_type)
            ),
            after_cutoff_snapshot_count=after_cutoff_market_count(
                [snapshot],
                event_id,
                cutoff_dt,
                market_type=snapshot.market_type,
            ),
            warnings=tuple(warnings),
            review=review,
        )

    @staticmethod
    def _read_packet(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ReviewedMarketSnapshotValidationError(f"{path}: file does not exist")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - keep path context.
            raise ReviewedMarketSnapshotValidationError(f"{path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ReviewedMarketSnapshotValidationError(f"{path}: expected a JSON object")
        return payload

    @staticmethod
    def _snapshot(event_id: str, packet: dict[str, Any]) -> MarketSnapshot:
        if packet.get("event_id") != event_id:
            raise ReviewedMarketSnapshotValidationError(
                f"packet event_id={packet.get('event_id')!r} does not match requested event_id={event_id!r}"
            )
        required = ("market_id", "market_type", "captured_at", "prices")
        missing = [name for name in required if not packet.get(name)]
        if missing:
            raise ReviewedMarketSnapshotValidationError(f"reviewed market packet missing fields: {', '.join(missing)}")
        if parse_dt(str(packet["captured_at"])) is None:
            raise ReviewedMarketSnapshotValidationError("captured_at must be an ISO datetime")
        prices = packet.get("prices")
        if not isinstance(prices, dict) or not prices:
            raise ReviewedMarketSnapshotValidationError("prices must be a non-empty object keyed by model outcome id")
        normalized_prices: dict[str, float] = {}
        for outcome_id, raw_price in prices.items():
            price = float(raw_price)
            if not outcome_id:
                raise ReviewedMarketSnapshotValidationError("price outcome id is required")
            if not math.isfinite(price) or price < 0.0 or price > 1.0:
                raise ReviewedMarketSnapshotValidationError(f"price for {outcome_id} must be finite and in 0..1")
            normalized_prices[str(outcome_id)] = price
        liquidity = float(packet.get("liquidity") or 0.0)
        spread = float(packet.get("spread_estimate") or 0.0)
        if liquidity < 0.0:
            raise ReviewedMarketSnapshotValidationError("liquidity must be non-negative")
        if spread < 0.0:
            raise ReviewedMarketSnapshotValidationError("spread_estimate must be non-negative")
        return MarketSnapshot(
            market_id=str(packet["market_id"]),
            event_id=event_id,
            market_type=str(packet["market_type"]),
            captured_at=str(packet["captured_at"]),
            prices=normalized_prices,
            liquidity=liquidity,
            spread_estimate=spread,
        )

    @staticmethod
    def _review(packet: dict[str, Any]) -> dict[str, Any]:
        review = packet.get("review")
        if not isinstance(review, dict):
            raise ReviewedMarketSnapshotValidationError("review object is required")
        status = str(review.get("status") or review.get("review_status") or "")
        normalized = dict(review)
        normalized["status"] = status
        required = ("status", "reviewed_by", "reviewed_at", "source_url", "source_captured_at", "notes")
        missing = [name for name in required if not normalized.get(name)]
        if missing:
            raise ReviewedMarketSnapshotValidationError(f"review missing fields: {', '.join(missing)}")
        if status not in ACCEPTED_REVIEW_STATUSES:
            raise ReviewedMarketSnapshotValidationError(
                f"review status must be one of {sorted(ACCEPTED_REVIEW_STATUSES)}"
            )
        if parse_dt(str(normalized["reviewed_at"])) is None:
            raise ReviewedMarketSnapshotValidationError("review.reviewed_at must be an ISO datetime")
        if parse_dt(str(normalized["source_captured_at"])) is None:
            raise ReviewedMarketSnapshotValidationError("review.source_captured_at must be an ISO datetime")
        return normalized

    def _validate_review(self, review: dict[str, Any], knowledge_cutoff: str | None) -> tuple[str, ...]:
        warnings: list[str] = []
        source_captured = parse_dt(str(review["source_captured_at"]))
        cutoff = parse_dt(knowledge_cutoff)
        if cutoff is not None and source_captured is not None and source_captured > cutoff:
            archive = review.get("historical_archive")
            if not isinstance(archive, dict) or not archive.get("archive_url"):
                warnings.append("source_review_captured_after_cutoff_without_archive_url")
        if not str(review.get("notes") or "").strip():
            raise ReviewedMarketSnapshotValidationError("review.notes must describe why the market definition is accepted")
        return tuple(warnings)

    def _validate_outcomes(self, snapshot: MarketSnapshot, review: dict[str, Any]) -> tuple[str, ...]:
        allowed = self._allowed_outcomes(snapshot.market_type)
        unknown = sorted(outcome for outcome in snapshot.prices if outcome not in allowed)
        if unknown:
            raise ReviewedMarketSnapshotValidationError(
                f"{snapshot.market_type} market contains unknown model outcome ids: {', '.join(unknown)}"
            )
        mapping = review.get("outcome_mapping")
        if not isinstance(mapping, dict):
            raise ReviewedMarketSnapshotValidationError("review.outcome_mapping must map market outcomes to model ids")
        missing_mapping = sorted(outcome for outcome in snapshot.prices if outcome not in mapping)
        if missing_mapping:
            raise ReviewedMarketSnapshotValidationError(
                f"review.outcome_mapping missing model outcome ids: {', '.join(missing_mapping)}"
            )
        total = sum(float(value) for value in snapshot.prices.values())
        if snapshot.market_type == "winner" and len(snapshot.prices) >= 2 and (total < 0.45 or total > 1.8):
            return ("winner_market_price_sum_outside_expected_range",)
        return ()

    def _allowed_outcomes(self, market_type: str) -> set[str]:
        if market_type == "winner":
            return set(self.season.drivers)
        if market_type == DRIVER_H2H:
            return {
                driver_h2h_outcome_id(driver_id, opponent_id)
                for driver_id in self.season.drivers
                for opponent_id in self.season.drivers
                if driver_id != opponent_id
            }
        if market_type.startswith("constructor_"):
            return set(self.season.teams)
        return set(self.season.drivers) | set(self.season.teams)

    @staticmethod
    def _validate_cutoff(
        snapshot: MarketSnapshot,
        knowledge_cutoff: str | None,
        require_cutoff_valid: bool,
    ) -> tuple[str, ...]:
        cutoff = parse_dt(knowledge_cutoff)
        if cutoff is None:
            return ()
        if snapshot.is_available(cutoff):
            return ()
        if require_cutoff_valid:
            raise ReviewedMarketSnapshotValidationError(
                f"snapshot captured_at={snapshot.captured_at} is after knowledge_cutoff={knowledge_cutoff}"
            )
        return ("snapshot_after_knowledge_cutoff",)


def reviewed_market_template(event_id: str, market_type: str = "winner") -> dict[str, Any]:
    price_key = "driver_or_team_id"
    if market_type == DRIVER_H2H:
        price_key = "driver_id_ahead_of_opponent_id"
    return {
        "event_id": event_id,
        "market_id": f"reviewed_{event_id}_{market_type}",
        "market_type": market_type,
        "captured_at": "YYYY-MM-DDTHH:MM:SS+00:00",
        "prices": {price_key: 0.0},
        "liquidity": 0.0,
        "spread_estimate": 0.0,
        "review": {
            "status": "accepted",
            "reviewed_by": "codex",
            "reviewed_at": utc_now().replace(microsecond=0).isoformat(),
            "source_url": "https://example.com/reviewed-market-source",
            "source_captured_at": "YYYY-MM-DDTHH:MM:SS+00:00",
            "notes": "Explain source, resolution rule, and outcome mapping.",
            "resolution_rule": "",
            "outcome_mapping": {price_key: "market outcome label"},
        },
    }
