"""Event-level model error review for chronological replay."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from f1predict.domain import DriverRaceProbability, race_probabilities_by_expected_rank, utc_now
from f1predict.models.pace import PaceModel
from f1predict.pipeline import PredictionPipeline
from f1predict.replay import ReplayCoverageBuilder


@dataclass(frozen=True)
class ModelErrorEventReview:
    event_id: str
    event_name: str
    cutoff: str
    status: str
    top_pick: str
    actual_winner: str
    hit: bool
    actual_winner_rank: int
    top_pick_probability: float
    actual_winner_probability: float
    probability_gap_top_minus_actual: float
    race_score_gap_top_minus_actual: float
    qualifying_score_gap_top_minus_actual: float
    reliability_gap_top_minus_actual: float
    evidence_gap_top_minus_actual: float
    feature_gap_top_minus_actual: float
    market_snapshot_count: int
    market_snapshot_after_cutoff_count: int
    evidence_quality_warning_count: int
    issue_codes: tuple[str, ...]
    diagnosis_codes: tuple[str, ...]
    review_summary: str
    next_action: str
    candidate_drivers: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "cutoff": self.cutoff,
            "status": self.status,
            "top_pick": self.top_pick,
            "actual_winner": self.actual_winner,
            "hit": self.hit,
            "actual_winner_rank": self.actual_winner_rank,
            "top_pick_probability": self.top_pick_probability,
            "actual_winner_probability": self.actual_winner_probability,
            "probability_gap_top_minus_actual": self.probability_gap_top_minus_actual,
            "race_score_gap_top_minus_actual": self.race_score_gap_top_minus_actual,
            "qualifying_score_gap_top_minus_actual": self.qualifying_score_gap_top_minus_actual,
            "reliability_gap_top_minus_actual": self.reliability_gap_top_minus_actual,
            "evidence_gap_top_minus_actual": self.evidence_gap_top_minus_actual,
            "feature_gap_top_minus_actual": self.feature_gap_top_minus_actual,
            "market_snapshot_count": self.market_snapshot_count,
            "market_snapshot_after_cutoff_count": self.market_snapshot_after_cutoff_count,
            "evidence_quality_warning_count": self.evidence_quality_warning_count,
            "issue_codes": list(self.issue_codes),
            "diagnosis_codes": list(self.diagnosis_codes),
            "review_summary": self.review_summary,
            "next_action": self.next_action,
            "candidate_drivers": list(self.candidate_drivers),
        }


@dataclass(frozen=True)
class ModelErrorReviewReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    formal_model_claim_ready: bool
    reviewed_events: int
    missed_events: int
    actual_winners_ranked_top3: int
    issue_counts: dict[str, int]
    summary: dict[str, Any]
    findings: tuple[str, ...]
    events: tuple[ModelErrorEventReview, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "formal_model_claim_ready": self.formal_model_claim_ready,
            "reviewed_events": self.reviewed_events,
            "missed_events": self.missed_events,
            "actual_winners_ranked_top3": self.actual_winners_ranked_top3,
            "issue_counts": self.issue_counts,
            "summary": self.summary,
            "findings": list(self.findings),
            "events": [event.to_dict() for event in self.events],
            "warnings": list(self.warnings),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict Model Error Review ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Formal model claim ready: **{self.formal_model_claim_ready}**",
            f"- Reviewed events: {self.reviewed_events}",
            f"- Missed events: {self.missed_events}",
            f"- Actual winners ranked top 3: {self.actual_winners_ranked_top3}",
            "",
            "This report is diagnostic only. It explains current replay misses and should guide matched ablations; it is not proof that a simulator change improves edge.",
            "",
            "## Summary",
            "",
        ]
        for key, value in self.summary.items():
            lines.append(f"- {key}: {value}")
        if self.issue_counts:
            lines.extend(["", "## Diagnosis Counts", ""])
            for key, value in sorted(self.issue_counts.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if self.findings:
            lines.extend(["", "## Findings", ""])
            for finding in self.findings:
                lines.append(f"- {finding}")
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")
        lines.extend(["", "## Event Review", ""])
        lines.append(
            "| Event | Pick | Actual | Hit | Actual rank | Top p | Actual p | Race gap | Feature gap | Diagnosis |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
        for row in self.events:
            lines.append(
                "| "
                f"{row.event_name} | {row.top_pick} | {row.actual_winner} | {row.hit} | "
                f"{row.actual_winner_rank} | {row.top_pick_probability:.4f} | "
                f"{row.actual_winner_probability:.4f} | {row.race_score_gap_top_minus_actual:+.4f} | "
                f"{row.feature_gap_top_minus_actual:+.4f} | {', '.join(row.diagnosis_codes)} |"
            )
        lines.extend(["", "## Next Actions", ""])
        for row in self.events:
            if row.hit:
                continue
            lines.extend(
                [
                    f"### {row.event_name}",
                    "",
                    f"- Summary: {row.review_summary}",
                    f"- Next action: {row.next_action}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"


class ModelErrorReviewBuilder:
    """Explains replay hits and misses through probability and pace components."""

    def __init__(self, pipeline: PredictionPipeline | None = None) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)

    def build(self, year: int, as_of: str) -> ModelErrorReviewReport:
        coverage = ReplayCoverageBuilder(self.pipeline).build(year, as_of)
        season = self.pipeline.data_source.load()
        events_by_id = {event.event_id: event for event in season.events}
        reviews: list[ModelErrorEventReview] = []
        for replay_row in coverage.rows:
            if replay_row.status != "replayed" or not replay_row.seed_event_id or not replay_row.actual_winner:
                continue
            event = events_by_id.get(replay_row.seed_event_id)
            if event is None:
                continue
            cutoff = f"{event.date}T00:00:00+00:00"
            prediction = self.pipeline.predict_event(event.event_id, cutoff)
            pace_model = PaceModel(
                season,
                prediction.evidence,
                prediction.feature_adjustments,
                evidence_weights=self.pipeline._evidence_input_weights(prediction.evidence_quality),
            )
            probability_by_driver = {row.driver_id: row for row in prediction.race_probabilities}
            top = prediction.race_probabilities[0]
            actual = probability_by_driver.get(replay_row.actual_winner)
            if actual is None:
                continue
            candidate_drivers = self._candidate_rows(
                season,
                prediction.race_probabilities,
                pace_model,
                prediction.event,
                actual.driver_id,
            )
            top_detail = next(row for row in candidate_drivers if row["driver_id"] == top.driver_id)
            actual_detail = next(row for row in candidate_drivers if row["driver_id"] == actual.driver_id)
            diagnosis_codes = self._diagnosis_codes(replay_row.__dict__, top_detail, actual_detail, top, actual)
            reviews.append(
                ModelErrorEventReview(
                    event_id=event.event_id,
                    event_name=event.name,
                    cutoff=cutoff,
                    status="hit" if top.driver_id == actual.driver_id else "miss",
                    top_pick=top.driver_id,
                    actual_winner=actual.driver_id,
                    hit=top.driver_id == actual.driver_id,
                    actual_winner_rank=self._rank_of(prediction.race_probabilities, actual.driver_id),
                    top_pick_probability=round(top.win, 4),
                    actual_winner_probability=round(actual.win, 4),
                    probability_gap_top_minus_actual=round(top.win - actual.win, 4),
                    race_score_gap_top_minus_actual=round(
                        float(top_detail["race_score"]) - float(actual_detail["race_score"]),
                        4,
                    ),
                    qualifying_score_gap_top_minus_actual=round(
                        float(top_detail["qualifying_score"]) - float(actual_detail["qualifying_score"]),
                        4,
                    ),
                    reliability_gap_top_minus_actual=round(
                        float(top_detail["reliability"]) - float(actual_detail["reliability"]),
                        4,
                    ),
                    evidence_gap_top_minus_actual=round(
                        float(top_detail["evidence_total"]) - float(actual_detail["evidence_total"]),
                        4,
                    ),
                    feature_gap_top_minus_actual=round(
                        float(top_detail["feature_total"]) - float(actual_detail["feature_total"]),
                        4,
                    ),
                    market_snapshot_count=replay_row.market_snapshot_count,
                    market_snapshot_after_cutoff_count=replay_row.market_snapshot_after_cutoff_count,
                    evidence_quality_warning_count=sum(
                        1
                        for row in prediction.evidence_quality
                        if row.quality_status in {"weak_diagnostic", "review_required"}
                    ),
                    issue_codes=tuple(replay_row.warnings),
                    diagnosis_codes=diagnosis_codes,
                    review_summary=self._review_summary(event.name, top, actual, diagnosis_codes),
                    next_action=self._next_action(diagnosis_codes),
                    candidate_drivers=tuple(candidate_drivers),
                )
            )
        issue_counts = dict(Counter(code for row in reviews for code in row.diagnosis_codes))
        return ModelErrorReviewReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().isoformat(),
            status="diagnostic_only",
            formal_model_claim_ready=False,
            reviewed_events=len(reviews),
            missed_events=sum(1 for row in reviews if not row.hit),
            actual_winners_ranked_top3=sum(1 for row in reviews if row.actual_winner_rank <= 3),
            issue_counts=issue_counts,
            summary=self._summary(reviews),
            findings=self._findings(reviews, issue_counts),
            events=tuple(reviews),
            warnings=self._warnings(reviews),
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/model_error_review"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"
        json_path = directory / f"{stem}.model_error_review.json"
        markdown_path = directory / f"{stem}.model_error_review.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    @staticmethod
    def _candidate_rows(
        season,
        probabilities: list[DriverRaceProbability],
        pace_model: PaceModel,
        event,
        actual_winner: str,
    ) -> list[dict[str, Any]]:
        selected_ids = [row.driver_id for row in probabilities[:5]]
        if actual_winner not in selected_ids:
            selected_ids.append(actual_winner)
        rows = []
        probability_by_driver = {row.driver_id: row for row in probabilities}
        for driver_id in selected_ids:
            driver = season.drivers[driver_id]
            probability = probability_by_driver[driver_id]
            race = pace_model.score_breakdown(driver, event, mode="race")
            qualifying = pace_model.score_breakdown(driver, event, mode="qualifying")
            evidence_total = sum(
                value
                for components in (race, qualifying)
                for key, value in components.items()
                if key.startswith("evidence_")
            )
            feature_total = sum(
                value
                for components in (race, qualifying)
                for key, value in components.items()
                if key.startswith("feature_")
            )
            rows.append(
                {
                    "driver_id": driver_id,
                    "team_id": driver.team_id,
                    "win_probability": round(probability.win, 4),
                    "podium_probability": round(probability.podium, 4),
                    "expected_points": round(probability.expected_points, 3),
                    "average_finish": round(probability.average_finish, 3),
                    "race_score": round(race["total"], 4),
                    "qualifying_score": round(qualifying["total"], 4),
                    "reliability": round(pace_model.reliability(driver), 4),
                    "evidence_total": round(evidence_total, 4),
                    "feature_total": round(feature_total, 4),
                    "race_components": {key: round(value, 4) for key, value in race.items()},
                    "qualifying_components": {key: round(value, 4) for key, value in qualifying.items()},
                }
            )
        rows.sort(key=lambda row: float(row["win_probability"]), reverse=True)
        return rows

    @staticmethod
    def _diagnosis_codes(
        replay_row: dict[str, Any],
        top_detail: dict[str, Any],
        actual_detail: dict[str, Any],
        top: DriverRaceProbability,
        actual: DriverRaceProbability,
    ) -> tuple[str, ...]:
        if top.driver_id == actual.driver_id:
            return ("top_pick_matched_actual",)
        codes: list[str] = []
        rank = int(actual_detail.get("rank", 0) or 0)
        race_gap = float(top_detail["race_score"]) - float(actual_detail["race_score"])
        qualifying_gap = float(top_detail["qualifying_score"]) - float(actual_detail["qualifying_score"])
        feature_gap = float(top_detail["feature_total"]) - float(actual_detail["feature_total"])
        evidence_gap = float(top_detail["evidence_total"]) - float(actual_detail["evidence_total"])
        reliability_gap = float(top_detail["reliability"]) - float(actual_detail["reliability"])
        probability_gap = top.win - actual.win
        if probability_gap <= 0.08:
            codes.append("near_miss_probability_cluster")
        else:
            codes.append("actual_winner_underweighted")
        if race_gap > 0.06:
            codes.append("race_pace_prior_favored_top_pick")
        if qualifying_gap > 0.08:
            codes.append("grid_prior_favored_top_pick")
        if feature_gap > 0.04:
            codes.append("structured_features_favored_top_pick")
        if evidence_gap > 0.015:
            codes.append("codex_evidence_favored_top_pick")
        if reliability_gap > 0.015:
            codes.append("reliability_prior_favored_top_pick")
        if int(replay_row.get("market_snapshot_count") or 0) == 0:
            codes.append("no_market_prior_to_compare")
        if "season_opener_no_prior_form" in replay_row.get("warnings", ()):
            codes.append("season_opener_feature_horizon")
        return tuple(codes or ("miss_needs_manual_review",))

    @staticmethod
    def _rank_of(probabilities: list[DriverRaceProbability], driver_id: str) -> int:
        for index, item in enumerate(race_probabilities_by_expected_rank(probabilities), start=1):
            if item.driver_id == driver_id:
                return index
        return len(probabilities) + 1

    @staticmethod
    def _summary(rows: list[ModelErrorEventReview]) -> dict[str, Any]:
        misses = [row for row in rows if not row.hit]
        return {
            "top_pick_hit_rate": round(sum(1 for row in rows if row.hit) / len(rows), 4) if rows else None,
            "mean_actual_winner_probability": round(mean(row.actual_winner_probability for row in rows), 4) if rows else None,
            "mean_probability_gap_on_misses": round(mean(row.probability_gap_top_minus_actual for row in misses), 4) if misses else None,
            "mean_race_score_gap_on_misses": round(mean(row.race_score_gap_top_minus_actual for row in misses), 4) if misses else None,
            "mean_feature_gap_on_misses": round(mean(row.feature_gap_top_minus_actual for row in misses), 4) if misses else None,
            "misses_with_actual_top3": sum(1 for row in misses if row.actual_winner_rank <= 3),
            "misses_without_market_snapshot": sum(1 for row in misses if row.market_snapshot_count == 0),
        }

    @staticmethod
    def _findings(rows: list[ModelErrorEventReview], issue_counts: dict[str, int]) -> tuple[str, ...]:
        findings: list[str] = []
        misses = [row for row in rows if not row.hit]
        if not rows:
            return ("No replayed events were available for model error review.",)
        if misses and sum(1 for row in misses if row.actual_winner_rank <= 3) >= max(1, len(misses) // 2):
            findings.append(
                "Most misses still ranked the actual winner near the front; prioritize probability/ranking calibration before large model rewrites."
            )
        if issue_counts.get("race_pace_prior_favored_top_pick", 0):
            findings.append(
                "Race-pace priors frequently favored the wrong top pick; review FastF1 form weighting, team baseline strength, and track-affinity scaling."
            )
        if issue_counts.get("grid_prior_favored_top_pick", 0):
            findings.append(
                "Qualifying/grid priors favored the wrong top pick in some misses; add session-specific qualifying features before increasing grid influence."
            )
        if issue_counts.get("structured_features_favored_top_pick", 0):
            findings.append(
                "Structured features contributed to at least one wrong preference; inspect feature provenance and confidence weights before treating them as strong signals."
            )
        if issue_counts.get("no_market_prior_to_compare", 0):
            findings.append(
                "Most miss reviews still lack same-time market priors, so model-vs-market edge diagnosis remains incomplete."
            )
        return tuple(findings)

    @staticmethod
    def _warnings(rows: list[ModelErrorEventReview]) -> tuple[str, ...]:
        warnings = ["diagnostic_only_not_matched_ablation"]
        if len(rows) < 20:
            warnings.append("small_sample_less_than_20_scored_events")
        if any(row.market_snapshot_count == 0 for row in rows):
            warnings.append("market_snapshot_subset_incomplete")
        return tuple(warnings)

    @staticmethod
    def _review_summary(
        event_name: str,
        top: DriverRaceProbability,
        actual: DriverRaceProbability,
        diagnosis_codes: tuple[str, ...],
    ) -> str:
        if top.driver_id == actual.driver_id:
            return f"{event_name} was a replay hit; keep it as a control row when testing model changes."
        return (
            f"{event_name} missed with {top.driver_id} over {actual.driver_id}; "
            f"diagnosis: {', '.join(diagnosis_codes)}."
        )

    @staticmethod
    def _next_action(diagnosis_codes: tuple[str, ...]) -> str:
        if "top_pick_matched_actual" in diagnosis_codes:
            return "Use as a control row in matched simulator ablations."
        if "race_pace_prior_favored_top_pick" in diagnosis_codes:
            return "Run a matched ablation on race-pace/form/track-affinity weights and compare log loss, Brier, and actual-winner rank."
        if "grid_prior_favored_top_pick" in diagnosis_codes:
            return "Add or backfill cutoff-valid qualifying/session features before increasing grid influence."
        if "structured_features_favored_top_pick" in diagnosis_codes:
            return "Review structured feature provenance and confidence; test a lower feature-weight candidate in simulator calibration."
        if "near_miss_probability_cluster" in diagnosis_codes:
            return "Tune probability calibration and race-noise parameters rather than making a broad model rewrite."
        return "Inspect event-specific features, Codex evidence, and simulator parameters before changing production defaults."
