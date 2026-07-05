"""Command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from f1predict.backtest import Backtester
from f1predict.calibration import ReplayCalibrationBuilder
from f1predict.chronological_replay import ChronologicalReplayBundleBuilder
from f1predict.domain import parse_dt
from f1predict.features.calendar import CalendarBuilder
from f1predict.features.openf1_summary import OpenF1SummaryBuilder
from f1predict.improvement_plan import ImprovementPlanBuilder
from f1predict.ingestion import LiveIngestor
from f1predict.intelligence.codex import CodexEvidenceProvider, EvidencePacketStore
from f1predict.intelligence.evidence_workflow import CodexResearchWorkspaceBuilder, EvidenceCoverageAuditor
from f1predict.intelligence.research_brief import ResearchBriefBuilder
from f1predict.intelligence.research_packet import CodexResearchPacketArchiver, CodexResearchPacketPreflight
from f1predict.intelligence.research_plan import CodexResearchPlanBuilder
from f1predict.intelligence.source_candidates import CodexSourceCandidateBuilder
from f1predict.intelligence.source_registry import (
    DEFAULT_SOURCE_RELIABILITY,
    SourceArchiveBackfiller,
    SourceLogAuditor,
    SourceSnapshotter,
)
from f1predict.market import after_cutoff_market_count, event_market_snapshots
from f1predict.market_sources.polymarket import (
    PolymarketDiscoveryAuditor,
    PolymarketGammaNormalizer,
    PolymarketLiveSnapshotter,
    PolymarketPriceHistoryBackfiller,
    PolymarketSearchHistoryBackfiller,
    PolymarketSeasonSearchAuditor,
)
from f1predict.market_readiness import ReadinessMarketScanner
from f1predict.market_store import MarketSnapshotStore
from f1predict.manifest import ReplayFreezeManifestBuilder
from f1predict.model_error_review import ModelErrorReviewBuilder
from f1predict.mvp_completion_audit import MVPCompletionAuditBuilder
from f1predict.mvp_gate import MVPGateBuilder
from f1predict.official_standings import OfficialStandingsRepository
from f1predict.pipeline import PredictionPipeline
from f1predict.prediction_packet import PredictionPacketBuilder
from f1predict.readiness import FormalReadinessBuilder
from f1predict.readiness_intake import ReadinessIntakeExporter, ReadinessIntakeVerifier
from f1predict.replay import ReplayCoverageBuilder
from f1predict.replay_analysis import ReplayAnalysisBuilder
from f1predict.reviewed_market import ReviewedMarketSnapshotArchiver, reviewed_market_template
from f1predict.run_tracking import InformationIntakeStore, MatchedPredictionDiff, PredictionRunRegistry
from f1predict.seed_roster import SeedRosterSyncPlanner
from f1predict.simulator_calibration import SimulatorCalibrationBuilder
from f1predict.source_replacements import SourceReplacementApplier, SourceReplacementCandidateBuilder
from f1predict.track_assets import TrackAssetAuditor


def _read_json(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _raw_snapshot_captured_at(path: Path | str) -> str | None:
    input_path = Path(path)
    candidates = [
        input_path.with_name(f"{input_path.stem}.meta.json"),
        input_path.with_name(f"{input_path.name}.meta.json"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        meta = _read_json(candidate)
        captured_at = meta.get("captured_at")
        return str(captured_at) if captured_at else None
    return None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="f1predict")
    sub = parser.add_subparsers(dest="command", required=True)

    predict = sub.add_parser("predict", help="Run event prediction")
    predict.add_argument("--event", default="british_gp")
    predict.add_argument("--knowledge-cutoff", default=None)
    predict.add_argument("--iterations", type=int, default=5000)

    prediction_packet = sub.add_parser("prediction-packet", help="Build an auditable single-event prediction packet")
    prediction_packet.add_argument("--event", default="british_gp")
    prediction_packet.add_argument("--knowledge-cutoff", default=None)
    prediction_packet.add_argument("--iterations", type=int, default=1200)
    prediction_packet.add_argument("--write", action="store_true")
    prediction_packet.add_argument("--output-dir", default="reports/prediction_packets")
    prediction_packet.add_argument("--register-run", action="store_true")
    prediction_packet.add_argument("--registry-root", default="reports/prediction_runs")
    prediction_packet.add_argument("--information-intake", default=None)

    season_forecast = sub.add_parser("season-forecast", help="Run cutoff-aware season points forecast")
    season_forecast.add_argument("--knowledge-cutoff", default=None)
    season_forecast.add_argument("--iterations", type=int, default=1500)
    season_forecast.add_argument("--output", default=None)

    official_standings = sub.add_parser(
        "build-official-standings",
        help="Parse stored F1 official driver/team standings into structured rows",
    )
    official_standings.add_argument("--year", type=int, required=True)
    official_standings.add_argument("--knowledge-cutoff", default=None)
    official_standings.add_argument("--write", action="store_true")

    roster_sync = sub.add_parser(
        "sync-official-roster",
        help="Plan or apply audited seed-roster updates from F1 official standings",
    )
    roster_sync.add_argument("--year", type=int, required=True)
    roster_sync.add_argument("--seed", default="data/seed/demo_season.json")
    roster_sync.add_argument("--knowledge-cutoff", default=None)
    roster_sync.add_argument("--apply", action="store_true", help="Apply auto-safe operations to the seed file")
    roster_sync.add_argument("--output", default=None, help="Write applied seed JSON to this path instead of the input")
    roster_sync.add_argument("--plan-output", default=None, help="Write the roster sync plan JSON to this path")
    roster_sync.add_argument(
        "--apply-review-required",
        action="store_true",
        help="Also apply operations marked review_required, such as new drivers or teams with default model priors",
    )

    sub.add_parser("events", help="List events")
    sub.add_parser("backtest", help="Run diagnostic replay over completed events")

    replay_report = sub.add_parser("replay-report", help="Build chronological replay coverage report")
    replay_report.add_argument("--year", type=int, required=True)
    replay_report.add_argument("--as-of", required=True)
    replay_report.add_argument("--write", action="store_true")

    replay_analysis = sub.add_parser("analyze-replay", help="Analyze chronological replay failure modes")
    replay_analysis.add_argument("--year", type=int, required=True)
    replay_analysis.add_argument("--as-of", required=True)
    replay_analysis.add_argument("--iterations", type=int, default=1200)
    replay_analysis.add_argument("--write", action="store_true")
    replay_analysis.add_argument("--output-dir", default="reports/replay_analysis")

    chronological_replay = sub.add_parser(
        "chronological-replay",
        help="Build the full chronological replay bundle and component diagnostics",
    )
    chronological_replay.add_argument("--year", type=int, required=True)
    chronological_replay.add_argument("--as-of", required=True)
    chronological_replay.add_argument("--iterations", type=int, default=1200)
    chronological_replay.add_argument("--write", action="store_true")
    chronological_replay.add_argument("--output-dir", default="reports/chronological_replay")
    chronological_replay.add_argument(
        "--no-components",
        action="store_true",
        help="Only write the bundle; do not regenerate replay/analysis/readiness/calibration/improvement reports",
    )
    chronological_replay.add_argument(
        "--no-freeze",
        action="store_true",
        help="Do not refresh the replay freeze manifest after writing the bundle",
    )

    readiness = sub.add_parser("formal-readiness", help="Build formal replay input-readiness manifest")
    readiness.add_argument("--year", type=int, required=True)
    readiness.add_argument("--as-of", required=True)
    readiness.add_argument("--iterations", type=int, default=1200)
    readiness.add_argument("--write", action="store_true")
    readiness.add_argument("--output-dir", default="reports/formal_readiness")

    readiness_intake = sub.add_parser("export-readiness-intake", help="Export readiness workstreams as task queues")
    readiness_intake.add_argument("--year", type=int, required=True)
    readiness_intake.add_argument("--as-of", required=True)
    readiness_intake.add_argument("--iterations", type=int, default=1200)
    readiness_intake.add_argument("--output-dir", default="reports/readiness_intake")

    verify_readiness_intake = sub.add_parser("verify-readiness-intake", help="Verify exported readiness queues")
    verify_readiness_intake.add_argument("--year", type=int, required=True)
    verify_readiness_intake.add_argument("--as-of", required=True)
    verify_readiness_intake.add_argument("--iterations", type=int, default=1200)
    verify_readiness_intake.add_argument("--bundle-root", default="reports/readiness_intake")
    verify_readiness_intake.add_argument("--write", action="store_true")

    readiness_markets = sub.add_parser(
        "scan-readiness-markets",
        help="Search Polymarket candidates for market-related readiness actions",
    )
    readiness_markets.add_argument("--year", type=int, required=True)
    readiness_markets.add_argument("--as-of", required=True)
    readiness_markets.add_argument("--limit", type=int, default=20)
    readiness_markets.add_argument("--market-type", default="winner")
    readiness_markets.add_argument("--include-closed", dest="include_closed", action="store_true", default=True)
    readiness_markets.add_argument("--active-only", dest="include_closed", action="store_false")
    readiness_markets.add_argument("--bundle-root", default="reports/readiness_intake")
    readiness_markets.add_argument("--write", action="store_true")
    readiness_markets.add_argument("--output-dir", default="reports/market_readiness")

    improvement_plan = sub.add_parser(
        "improvement-plan",
        help="Build a prioritized improvement plan from current replay diagnostics",
    )
    improvement_plan.add_argument("--year", type=int, required=True)
    improvement_plan.add_argument("--as-of", required=True)
    improvement_plan.add_argument("--iterations", type=int, default=1200)
    improvement_plan.add_argument("--write", action="store_true")
    improvement_plan.add_argument("--output-dir", default="reports/improvement_plan")

    calibration = sub.add_parser("calibration-report", help="Build replay probability calibration diagnostics")
    calibration.add_argument("--year", type=int, required=True)
    calibration.add_argument("--as-of", required=True)
    calibration.add_argument("--iterations", type=int, default=1200)
    calibration.add_argument("--write", action="store_true")
    calibration.add_argument("--output-dir", default="reports/calibration")

    model_error_review = sub.add_parser(
        "model-error-review",
        help="Explain replay hits and misses through model input components",
    )
    model_error_review.add_argument("--year", type=int, required=True)
    model_error_review.add_argument("--as-of", required=True)
    model_error_review.add_argument("--iterations", type=int, default=1200)
    model_error_review.add_argument("--write", action="store_true")
    model_error_review.add_argument("--output-dir", default="reports/model_error_review")

    mvp_gate = sub.add_parser(
        "mvp-gate",
        help="Build a requirement-by-requirement MVP delivery gate",
    )
    mvp_gate.add_argument("--year", type=int, required=True)
    mvp_gate.add_argument("--as-of", required=True)
    mvp_gate.add_argument("--write", action="store_true")
    mvp_gate.add_argument("--output-dir", default="reports/mvp_gate")

    mvp_completion_audit = sub.add_parser(
        "mvp-completion-audit",
        help="Audit the current artifacts against the diagnostic MVP objective",
    )
    mvp_completion_audit.add_argument("--year", type=int, required=True)
    mvp_completion_audit.add_argument("--as-of", required=True)
    mvp_completion_audit.add_argument("--write", action="store_true")
    mvp_completion_audit.add_argument("--output-dir", default="reports/mvp_completion_audit")

    track_assets = sub.add_parser(
        "audit-track-assets",
        help="Verify that season events expose real verified circuit-map assets",
    )
    track_assets.add_argument("--year", type=int, required=True)
    track_assets.add_argument("--write", action="store_true")
    track_assets.add_argument("--output-dir", default="reports/track_assets")

    simulator_calibration = sub.add_parser(
        "simulator-calibration",
        help="Compare diagnostic simulator parameter candidates over replayable races",
    )
    simulator_calibration.add_argument("--year", type=int, required=True)
    simulator_calibration.add_argument("--as-of", required=True)
    simulator_calibration.add_argument("--iterations", type=int, default=800)
    simulator_calibration.add_argument("--write", action="store_true")
    simulator_calibration.add_argument("--output-dir", default="reports/simulator_calibration")

    freeze_manifest = sub.add_parser("replay-freeze-manifest", help="Build a hash manifest for a replay state")
    freeze_manifest.add_argument("--year", type=int, required=True)
    freeze_manifest.add_argument("--as-of", required=True)
    freeze_manifest.add_argument("--iterations", type=int, default=1200)
    freeze_manifest.add_argument("--write", action="store_true")
    freeze_manifest.add_argument("--output-dir", default="reports/replay_freeze")

    ingest_openf1 = sub.add_parser("ingest-openf1", help="Snapshot OpenF1 event data")
    ingest_openf1.add_argument("--year", type=int, required=True)
    ingest_openf1.add_argument("--event-query", required=True)
    ingest_openf1.add_argument("--include-session-data", action="store_true")

    ingest_openf1_calendar = sub.add_parser("ingest-openf1-calendar", help="Snapshot OpenF1 yearly meetings")
    ingest_openf1_calendar.add_argument("--year", type=int, required=True)

    ingest_circuit_profiles = sub.add_parser(
        "ingest-circuit-profiles",
        help="Snapshot circuit geometry profiles from OpenF1 circuit_info_url values",
    )
    ingest_circuit_profiles.add_argument("--year", type=int, required=True)
    ingest_circuit_profiles.add_argument("--event", action="append", default=[])

    ingest_weather_profiles = sub.add_parser(
        "ingest-weather-profiles",
        help="Snapshot Open-Meteo historical climate weather profiles for season events",
    )
    ingest_weather_profiles.add_argument("--year", type=int, required=True)
    ingest_weather_profiles.add_argument("--event", action="append", default=[])
    ingest_weather_profiles.add_argument("--baseline-start-year", type=int, default=None)
    ingest_weather_profiles.add_argument("--baseline-end-year", type=int, default=None)
    ingest_weather_profiles.add_argument("--window-days", type=int, default=3)

    ingest_weather_forecast = sub.add_parser(
        "ingest-weather-forecast",
        help="Snapshot Open-Meteo race-week weather forecasts for season events",
    )
    ingest_weather_forecast.add_argument("--year", type=int, required=True)
    ingest_weather_forecast.add_argument("--event", action="append", default=[])
    ingest_weather_forecast.add_argument("--forecast-days", type=int, default=16)

    ingest_poly = sub.add_parser("ingest-polymarket", help="Snapshot Polymarket F1 event data")
    ingest_poly.add_argument("--limit", type=int, default=20)

    normalize_poly = sub.add_parser(
        "normalize-polymarket",
        help="Normalize a Polymarket Gamma payload into project market snapshots",
    )
    normalize_poly.add_argument("--event", required=True)
    normalize_poly.add_argument("--input", required=True)
    normalize_poly.add_argument("--captured-at", default=None)
    normalize_poly.add_argument("--knowledge-cutoff", default=None)
    normalize_poly.add_argument("--market-type", default="winner")
    normalize_poly.add_argument("--event-alias", action="append", default=[])
    normalize_poly.add_argument("--include-closed", action="store_true")
    normalize_poly.add_argument("--write", action="store_true")
    normalize_poly.add_argument("--market-root", default="data/market_snapshots")
    normalize_poly.add_argument("--output", default=None)

    discover_poly = sub.add_parser(
        "discover-polymarket-markets",
        help="Audit which season events are represented in a Polymarket Gamma payload",
    )
    discover_poly.add_argument("--input", required=True)
    discover_poly.add_argument("--market-type", default="winner")
    discover_poly.add_argument("--include-closed", action="store_true")
    discover_poly.add_argument("--event", action="append", default=[])
    discover_poly.add_argument("--output", default=None)

    search_poly = sub.add_parser(
        "search-polymarket-season",
        help="Search Polymarket Gamma markets by season event names and audit matches",
    )
    search_poly.add_argument("--limit", type=int, default=20)
    search_poly.add_argument("--market-type", default="winner")
    search_poly.add_argument("--include-closed", action="store_true")
    search_poly.add_argument("--event", action="append", default=[])
    search_poly.add_argument("--output", default=None)

    capture_poly = sub.add_parser(
        "capture-polymarket-snapshot",
        help="Search Polymarket and archive a same-time order-book-backed market snapshot",
    )
    capture_poly.add_argument("--event", required=True)
    capture_poly.add_argument("--limit", type=int, default=20)
    capture_poly.add_argument("--market-type", default="winner")
    capture_poly.add_argument("--event-alias", action="append", default=[])
    capture_poly.add_argument("--include-closed", action="store_true")
    capture_poly.add_argument("--captured-at", default=None)
    capture_poly.add_argument("--wide-spread-threshold", type=float, default=0.10)
    capture_poly.add_argument("--write", action="store_true")
    capture_poly.add_argument("--market-root", default="data/market_snapshots")
    capture_poly.add_argument("--output", default=None)

    backfill_poly = sub.add_parser(
        "backfill-polymarket-history",
        help="Backfill cutoff market snapshots from Polymarket price history",
    )
    backfill_poly.add_argument("--event", required=True)
    backfill_poly.add_argument("--input", required=True)
    backfill_poly.add_argument("--knowledge-cutoff", required=True)
    backfill_poly.add_argument("--lookback-hours", type=int, default=168)
    backfill_poly.add_argument("--fidelity-minutes", type=int, default=1)
    backfill_poly.add_argument("--market-type", default="winner")
    backfill_poly.add_argument("--event-alias", action="append", default=[])
    backfill_poly.add_argument("--include-closed", action="store_true")
    backfill_poly.add_argument("--write", action="store_true")
    backfill_poly.add_argument("--market-root", default="data/market_snapshots")
    backfill_poly.add_argument("--output", default=None)

    search_backfill_poly = sub.add_parser(
        "search-backfill-polymarket-history",
        help="Search Polymarket markets and backfill cutoff prices from price history",
    )
    search_backfill_poly.add_argument("--event", required=True)
    search_backfill_poly.add_argument("--knowledge-cutoff", required=True)
    search_backfill_poly.add_argument("--limit", type=int, default=20)
    search_backfill_poly.add_argument("--lookback-hours", type=int, default=168)
    search_backfill_poly.add_argument("--fidelity-minutes", type=int, default=1)
    search_backfill_poly.add_argument("--market-type", default="winner")
    search_backfill_poly.add_argument("--event-alias", action="append", default=[])
    search_backfill_poly.add_argument("--include-closed", action="store_true")
    search_backfill_poly.add_argument("--write", action="store_true")
    search_backfill_poly.add_argument("--market-root", default="data/market_snapshots")
    search_backfill_poly.add_argument("--output", default=None)
    search_backfill_poly.add_argument("--search-output", default=None)

    archive_market = sub.add_parser(
        "archive-market-snapshot",
        help="Archive validated normalized market snapshots",
    )
    archive_market.add_argument("--event", required=True)
    archive_market.add_argument("--input", required=True)
    archive_market.add_argument("--market-root", default="data/market_snapshots")
    archive_market.add_argument("--source", default="manual")
    archive_market.add_argument("--knowledge-cutoff", default=None)

    reviewed_market = sub.add_parser(
        "archive-reviewed-market-snapshot",
        help="Archive a Codex/human-reviewed market snapshot packet",
    )
    reviewed_market.add_argument("--event", required=True)
    reviewed_market.add_argument("--input", required=True)
    reviewed_market.add_argument("--knowledge-cutoff", default=None)
    reviewed_market.add_argument("--require-cutoff-valid", action="store_true")
    reviewed_market.add_argument("--market-root", default="data/market_snapshots")
    reviewed_market.add_argument("--dry-run", action="store_true")
    reviewed_market.add_argument("--output", default=None)

    reviewed_market_template_cmd = sub.add_parser(
        "reviewed-market-template",
        help="Print a reviewed market snapshot packet template",
    )
    reviewed_market_template_cmd.add_argument("--event", required=True)
    reviewed_market_template_cmd.add_argument("--market-type", default="winner")

    ingest_fastf1 = sub.add_parser("ingest-fastf1-schedule", help="Snapshot FastF1 event schedule")
    ingest_fastf1.add_argument("--year", type=int, required=True)

    ingest_fastf1_results = sub.add_parser("ingest-fastf1-results", help="Snapshot FastF1 session results")
    ingest_fastf1_results.add_argument("--year", type=int, required=True)
    ingest_fastf1_results.add_argument("--event", default=None, help="FastF1 event name or location query")
    ingest_fastf1_results.add_argument("--round", type=int, default=None, help="FastF1 round number")
    ingest_fastf1_results.add_argument("--session", default="R")
    ingest_fastf1_results.add_argument("--as-of", default=None, help="Batch all due race sessions up to this UTC cutoff")

    ingest_official = sub.add_parser("ingest-f1-official", help="Snapshot F1 official HTML page")
    ingest_official.add_argument("--year", type=int, required=True)
    ingest_official.add_argument("--page", choices=["calendar", "drivers", "teams"], required=True)

    ingest_official_races = sub.add_parser(
        "ingest-f1-race-profiles",
        help="Snapshot F1 official race profile pages, including planned lap counts",
    )
    ingest_official_races.add_argument("--year", type=int, required=True)
    ingest_official_races.add_argument("--slug", action="append", default=[])

    summarize_openf1 = sub.add_parser("summarize-openf1", help="Build processed OpenF1 event summary")
    summarize_openf1.add_argument("--year", type=int, required=True)
    summarize_openf1.add_argument("--event-query", required=True)
    summarize_openf1.add_argument("--write", action="store_true")

    calendar = sub.add_parser("build-calendar", help="Build normalized calendar from raw snapshots")
    calendar.add_argument("--year", type=int, required=True)
    calendar.add_argument("--write", action="store_true")

    validate = sub.add_parser("validate-evidence", help="Validate Codex evidence JSONL")
    validate.add_argument("--event", required=True)
    validate.add_argument("--path", default=None)

    ingest_evidence = sub.add_parser("ingest-evidence", help="Archive a validated Codex evidence JSONL packet")
    ingest_evidence.add_argument("--event", required=True)
    ingest_evidence.add_argument("--input", required=True)
    ingest_evidence.add_argument("--source-log", default=None)
    ingest_evidence.add_argument("--knowledge-cutoff", default=None)
    ingest_evidence.add_argument("--packet-root", default="data/evidence")

    archive_research_packet = sub.add_parser(
        "archive-research-packet",
        help="Snapshot sources, audit, and archive a Codex research packet manifest",
    )
    archive_research_packet.add_argument("--input", required=True)
    archive_research_packet.add_argument("--event", default=None)
    archive_research_packet.add_argument("--knowledge-cutoff", default=None)
    archive_research_packet.add_argument("--research-root", default="data/research")
    archive_research_packet.add_argument("--packet-root", default="data/evidence")
    archive_research_packet.add_argument("--append-draft", action="store_true")

    preflight_research_packet = sub.add_parser(
        "preflight-research-packet",
        help="Dry-run schema, source, quality, and simulator-route diagnostics for a Codex research packet",
    )
    preflight_research_packet.add_argument("--input", required=True)
    preflight_research_packet.add_argument("--event", default=None)
    preflight_research_packet.add_argument("--knowledge-cutoff", default=None)
    preflight_research_packet.add_argument("--source-candidate-report", default=None)
    preflight_research_packet.add_argument("--source-candidates-input", default=None)
    preflight_research_packet.add_argument("--output", default=None)
    preflight_research_packet.add_argument("--markdown-output", default=None)

    codex_source_candidates = sub.add_parser(
        "codex-source-candidates",
        help="Audit Codex web-search source candidates before drafting evidence claims",
    )
    codex_source_candidates.add_argument("--event", required=True)
    codex_source_candidates.add_argument("--input", default=None)
    codex_source_candidates.add_argument("--knowledge-cutoff", default=None)
    codex_source_candidates.add_argument("--output", default=None)
    codex_source_candidates.add_argument("--markdown-output", default=None)

    audit_evidence_sources = sub.add_parser("audit-evidence-sources", help="Audit evidence claims against a source log")
    audit_evidence_sources.add_argument("--event", required=True)
    audit_evidence_sources.add_argument("--input", required=True)
    audit_evidence_sources.add_argument("--source-log", required=True)
    audit_evidence_sources.add_argument("--knowledge-cutoff", default=None)

    snapshot_source = sub.add_parser("snapshot-source", help="Snapshot a source URL into the Codex research audit trail")
    snapshot_source.add_argument("--event", required=True)
    snapshot_source.add_argument("--url", required=True)
    snapshot_source.add_argument("--source", required=True)
    snapshot_source.add_argument("--source-class", choices=sorted(DEFAULT_SOURCE_RELIABILITY), required=True)
    snapshot_source.add_argument("--published-at", default=None)
    snapshot_source.add_argument("--observed-at", default=None)
    snapshot_source.add_argument("--knowledge-cutoff", default=None)
    snapshot_source.add_argument("--notes", default="")
    snapshot_source.add_argument("--research-root", default="data/research")
    snapshot_source.add_argument("--claim-id", action="append", default=[])
    snapshot_source.add_argument("--historical-archive-url", default=None)
    snapshot_source.add_argument("--historical-archived-at", default=None)
    snapshot_source.add_argument("--historical-original-url", default=None)
    snapshot_source.add_argument("--historical-verification-method", default=None)
    snapshot_source.add_argument("--historical-notes", default="")

    discover_source_archives = sub.add_parser(
        "discover-source-archives",
        help="Find cutoff-valid Wayback archive captures for retrospective source snapshots",
    )
    discover_source_archives.add_argument("--event", action="append", default=[])
    discover_source_archives.add_argument("--research-root", default="data/research")
    discover_source_archives.add_argument("--write", action="store_true")
    discover_source_archives.add_argument("--limit", type=int, default=None)
    discover_source_archives.add_argument("--output", default=None)

    source_replacements = sub.add_parser(
        "source-replacement-candidates",
        help="Review replacement-source candidates for unresolved source archive blockers",
    )
    source_replacements.add_argument("--input", default="reports/source_archives/remaining_blockers_cdx_discovery.json")
    source_replacements.add_argument("--event", action="append", default=[])
    source_replacements.add_argument("--no-current-check", action="store_true")
    source_replacements.add_argument("--no-archive-check", action="store_true")
    source_replacements.add_argument("--write", action="store_true")
    source_replacements.add_argument("--output-dir", default="reports/source_replacements")

    apply_source_replacement = sub.add_parser(
        "apply-source-replacement",
        help="Apply a formal-ready replacement source candidate into source/evidence logs",
    )
    apply_source_replacement.add_argument("--candidate-id", required=True)
    apply_source_replacement.add_argument(
        "--replacement-report",
        default="reports/source_replacements/remaining_blockers.source_replacements.json",
    )
    apply_source_replacement.add_argument("--research-root", default="data/research")
    apply_source_replacement.add_argument("--packet-root", default="data/evidence")
    apply_source_replacement.add_argument("--evidence-dir", default="data/seed/evidence")
    apply_source_replacement.add_argument(
        "--content-override",
        default=None,
        help="Optional local text/html file to use instead of fetching current candidate URL",
    )

    brief = sub.add_parser("research-brief", help="Generate Codex research brief")
    brief.add_argument("--event", required=True)
    brief.add_argument("--output", default=None)

    research_plan = sub.add_parser(
        "codex-research-plan",
        help="Build a source-quality and impact-rubric plan for Codex research",
    )
    research_plan.add_argument("--event", required=True)
    research_plan.add_argument("--knowledge-cutoff", default=None)
    research_plan.add_argument("--write", action="store_true")
    research_plan.add_argument("--output-dir", default="data/research")
    research_plan.add_argument("--output", default=None)
    research_plan.add_argument("--markdown-output", default=None)

    evidence_coverage = sub.add_parser("evidence-coverage", help="Audit Codex evidence coverage")
    evidence_coverage.add_argument("--as-of", default=None)
    evidence_coverage.add_argument("--write", action="store_true")
    evidence_coverage.add_argument("--output", default="reports/evidence_coverage.json")

    prepare_research = sub.add_parser("prepare-research", help="Create Codex research workspace files")
    prepare_research.add_argument("--event", default=None)
    prepare_research.add_argument("--knowledge-cutoff", default=None)
    prepare_research.add_argument("--as-of", default=None, help="Batch completed events up to this cutoff")
    prepare_research.add_argument("--output-dir", default="data/research")
    prepare_research.add_argument("--include-existing-evidence", action="store_true")

    information_intake = sub.add_parser(
        "build-information-intake",
        help="Build the structured local information snapshot available to a prediction",
    )
    information_intake.add_argument("--event", default="british_gp")
    information_intake.add_argument("--knowledge-cutoff", default=None)
    information_intake.add_argument("--write", action="store_true")
    information_intake.add_argument("--intake-root", default="data/intake")
    information_intake.add_argument("--research-root", default="data/research")
    information_intake.add_argument("--reports-root", default="reports")

    register_prediction_run = sub.add_parser(
        "register-prediction-run",
        help="Register an existing prediction packet as a comparable prediction run",
    )
    register_prediction_run.add_argument("--packet", required=True)
    register_prediction_run.add_argument("--information-intake", default=None)
    register_prediction_run.add_argument("--registry-root", default="reports/prediction_runs")
    register_prediction_run.add_argument("--notes", default=None)

    diff_prediction_runs = sub.add_parser(
        "diff-prediction-runs",
        help="Compare two registered prediction runs under the same output schema",
    )
    diff_prediction_runs.add_argument("--base-run", required=True)
    diff_prediction_runs.add_argument("--candidate-run", required=True)
    diff_prediction_runs.add_argument("--registry-root", default="reports/prediction_runs")
    diff_prediction_runs.add_argument("--write", action="store_true")
    diff_prediction_runs.add_argument("--output-dir", default="reports/prediction_diffs")

    features = sub.add_parser("features", help="Show processed feature adjustments for an event")
    features.add_argument("--event", required=True)

    args = parser.parse_args()
    if args.command == "predict":
        report = PredictionPipeline(iterations=args.iterations).predict_event(
            event_id=args.event,
            knowledge_cutoff=args.knowledge_cutoff,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "prediction-packet":
        builder = PredictionPacketBuilder(PredictionPipeline(iterations=args.iterations))
        if args.write:
            paths = builder.write(
                args.event,
                knowledge_cutoff=args.knowledge_cutoff,
                iterations=args.iterations,
                output_dir=args.output_dir,
            )
            payload = {name: str(path) for name, path in paths.items()}
            if args.register_run:
                record = PredictionRunRegistry(args.registry_root).register_packet(
                    paths["json"],
                    information_intake_path=args.information_intake,
                )
                payload["prediction_run"] = record.to_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if args.register_run:
                raise ValueError("prediction-packet --register-run requires --write so the run points to a packet file")
            packet = builder.build(args.event, knowledge_cutoff=args.knowledge_cutoff, iterations=args.iterations)
            print(json.dumps(packet.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "season-forecast":
        report = PredictionPipeline(iterations=args.iterations).forecast_season(
            knowledge_cutoff=args.knowledge_cutoff,
            iterations=args.iterations,
        )
        payload = report.to_dict()
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "build-official-standings":
        season = PredictionPipeline().data_source.load()
        repository = OfficialStandingsRepository()
        if args.write:
            path = repository.write(args.year, season=season, knowledge_cutoff=args.knowledge_cutoff)
            print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        else:
            report = repository.build(args.year, season=season, knowledge_cutoff=args.knowledge_cutoff)
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "sync-official-roster":
        planner = SeedRosterSyncPlanner()
        plan = planner.plan(args.year, seed_path=args.seed, knowledge_cutoff=args.knowledge_cutoff)
        payload = plan.to_dict()
        if args.apply:
            result = planner.apply(
                plan,
                seed_path=args.seed,
                output_path=args.output,
                apply_review_required=args.apply_review_required,
            )
            payload["apply_result"] = result.to_dict()
        if args.plan_output:
            plan_output = Path(args.plan_output)
            plan_output.parent.mkdir(parents=True, exist_ok=True)
            plan_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["plan_output"] = str(plan_output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "events":
        print(json.dumps(PredictionPipeline().list_events(), ensure_ascii=False, indent=2))
    elif args.command == "backtest":
        rows = [row.__dict__ for row in Backtester().run_seed_replay()]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.command == "replay-report":
        builder = ReplayCoverageBuilder()
        if args.write:
            path = builder.write(args.year, args.as_of)
            print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "analyze-replay":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = ReplayAnalysisBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "chronological-replay":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = ChronologicalReplayBundleBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(
                args.year,
                args.as_of,
                iterations=args.iterations,
                output_dir=args.output_dir,
                write_components=not args.no_components,
                write_freeze=not args.no_freeze,
            )
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of, iterations=args.iterations).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "formal-readiness":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = FormalReadinessBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "export-readiness-intake":
        pipeline = PredictionPipeline(iterations=args.iterations)
        bundle = ReadinessIntakeExporter(pipeline=pipeline).write(args.year, args.as_of, args.output_dir)
        print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "verify-readiness-intake":
        pipeline = PredictionPipeline(iterations=args.iterations)
        verifier = ReadinessIntakeVerifier(pipeline=pipeline)
        if args.write:
            paths = verifier.write(args.year, args.as_of, args.bundle_root)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(verifier.verify(args.year, args.as_of, args.bundle_root).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "scan-readiness-markets":
        scanner = ReadinessMarketScanner()
        if args.write:
            paths = scanner.write(
                year=args.year,
                as_of=args.as_of,
                output_dir=args.output_dir,
                bundle_root=args.bundle_root,
                limit=args.limit,
                market_type=args.market_type,
                include_closed=args.include_closed,
            )
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            report = scanner.scan(
                year=args.year,
                as_of=args.as_of,
                bundle_root=args.bundle_root,
                limit=args.limit,
                market_type=args.market_type,
                include_closed=args.include_closed,
            )
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "improvement-plan":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = ImprovementPlanBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "calibration-report":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = ReplayCalibrationBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "model-error-review":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = ModelErrorReviewBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "mvp-gate":
        builder = MVPGateBuilder()
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "mvp-completion-audit":
        builder = MVPCompletionAuditBuilder()
        if args.write:
            paths = builder.write(args.year, args.as_of, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "audit-track-assets":
        season = PredictionPipeline(iterations=1).data_source.load()
        auditor = TrackAssetAuditor()
        if args.write:
            path = auditor.write(args.year, season.events, args.output_dir)
            print(json.dumps({"json": str(path)}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(auditor.build(args.year, season.events).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "simulator-calibration":
        pipeline = PredictionPipeline(iterations=args.iterations)
        builder = SimulatorCalibrationBuilder(pipeline=pipeline)
        if args.write:
            paths = builder.write(args.year, args.as_of, iterations=args.iterations, output_dir=args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of, iterations=args.iterations).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "replay-freeze-manifest":
        builder = ReplayFreezeManifestBuilder()
        if args.write:
            paths = builder.write(args.year, args.as_of, args.iterations, args.output_dir)
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build(args.year, args.as_of, args.iterations).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-openf1":
        result = LiveIngestor().ingest_openf1_event(
            year=args.year,
            event_query=args.event_query,
            include_session_data=args.include_session_data,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-openf1-calendar":
        result = LiveIngestor().ingest_openf1_calendar(year=args.year)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-circuit-profiles":
        result = LiveIngestor().ingest_circuit_profiles(year=args.year, event_queries=args.event)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-weather-profiles":
        result = LiveIngestor().ingest_weather_profiles(
            year=args.year,
            event_queries=args.event,
            baseline_start_year=args.baseline_start_year,
            baseline_end_year=args.baseline_end_year,
            window_days=args.window_days,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-weather-forecast":
        result = LiveIngestor().ingest_weather_forecasts(
            year=args.year,
            event_queries=args.event,
            forecast_days=args.forecast_days,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-polymarket":
        result = LiveIngestor().ingest_polymarket_f1_events(limit=args.limit)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "normalize-polymarket":
        input_path = Path(args.input)
        season = PredictionPipeline(iterations=1).data_source.load()
        captured_at = args.captured_at or _raw_snapshot_captured_at(input_path)
        result = PolymarketGammaNormalizer(season).normalize_payload(
            _read_json(input_path),
            event_id=args.event,
            captured_at=captured_at,
            market_type=args.market_type,
            event_aliases=args.event_alias,
            include_closed=args.include_closed,
        )
        cutoff_dt = parse_dt(args.knowledge_cutoff)
        payload = result.to_dict()
        payload.update(
            {
                "input": str(input_path),
                "knowledge_cutoff": args.knowledge_cutoff,
                "cutoff_valid_snapshot_count": len(
                    event_market_snapshots(list(result.snapshots), args.event, cutoff_dt, market_type=args.market_type)
                ),
                "after_cutoff_snapshot_count": after_cutoff_market_count(
                    list(result.snapshots),
                    args.event,
                    cutoff_dt,
                    market_type=args.market_type,
                ),
                "archived_path": None,
            }
        )
        if args.write and result.snapshots:
            archived_path = MarketSnapshotStore(args.market_root).write_event_snapshots(
                args.event,
                list(result.snapshots),
                params={
                    "input": str(input_path),
                    "source": "polymarket_gamma",
                    "market_type": args.market_type,
                    "knowledge_cutoff": args.knowledge_cutoff,
                    "include_closed": args.include_closed,
                },
            )
            payload["archived_path"] = str(archived_path)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "discover-polymarket-markets":
        input_path = Path(args.input)
        season = PredictionPipeline(iterations=1).data_source.load()
        report = PolymarketDiscoveryAuditor(season).build(
            _read_json(input_path),
            market_type=args.market_type,
            include_closed=args.include_closed,
            event_ids=args.event,
        )
        payload = report.to_dict()
        payload["input"] = str(input_path)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "search-polymarket-season":
        season = PredictionPipeline(iterations=1).data_source.load()
        report = PolymarketSeasonSearchAuditor(season).build(
            limit=args.limit,
            market_type=args.market_type,
            include_closed=args.include_closed,
            event_ids=args.event,
        )
        payload = report.to_dict()
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "capture-polymarket-snapshot":
        season = PredictionPipeline(iterations=1).data_source.load()
        result = PolymarketLiveSnapshotter(season).capture_event(
            event_id=args.event,
            limit=args.limit,
            market_type=args.market_type,
            include_closed=args.include_closed,
            event_aliases=args.event_alias,
            captured_at=args.captured_at,
            wide_spread_threshold=args.wide_spread_threshold,
        )
        payload = result.to_dict()
        payload["archived_path"] = None
        if args.write and result.snapshots:
            archived_path = MarketSnapshotStore(args.market_root).write_event_snapshots(
                args.event,
                list(result.snapshots),
                params={
                    "source": "polymarket_live_orderbook",
                    "market_type": args.market_type,
                    "limit": args.limit,
                    "include_closed": args.include_closed,
                    "event_aliases": args.event_alias,
                    "wide_spread_threshold": args.wide_spread_threshold,
                    "quote_count": len(result.quotes),
                    "issue_count": len(result.issues),
                },
            )
            payload["archived_path"] = str(archived_path)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "backfill-polymarket-history":
        input_path = Path(args.input)
        season = PredictionPipeline(iterations=1).data_source.load()
        result = PolymarketPriceHistoryBackfiller(season).backfill_payload(
            _read_json(input_path),
            event_id=args.event,
            knowledge_cutoff=args.knowledge_cutoff,
            lookback_hours=args.lookback_hours,
            market_type=args.market_type,
            event_aliases=args.event_alias,
            include_closed=args.include_closed,
            fidelity_minutes=args.fidelity_minutes,
        )
        cutoff_dt = parse_dt(args.knowledge_cutoff)
        payload = result.to_dict()
        payload.update(
            {
                "input": str(input_path),
                "lookback_hours": args.lookback_hours,
                "fidelity_minutes": args.fidelity_minutes,
                "cutoff_valid_snapshot_count": len(
                    event_market_snapshots(list(result.snapshots), args.event, cutoff_dt, market_type=args.market_type)
                ),
                "after_cutoff_snapshot_count": after_cutoff_market_count(
                    list(result.snapshots),
                    args.event,
                    cutoff_dt,
                    market_type=args.market_type,
                ),
                "archived_path": None,
            }
        )
        if args.write and result.snapshots:
            archived_path = MarketSnapshotStore(args.market_root).write_event_snapshots(
                args.event,
                list(result.snapshots),
                params={
                    "input": str(input_path),
                    "source": "polymarket_price_history",
                    "market_type": args.market_type,
                    "knowledge_cutoff": args.knowledge_cutoff,
                    "lookback_hours": args.lookback_hours,
                    "include_closed": args.include_closed,
                },
            )
            payload["archived_path"] = str(archived_path)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "search-backfill-polymarket-history":
        season = PredictionPipeline(iterations=1).data_source.load()
        result = PolymarketSearchHistoryBackfiller(season).backfill_event(
            event_id=args.event,
            knowledge_cutoff=args.knowledge_cutoff,
            limit=args.limit,
            lookback_hours=args.lookback_hours,
            market_type=args.market_type,
            event_aliases=args.event_alias,
            include_closed=args.include_closed,
            fidelity_minutes=args.fidelity_minutes,
        )
        cutoff_dt = parse_dt(args.knowledge_cutoff)
        payload = result.to_dict()
        payload.update(
            {
                "cutoff_valid_snapshot_count": len(
                    event_market_snapshots(list(result.snapshots), args.event, cutoff_dt, market_type=args.market_type)
                ),
                "after_cutoff_snapshot_count": after_cutoff_market_count(
                    list(result.snapshots),
                    args.event,
                    cutoff_dt,
                    market_type=args.market_type,
                ),
                "archived_path": None,
                "search_output": None,
            }
        )
        if args.search_output:
            search_output_path = Path(args.search_output)
            search_output_path.parent.mkdir(parents=True, exist_ok=True)
            search_output_path.write_text(
                json.dumps(list(result.search_payload), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            payload["search_output"] = str(search_output_path)
        if args.write and result.snapshots:
            archived_path = MarketSnapshotStore(args.market_root).write_event_snapshots(
                args.event,
                list(result.snapshots),
                params={
                    "source": "polymarket_search_price_history",
                    "market_type": args.market_type,
                    "knowledge_cutoff": args.knowledge_cutoff,
                    "limit": args.limit,
                    "lookback_hours": args.lookback_hours,
                    "include_closed": args.include_closed,
                    "event_aliases": args.event_alias,
                    "query_count": len(result.queries),
                    "unique_market_count": result.unique_market_count,
                    "issue_count": len(result.issues),
                    "search_output": payload["search_output"],
                },
            )
            payload["archived_path"] = str(archived_path)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "archive-market-snapshot":
        store = MarketSnapshotStore(args.market_root)
        snapshots = store.validate_event_file(args.event, args.input)
        path = store.write_event_snapshots(
            args.event,
            snapshots,
            params={
                "input": args.input,
                "source": args.source,
                "knowledge_cutoff": args.knowledge_cutoff,
            },
        )
        cutoff_dt = parse_dt(args.knowledge_cutoff)
        payload = {
            "event_id": args.event,
            "snapshot_count": len(snapshots),
            "path": str(path),
            "cutoff_valid_snapshot_count": len(
                event_market_snapshots(snapshots, args.event, cutoff_dt)
            ),
            "after_cutoff_snapshot_count": after_cutoff_market_count(
                snapshots,
                args.event,
                cutoff_dt,
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "archive-reviewed-market-snapshot":
        season = PredictionPipeline(iterations=1).data_source.load()
        result = ReviewedMarketSnapshotArchiver(
            season=season,
            store=MarketSnapshotStore(args.market_root),
        ).archive_packet(
            event_id=args.event,
            input_path=args.input,
            knowledge_cutoff=args.knowledge_cutoff,
            require_cutoff_valid=args.require_cutoff_valid,
            write=not args.dry_run,
        )
        payload = result.to_dict()
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "reviewed-market-template":
        print(json.dumps(reviewed_market_template(args.event, args.market_type), ensure_ascii=False, indent=2))
    elif args.command == "ingest-fastf1-schedule":
        result = LiveIngestor().ingest_fastf1_schedule(year=args.year)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-fastf1-results":
        ingestor = LiveIngestor()
        if args.as_of:
            result = ingestor.ingest_fastf1_due_results(year=args.year, as_of=args.as_of, session=args.session)
        else:
            event = args.round if args.round is not None else args.event
            if event is None:
                raise ValueError("Provide --event, --round, or --as-of for ingest-fastf1-results")
            result = ingestor.ingest_fastf1_results(year=args.year, event=event, session=args.session)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-f1-official":
        result = LiveIngestor().ingest_f1_official_page(page=args.page, year=args.year)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "ingest-f1-race-profiles":
        result = LiveIngestor().ingest_f1_official_race_profiles(year=args.year, slugs=args.slug)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "summarize-openf1":
        builder = OpenF1SummaryBuilder()
        if args.write:
            path = builder.write_event_summary(args.year, args.event_query)
            print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        else:
            summary = builder.build_event_summary(args.year, args.event_query)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "build-calendar":
        builder = CalendarBuilder()
        if args.write:
            path = builder.write_openf1_calendar(args.year)
            print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(builder.build_from_openf1(args.year), ensure_ascii=False, indent=2))
    elif args.command == "validate-evidence":
        provider = CodexEvidenceProvider()
        if args.path:
            claims = provider.validate_event_file(args.event, args.path)
            payload = {"event_id": args.event, "path": args.path, "claim_count": len(claims)}
        else:
            claims = provider.load_event_evidence(args.event)
            payload = {"event_id": args.event, "claim_count": len(claims)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "ingest-evidence":
        provider = CodexEvidenceProvider()
        claims = provider.validate_event_file(args.event, args.input)
        if not claims:
            raise ValueError(f"No claims found in evidence input: {args.input}")
        if not args.source_log:
            raise ValueError("ingest-evidence requires --source-log so claims can be audited against source snapshots")
        audit = SourceLogAuditor().audit_claims(claims, args.source_log, args.knowledge_cutoff)
        if not audit.can_archive:
            raise ValueError(f"Evidence source audit failed: {json.dumps(audit.to_dict(), ensure_ascii=False)}")
        path = EvidencePacketStore(args.packet_root).write_event_packet(
            args.event,
            claims,
            source_log_path=args.source_log,
            params={"input": args.input, "source_audit": audit.to_dict()},
        )
        print(json.dumps({"event_id": args.event, "claim_count": len(claims), "path": str(path), "source_audit": audit.to_dict()}, ensure_ascii=False, indent=2))
    elif args.command == "archive-research-packet":
        result = CodexResearchPacketArchiver(
            research_root=args.research_root,
            packet_root=args.packet_root,
        ).archive_file(
            args.input,
            event_id=args.event,
            knowledge_cutoff=args.knowledge_cutoff,
            replace_draft=not args.append_draft,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "preflight-research-packet":
        result = CodexResearchPacketPreflight().preflight_file(
            args.input,
            event_id=args.event,
            knowledge_cutoff=args.knowledge_cutoff,
            source_candidate_report_path=args.source_candidate_report,
            source_candidates_input_path=args.source_candidates_input,
        )
        written = CodexResearchPacketPreflight.write_outputs(
            result,
            json_output=args.output,
            markdown_output=args.markdown_output,
        )
        payload = result.to_dict()
        if written:
            payload["written"] = written
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "codex-source-candidates":
        builder = CodexSourceCandidateBuilder()
        if args.input:
            report = builder.build_file(
                args.event,
                args.input,
                knowledge_cutoff=args.knowledge_cutoff,
            )
        else:
            report = builder.build(args.event, knowledge_cutoff=args.knowledge_cutoff)
        written = CodexSourceCandidateBuilder.write(
            report,
            json_output=args.output,
            markdown_output=args.markdown_output,
        )
        payload = report.to_dict()
        if written:
            payload["written"] = written
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "audit-evidence-sources":
        provider = CodexEvidenceProvider()
        claims = provider.validate_event_file(args.event, args.input)
        audit = SourceLogAuditor().audit_claims(claims, args.source_log, args.knowledge_cutoff)
        print(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "snapshot-source":
        historical_archive = None
        if args.historical_archive_url or args.historical_archived_at or args.historical_original_url:
            historical_archive = {
                "archive_url": args.historical_archive_url,
                "archived_at": args.historical_archived_at,
                "original_url": args.historical_original_url or args.url,
                "verified_at": args.observed_at or args.knowledge_cutoff,
                "verification_method": args.historical_verification_method or "manual_review",
                "notes": args.historical_notes,
            }
        result = SourceSnapshotter(research_root=args.research_root).snapshot_url(
            event_id=args.event,
            url=args.url,
            source=args.source,
            source_class=args.source_class,
            published_at=args.published_at,
            observed_at=args.observed_at,
            knowledge_cutoff=args.knowledge_cutoff,
            notes=args.notes,
            used_in_claim_ids=args.claim_id,
            historical_archive=historical_archive,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "discover-source-archives":
        report = SourceArchiveBackfiller(research_root=args.research_root).discover(
            event_ids=args.event,
            write=args.write,
            limit=args.limit,
        )
        payload = report.to_dict()
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["output"] = str(output_path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "source-replacement-candidates":
        builder = SourceReplacementCandidateBuilder()
        if args.write:
            paths = builder.write(
                input_path=args.input,
                event_ids=args.event,
                check_current=not args.no_current_check,
                check_archive=not args.no_archive_check,
                output_dir=args.output_dir,
            )
            print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, indent=2))
        else:
            report = builder.build(
                input_path=args.input,
                event_ids=args.event,
                check_current=not args.no_current_check,
                check_archive=not args.no_archive_check,
            )
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "apply-source-replacement":
        content_override = None
        if args.content_override:
            content_override = Path(args.content_override).read_text(encoding="utf-8")
        provider = CodexEvidenceProvider(evidence_dir=args.evidence_dir, packet_root=args.packet_root)
        result = SourceReplacementApplier(
            replacement_report_path=args.replacement_report,
            research_root=args.research_root,
            packet_root=args.packet_root,
            evidence_provider=provider,
        ).apply_candidate(
            args.candidate_id,
            content_override=content_override,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "research-brief":
        text = ResearchBriefBuilder().build(args.event)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(json.dumps({"path": args.output}, ensure_ascii=False, indent=2))
        else:
            print(text)
    elif args.command == "codex-research-plan":
        plan = CodexResearchPlanBuilder().build(
            args.event,
            knowledge_cutoff=args.knowledge_cutoff,
        )
        payload = plan.to_dict()
        written: dict[str, str] = {}
        if args.write:
            paths = CodexResearchPlanBuilder.write(plan, output_dir=args.output_dir)
            written.update({key: str(path) for key, path in paths.items()})
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            written["json"] = str(output_path)
        if args.markdown_output:
            markdown_path = Path(args.markdown_output)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(plan.to_markdown(), encoding="utf-8")
            written["markdown"] = str(markdown_path)
        if written:
            print(
                json.dumps(
                    {
                        "event_id": plan.event_id,
                        "status": plan.status,
                        "source_task_count": len(plan.source_tasks),
                        "paths": written,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "evidence-coverage":
        report = EvidenceCoverageAuditor().build(as_of=args.as_of)
        payload = report.to_dict()
        if args.write:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"path": str(path), **{k: payload[k] for k in payload if k != "rows"}}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "prepare-research":
        builder = CodexResearchWorkspaceBuilder()
        if args.as_of:
            paths = builder.write_due_workspaces(
                as_of=args.as_of,
                output_dir=args.output_dir,
                only_missing_evidence=not args.include_existing_evidence,
            )
        else:
            if args.event is None:
                raise ValueError("Provide --event or --as-of for prepare-research")
            paths = builder.write_event_workspace(
                event_id=args.event,
                knowledge_cutoff=args.knowledge_cutoff,
                output_dir=args.output_dir,
            )
        print(json.dumps({"paths": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    elif args.command == "build-information-intake":
        store = InformationIntakeStore(
            root=args.intake_root,
            research_root=args.research_root,
            reports_root=args.reports_root,
        )
        record = store.build(args.event, knowledge_cutoff=args.knowledge_cutoff)
        payload = record.to_dict()
        if args.write:
            path = store.write(record)
            payload["path"] = str(path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "register-prediction-run":
        record = PredictionRunRegistry(args.registry_root).register_packet(
            args.packet,
            information_intake_path=args.information_intake,
            notes=args.notes,
        )
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "diff-prediction-runs":
        differ = MatchedPredictionDiff(
            registry=PredictionRunRegistry(args.registry_root),
            output_dir=args.output_dir,
        )
        diff = differ.build(args.base_run, args.candidate_run)
        payload = diff.to_dict()
        if args.write:
            paths = differ.write(diff)
            payload["paths"] = {name: str(path) for name, path in paths.items()}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "features":
        pipeline = PredictionPipeline(iterations=1)
        season = pipeline.data_source.load()
        event = next((item for item in season.events if item.event_id == args.event), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {args.event}")
        adjustments = pipeline.feature_provider.load_event_features(season, event)
        print(json.dumps([item.__dict__ for item in adjustments], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
