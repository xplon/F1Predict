# MVP Status

Updated: 2026-07-03

## What Works Now

- Python package skeleton with clear module boundaries.
- Seed-data ingestion for season, teams, drivers, events, track maps, and market
  snapshots.
- Codex-normalized evidence protocol and JSONL evidence validator.
- Codex evidence-impact diagnostics in each prediction report: normalized
  claims are compared against a same-seed leave-one-claim counterfactual while
  structured data features and all other Codex evidence stay in place,
  producing target-scope probability deltas for audit/debugging without mixing
  other same-target claims into the selected claim's attribution.
- Normalized factor traces in each prediction report: each Codex claim is routed
  to a simulator surface such as track-contextual pace, tyre degradation,
  reliability, pit strategy, or wet-weather branching, with route status and
  same-seed probability movement. Traces now expose raw signed impact,
  quality-weighted input, and track-context-effective race/qualifying inputs so
  technical claims can be audited from source text to simulator surface. Track
  contextual rows also expose the demand component and profile behind the
  multiplier, such as ERS demand, power demand, drag demand, traction demand,
  launch importance, braking-energy demand, mass sensitivity, and altitude
  derate placeholders for future source-backed track features.
- Codex evidence-quality diagnostics in each prediction report: normalized
  claims are scored against source reliability, cutoff status, archive support,
  claim uncertainty, source triangulation, opposing-claim conflicts, review
  flags, and diagnostic model impact before the UI presents them as model
  inputs.
- Quality-derived Codex model-input weights are applied before simulation, so
  weak, seed-only, after-cutoff, or conflict-prone claims are downweighted
  rather than entering the pace model at full strength.
- Single-event prediction packet builder that writes an auditable JSON/Markdown
  artifact containing model probabilities, event-input provenance, Codex
  evidence quality, market context, blockers, warnings, and a payload hash.
- Codex evidence coverage auditor for replay rows.
- Codex research workspace generator that writes per-event research tasks,
  evidence templates, research packet templates, source logs, and non-loaded
  draft JSONL files.
- Codex research plan generator that writes a per-event source-quality and
  impact-rubric contract before web research. The plan enumerates source
  classes, search queries, acceptance and rejection rules, bounded impact bands,
  metric mapping, quality gates, and archive commands so Codex tool use is
  auditable instead of free-form.
- Codex source-candidate auditor for web-search/open outputs before claim
  drafting. It checks event-id consistency, source class reliability, linked
  research tasks, cutoff timestamps, URL validity, metric overlap, and
  relevance, then writes JSON/Markdown review reports under
  `reports/research_candidates/`. Candidate rows preview simulator routes,
  model surfaces, event-specific technical context multipliers, and impact-band
  guidance without auto-selecting claim direction or magnitude.
- Research-packet preflight now cross-checks packet source URLs against the
  source-candidate audit when available. Sources that bypass candidate review,
  map to blocked candidates, or come from the wrong event become blocking
  `source_candidate_*` findings before archive.
- Research-packet preflight also applies a shared factor contract: each
  simulator metric declares accepted target types, accepted claim types, route,
  model surface, and technical mechanism, and mismatches become blocking
  `factor_contract_*` findings before archive.
- Research-packet preflight now detects unfilled `REPLACE_WITH_*` templates and
  returns `research_packet_template_unfilled` instead of routing placeholder
  rows as unsupported real claims. The frontend loads source-candidate and
  preflight panels independently from slower prediction-packet generation, so
  Codex intake state is visible even before a full audit packet finishes.
- File-based research-packet preflight now reuses the adjacent real
  `source_log.json` before falling back to a synthetic preflight log, so
  cutoff-valid local source snapshots keep their true source status and model
  input weight during the pre-archive check.
- Codex source snapshot registry that archives inspected URLs into
  `data/raw/research_sources/` and appends source audit records with reliability
  and cutoff status.
- Codex research packet archiver for the preferred LLM handoff path: one
  sources+claims manifest is converted into snapshots, draft JSONL, source
  audits, and an archived evidence packet.
- Append-only Codex evidence packet store under `data/evidence/<event_id>/packets/`.
- Source audit gate for `ingest-evidence`: every archived claim must link to a
  source snapshot, list the claim id in `used_in_claim_ids`, and pass the
  point-in-time cutoff and snapshot-capture timestamp checks.
- Historical archive source proof: late local source snapshots can carry a
  `historical_archive` object with archive URL, archived timestamp, original
  URL, verification timestamp, and verification method. Coverage reports these
  separately from retrospective snapshots.
- URL-level source snapshot diagnostics: coverage and replay analysis now list
  the exact retrospective source URLs, capture times, and archive status for
  each replay row.
- Wayback archive discovery command that dry-runs or writes cutoff-valid archive
  proofs for retrospective local source snapshots through the availability API
  plus a CDX fallback, and records a reviewable report under
  `reports/source_archives/`.
- Retrospective source snapshot warnings: source snapshots captured after a
  replay cutoff are allowed for diagnostic backfill but block formal replay
  claims until replaced with frozen point-in-time captures or verifiable
  archived sources.
- Retrospective F1 official qualifying/practice evidence packets for all eight
  completed replay races as of `2026-06-30T00:00:00+00:00`.
- First archived source-backed evidence packet for `british_gp`: an Open-Meteo
  Silverstone forecast snapshot linked to an event-level weather claim.
- Simple pace model using team, driver, track, weather, and Codex evidence.
- Strategy-aware compact Monte Carlo single-race simulator using race-time
  sampling with grid position, tyre degradation, pit-loss, weather,
  safety-car, and reliability proxies.
- Cutoff-aware season forecast: completed races before the cutoff seed driver
  points from stored FastF1 `Points` fields when available, falling back to
  classified order only when points are missing. Remaining races are simulated
  through the same strategy-aware event sampling boundary used by single-race
  prediction, with event-specific Codex evidence and processed features
  available at that cutoff.
- Market gap analysis for winner markets.
- Market edge rows expose both raw model probability and conservative
  calibration-shrunk probability; paper recommendations are based on
  conservative edge after costs and carry risk flags when calibration downgrades
  a raw gap.
- Market snapshots are filtered by `captured_at <= knowledge_cutoff` before
  entering prediction, replay, coverage, or edge comparison.
- After-cutoff market snapshots are reported separately so replay diagnostics do
  not accidentally use prices from after the prediction time.
- URL/time-level market snapshot diagnostics: coverage and replay analysis now
  list cutoff-valid snapshots, excluded after-cutoff snapshots, and the required
  winner-market cutoff for missing events.
- Append-only normalized market snapshot store under
  `data/market_snapshots/<event_id>/snapshots/`, with validation and CLI
  archival via `archive-market-snapshot`.
- Point-in-time diagnostic replay harness.
- Raw point-in-time snapshot storage.
- Real OpenF1 ingestion for meeting/session/laps/weather/race-control/stints.
- Real OpenF1 yearly meeting snapshots and normalized 2026 calendar.
- Real Polymarket F1-tag event snapshot ingestion.
- Conservative Polymarket Gamma normalizer that parses Yes/No driver markets
  into `MarketSnapshot` rows only when event, season, and driver are
  unambiguous; mismatched seasons and ambiguous outcomes become review issues.
- Polymarket CLOB price-history backfill command that uses reviewed Gamma
  market definitions and writes cutoff-valid `MarketSnapshot` rows only when a
  price point exists at or before the requested knowledge cutoff.
- Polymarket discovery auditor that scans one Gamma payload against every
  season event and reports which events have market definitions, snapshots, and
  review issues before any price-history backfill is attempted.
- Polymarket public-search season auditor that queries by race name, preserves
  event context from search results, deduplicates candidate markets, and reports
  rejected candidates before any market snapshot is archived.
- Polymarket live snapshotter that searches event-name markets, queries CLOB
  order books for matched driver token ids, computes quote-status-aware prices
  (`book_midpoint`, `book_last_trade_wide_spread`, or explicit Gamma fallback),
  and can archive same-time snapshots for future prediction cutoffs.
- FastF1 schedule snapshot ingestion through a project `.venv`.
- FastF1 completed-race result snapshot ingestion through the same `.venv`.
- FastF1 result repository defaults to Race-session results only, with explicit
  session filtering available for Sprint data, so future Sprint snapshots cannot
  silently override canonical race replay labels or season-forecast base points.
- Calendar-augmented season data source that creates missing race events from
  OpenF1 calendar snapshots and canonicalizes completed race results from
  FastF1.
- F1 official calendar/drivers/teams raw page snapshots.
- F1 official driver/team standings parser that extracts Formula1.com results
  tables from stored Next.js/React Flight HTML snapshots into structured
  driver and team standings rows.
- Official standings roster audit that keeps Formula1.com standings out of
  season base points when the project seed roster is not aligned with the
  official standings or when the snapshot was captured after the forecast
  cutoff. The latest stored 2026 standings now align with the seed roster and
  can seed current/no-cutoff forecasts.
- Official standings roster sync planner that converts future standings drift
  into an audited seed update plan. Source-backed points and team corrections
  can be applied automatically; new drivers or teams remain review-required
  because they introduce model-prior assumptions.
- F1 official race profile snapshots for non-cancelled 2026 races; planned lap
  counts now enter generated event rows as verified field-level provenance.
- Open-Meteo historical climate profile snapshots for non-cancelled 2026 races;
  generated weather priors are derived from 2016-2025 same-week precipitation
  records instead of static event-name heuristics.
- Open-Meteo race-week forecast ingestion and cutoff-aware
  `WeatherForecastProvider`: future events can use stored forecast snapshots
  captured before the prediction cutoff, while older cutoffs keep using only
  information that was available at that time.
- Processed OpenF1 event summaries from raw snapshots.
- Processed OpenF1 summaries now enter the pace model as low-confidence feature
  adjustments with point-in-time cutoff filtering.
- FastF1 previous-results form features now enter the pace model as
  point-in-time driver/team race pace, qualifying pace, and reliability priors.
- Chronological replay coverage report showing cancelled events, due races,
  diagnostic replay coverage, FastF1 result availability, generated prediction
  inputs, Codex evidence coverage, market-snapshot coverage, and source
  provenance such as OpenF1 calendar rounds versus FastF1 race sequence.
- Replay coverage now keeps raw calendar rounds separate from the
  cancellation-aware non-cancelled race sequence, so expected shifts after
  cancelled events are preserved as provenance rather than promoted to mismatch
  issues.
- Chronological replay analysis report showing diagnostic hit rate,
  actual-winner probability/rank, formal-backtest blockers, per-event issue
  codes, and prioritized next actions.
- Chronological replay bundle that runs the ordered replay report, analysis,
  formal readiness, calibration, improvement plan, and replay freeze from one
  command, then writes a single JSON/Markdown audit artifact for first-race to
  cutoff review.
- Replay analysis root-cause diagnosis that groups event-level issues into
  project-level market data gaps, source time-integrity gaps, model
  calibration gaps, seed-label provenance, and feature-horizon boundaries.
- Formal replay readiness manifest that converts replay blockers into
  workstream batches plus a per-event intake queue with required cutoffs,
  success criteria, and command templates for market backfill, after-cutoff
  market replacement, source archive proof, and calibration review.
- Replay calibration diagnostics for probability quality: top-pick confidence
  bins, winner Brier score, actual-winner log loss, market-scored subset size,
  and explicit small-sample warnings.
- Simulator calibration diagnostics compare hand-curated simulator parameter
  candidates against replay rows and rank review candidates by log loss, Brier,
  calibration gap, hit rate, and actual-winner probability while explicitly
  staying diagnostic-only because the ranking is in-sample and small-sample.
- Replay freeze manifest that fingerprints source code, frontend assets, input
  data, and generated diagnostic reports, while preserving whether the current
  replay is formal-ready or still diagnostic-only.
- Improvement plan report that combines formal readiness blockers,
  market-readiness search results, remaining source archive blockers, and
  replay calibration diagnostics into prioritized workstreams with owners,
  success criteria, commands, and formal-edge gating status.
- MVP delivery gate report that maps the original project requirements to
  current evidence, status, delivery blockers, formal-edge blockers, artifact
  references, and next actions.
  The gate treats `mvp_delivery_ready` as the diagnostic MVP delivery claim:
  data acquisition, Codex normalization, simulation, replay diagnostics, market
  gap inspection, and frontend review are runnable end-to-end. Source archive
  proof, complete same-time market snapshots, and matched calibration remain
  formal-edge blockers rather than diagnostic MVP delivery blockers.
- MVP completion audit that turns the original goal into explicit completion
  rows for architecture, Codex normalization, news-to-factor routing, simulation
  probabilities, market-gap analysis, chronological replay, frontend inspection,
  Codex factor-impact diagnostics, and verification. Its current expected
  status is `mvp_complete_formal_edge_not_ready`, so it records the MVP as
  complete while keeping stable-edge proof formally blocked.
- Readiness intake bundle export that writes per-workstream JSONL/CSV queues
  for market backfill, source archive proof, after-cutoff market replacement,
  and calibration review.
- Readiness intake verification that compares an exported queue against the
  current readiness state and marks each row as open, resolved, or newly
  changed before the replay state is frozen.
- Readiness market candidate scanning that reads market-related intake rows,
  searches Polymarket by blocked event, and reports whether candidate market
  definitions exist before manual price-history backfill.
- Local JSON API and static frontend.
- Frontend views:
  - archived F1 official track maps for every loaded 2026 event, with local
    asset provenance and source-backed geometry fallback
  - interactive selected simulation replay with lap scrub/playback, current-lap
    ranking cards, schematic track markers, and lap-by-lap position, gap, tyre,
    pit, weather, safety-car, reliability, and DNF trace fields
  - model probabilities
  - official standings roster audit and top standings rows
  - replay root-cause cards with diagnosis, evidence, and improvement actions
  - chronological replay bundle summary with full-calendar coverage, blocker
    counts, calibration status, top root cause, and next project actions
  - chronological replay diagnostics timeline with raw round, race sequence,
    hit/miss, source state, market state, and per-event blockers
  - formal readiness workstreams and input queue
  - replay calibration summary and top-pick confidence bins
  - simulator calibration candidate ranking with parameter-review warnings
  - replay freeze manifest status, artifact hashes, and integrity flags
  - market readiness candidate scans for unresolved market blockers
  - source readiness archive-proof scans for unresolved source blockers
  - improvement plan workstreams that separate formal-edge blockers from
    diagnostic model-iteration tasks
  - prediction packet audit summary with readiness status, market context,
    Codex quality counts, blockers, warnings, and payload hash
  - research packet preflight panel showing source-link/schema blockers,
    conflict status, factor-contract mismatches, model input weights, and
    simulator route preview before evidence archive
  - market differences
  - Codex judgement
  - Codex research plan with source tasks, acceptance/rejection rules, impact
    bands, and quality gates
  - source-candidate audit panel showing Codex search/open candidate status,
    blocked source rows, task links, cutoff status, risk flags, and next actions
    before research-packet claim preflight, plus route previews from candidate
    metric to simulator surface
  - Codex evidence-impact sensitivity cards
  - normalized evidence cards

## Verified Commands

```powershell
$env:PYTHONPATH = "src"
python scripts\smoke_test.py
python -m f1predict.cli predict --event british_gp --iterations 800
python -m f1predict.cli backtest
python -m f1predict.cli predict --event miami_gp --iterations 500
python -m f1predict.cli validate-evidence --event british_gp
python -m f1predict.cli research-brief --event british_gp
python -m f1predict.cli codex-research-plan --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --write
python -m f1predict.cli evidence-coverage --as-of 2026-06-30T00:00:00+00:00 --write --output reports\evidence_coverage_20260630.json
python -m f1predict.cli prepare-research --as-of 2026-06-30T00:00:00+00:00 --output-dir data\research
python -m f1predict.cli codex-source-candidates --event miami_gp --input data\research\miami_gp\source_candidates.json --knowledge-cutoff 2026-05-03T00:00:00+00:00 --output reports\research_candidates\miami_gp.json --markdown-output reports\research_candidates\miami_gp.md
python -m f1predict.cli preflight-research-packet --input data\research\miami_gp\research_packet_template.json --event miami_gp --knowledge-cutoff 2026-05-03T00:00:00+00:00 --source-candidate-report reports\research_candidates\miami_gp.json --output reports\research_preflight\miami_gp.json --markdown-output reports\research_preflight\miami_gp.md
python -m f1predict.cli snapshot-source --event miami_gp --url <url> --source <name> --source-class media --published-at <iso> --knowledge-cutoff 2026-05-03T00:00:00+00:00 --claim-id miami_gp-codex-001
python -m f1predict.cli snapshot-source --event miami_gp --url <url> --source <name> --source-class media --published-at <iso> --observed-at <iso-before-cutoff> --knowledge-cutoff 2026-05-03T00:00:00+00:00 --claim-id miami_gp-codex-001 --historical-archive-url <archive-url> --historical-archived-at <iso-before-cutoff> --historical-original-url <url> --historical-verification-method wayback
python -m f1predict.cli discover-source-archives --output reports\source_archives\wayback_discovery_20260630.json
python -m f1predict.cli discover-source-archives --write --output reports\source_archives\wayback_discovery_20260630.write.json
python -m f1predict.cli validate-evidence --event miami_gp --path data\research\miami_gp\draft_evidence.jsonl
python -m f1predict.cli audit-evidence-sources --event miami_gp --input data\research\miami_gp\draft_evidence.jsonl --source-log data\research\miami_gp\source_log.json --knowledge-cutoff 2026-05-03T00:00:00+00:00
python -m f1predict.cli validate-evidence --event british_gp
python -m f1predict.cli prediction-packet --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --iterations 1200 --write
python -m f1predict.cli ingest-openf1-calendar --year 2026
python -m f1predict.cli ingest-openf1 --year 2024 --event-query Silverstone --include-session-data
python -m f1predict.cli summarize-openf1 --year 2024 --event-query Silverstone --write
python -m f1predict.cli ingest-fastf1-schedule --year 2026
python -m f1predict.cli ingest-fastf1-results --year 2026 --as-of 2026-06-30T00:00:00+00:00
python -m f1predict.cli ingest-f1-official --year 2026 --page calendar
python -m f1predict.cli ingest-f1-official --year 2026 --page drivers
python -m f1predict.cli ingest-f1-official --year 2026 --page teams
python -m f1predict.cli build-official-standings --year 2026 --write
python -m f1predict.cli ingest-f1-race-profiles --year 2026
python -m f1predict.cli ingest-weather-profiles --year 2026 --baseline-start-year 2016 --baseline-end-year 2025 --window-days 3
python -m f1predict.cli season-forecast --knowledge-cutoff 2026-06-30T00:00:00+00:00 --iterations 1200 --output reports\season_forecast\2026_asof_20260630T000000_0000.json
python -m f1predict.cli ingest-polymarket --limit 5
python -m f1predict.cli ingest-polymarket --limit 50
python -m f1predict.cli discover-polymarket-markets --input data\raw\polymarket\f1_events\2026-06-30\f1_events_2026-06-30T10_32_31_00_00.json --include-closed --output reports\market_normalization\f1_events_20260630T103231.discovery.json
python -m f1predict.cli search-polymarket-season --limit 15 --include-closed --output reports\market_normalization\f1_events_20260630T103231.season_search.json
python -m f1predict.cli capture-polymarket-snapshot --event british_gp --limit 15 --output reports\market_normalization\british_gp_live_snapshot.json
python -m f1predict.cli capture-polymarket-snapshot --event british_gp --limit 15 --write
python -m f1predict.cli normalize-polymarket --event italian_gp --input data\raw\polymarket\f1_events\2026-06-30\f1_events_2026-06-30T07_20_09_00_00.json --knowledge-cutoff 2026-09-01T00:00:00+00:00 --include-closed
python -m f1predict.cli backfill-polymarket-history --event italian_gp --input data\raw\polymarket\f1_events\2026-06-30\f1_events_2026-06-30T07_20_09_00_00.json --knowledge-cutoff 2026-09-01T00:00:00+00:00 --include-closed --output reports\market_normalization\italian_gp_raw_20260630.price_history_backfill.json
python -m f1predict.cli archive-market-snapshot --event miami_gp --input <normalized_market_snapshot.jsonl> --knowledge-cutoff 2026-05-03T00:00:00+00:00
python -m f1predict.cli build-calendar --year 2026 --write
python -m f1predict.cli replay-report --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
python -m f1predict.cli analyze-replay --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
python -m f1predict.cli chronological-replay --year 2026 --as-of 2026-06-30T00:00:00+00:00 --iterations 1200 --write
python -m f1predict.cli formal-readiness --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
python -m f1predict.cli export-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00
python -m f1predict.cli verify-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
python -m f1predict.cli scan-readiness-markets --year 2026 --as-of 2026-06-30T00:00:00+00:00 --limit 30 --include-closed --write
python -m f1predict.cli calibration-report --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
python -m f1predict.cli simulator-calibration --year 2026 --as-of 2026-06-30T00:00:00+00:00 --iterations 800 --write
python -m f1predict.cli improvement-plan --year 2026 --as-of 2026-06-30T00:00:00+00:00 --iterations 800 --write
python -m f1predict.cli replay-freeze-manifest --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
python -m compileall src scripts
```

`scripts\smoke_test.py` also verifies the batch
`archive-research-packet` plumbing with an offline source fixture.

Replay coverage as of `2026-06-30T00:00:00+00:00`:

```text
calendar_events: 24
cancelled_events: 2
due_events: 8
replayed_events: 8
result_available_events: 8
missing_due_events: 0
```

Interpretation: diagnostic replay now spans every non-cancelled race completed
by the cutoff. Three replay rows use seed event inputs with FastF1-canonicalized
results; five rows use OpenF1-calendar-generated event inputs with FastF1 race
results. Generated rows now expose field-level provenance: OpenF1 calendar,
FastF1 result fields, and stored Multiviewer circuit geometry are verified
where available. The completed generated rows no longer use placeholder track
maps, and track-type clusters are now derived from stored circuit geometry.

Latest generated replay state as of `2026-07-01T00:00:00+00:00`:

```text
chronological_replay: diagnostic_only
due_events: 8
replayed_events: 8
formal_readiness: inputs_required
blocking_actions: 12
market_readiness_actions: 9
freeze_status: diagnostic_freeze_inputs_required
```

The local API and frontend now resolve omitted replay `as_of` parameters to the
latest generated disk snapshot, so the default dashboard view reads the
`2026_asof_20260701T000000_0000` reports. Explicit `as_of` still selects a
reproducible historical snapshot; `live=1` intentionally recomputes supported
analysis/readiness/calibration/freeze endpoints.
F1 official race profile snapshots now verify planned lap counts. Open-Meteo
historical climate profiles now derive generated weather priors from pre-season
baseline years; these are source-backed climate priors, not race-week forecasts.
Replay rows now expose both raw calendar round and race sequence; current
OpenF1/FastF1 round shifts after the two cancelled events are expected sequence
provenance, not active mismatch issues.
This is useful for failure-mode discovery, but it is not yet a formal matched
backtest because three source rows remain retrospective and seven rows still
lack historical market snapshots.

Codex evidence coverage as of the same cutoff:

```text
completed_event_count: 8
events_with_evidence: 8
events_with_evidence_impact: 8
events_with_evidence_quality: 8
events_with_weak_evidence_quality: 3
events_with_strong_evidence_quality: 0
max_evidence_win_delta: 0.03
events_with_source_snapshots: 8
events_with_retrospective_source_snapshots: 3
events_with_archive_backed_source_snapshots: 5
events_with_market_snapshots: 1
events_with_market_snapshots_after_cutoff: 2
events_needing_codex_research: 0
```

Replay analysis as of the same cutoff:

```text
status: diagnostic_only
formal_backtest_ready: false
diagnostic_scored_events: 8
top_pick_hits: 3
top_pick_hit_rate: 0.375
median_actual_winner_rank: 2
events_with_evidence_impact: 8
events_with_evidence_quality: 8
events_with_weak_evidence_quality: 3
events_with_strong_evidence_quality: 0
max_evidence_win_delta: 0.015
input_quality_breakdown:
  - seed_with_fastf1_result: 3 scored events
  - generated_verified: 5 scored events
critical_blockers:
  - missing_market_snapshot: 7 events
high_blockers:
  - retrospective_source_snapshots: 3 events
  - market_snapshot_after_cutoff: 2 events
nonblocking_provenance:
  - top_pick_miss: 5 events
  - seed_result_overridden_by_fastf1: 3 events
  - season_opener_no_prior_form: 1 event
root_causes:
  - market_data_gap: 7 events, blocks formal edge claims
  - source_time_integrity_gap: 3 events, blocks formal Codex replay claims
  - model_ranking_calibration_gap: 5 events, diagnostic model issue
  - seed_label_provenance_gap: 3 events, nonblocking provenance
  - feature_horizon_boundary: 1 event, nonblocking opener limitation
```

Generated replay analysis reports:

```text
reports/replay_analysis/2026_asof_20260630T000000_0000.analysis.json
reports/replay_analysis/2026_asof_20260630T000000_0000.analysis.md
```

Generated chronological replay bundle:

```text
reports/chronological_replay/2026_asof_20260630T000000_0000.chronological_replay.json
reports/chronological_replay/2026_asof_20260630T000000_0000.chronological_replay.md
status: diagnostic_only
formal_edge_ready: false
calendar_events: 24
due_events: 8
replayed_events: 8
diagnostic_top_pick_hit_rate: 0.375
blocking_action_count: 12
market_snapshot_required: 7
source_archive_required: 3
top_priority: Backfill Same-Time Market Snapshots
next_actions:
  - P1 Backfill Same-Time Market Snapshots: blocked_no_usable_market_definitions
  - P2 Replace or Prove Retrospective Sources: replacement_sources_required
  - P3 Regenerate Formal Replay Freeze: blocked_by_input_readiness
```

Generated formal readiness reports:

```text
reports/formal_readiness/2026_asof_20260630T000000_0000.readiness.json
reports/formal_readiness/2026_asof_20260630T000000_0000.readiness.md
status: inputs_required
formal_backtest_ready: false
blocking_action_count: 12
warning_action_count: 5
market_snapshot_required: 7
after_cutoff_market_replacement: 2
source_archive_required: 3
model_calibration_review: 5
```

Generated readiness intake bundle:

```text
reports/readiness_intake/2026_asof_20260630T000000_0000/README.md
reports/readiness_intake/2026_asof_20260630T000000_0000/intake_manifest.json
reports/readiness_intake/2026_asof_20260630T000000_0000/actions.jsonl
reports/readiness_intake/2026_asof_20260630T000000_0000/workstreams.csv
action_count: 17
market_snapshot_backfill: 7 actions
after_cutoff_market_replacement: 2 actions
source_archive_proof: 3 actions
model_calibration_review: 5 actions
```

Generated readiness intake verification reports:

```text
reports/readiness_intake/2026_asof_20260630T000000_0000/verification.json
reports/readiness_intake/2026_asof_20260630T000000_0000/verification.csv
status: open_actions_remaining
queued_action_count: 17
open_action_count: 17
resolved_action_count: 0
new_action_count: 0
open_blocking_action_count: 12
open_warning_action_count: 5
```

Generated readiness market scan reports:

```text
reports/market_readiness/2026_asof_20260630T000000_0000.market_readiness.json
reports/market_readiness/2026_asof_20260630T000000_0000.market_readiness.csv
status: search_results_need_review
action_count: 9
event_count: 7
query_count: 40
total_search_results: 2754
events_with_search_results: 7
events_with_unique_markets: 7
events_with_snapshots: 0
events_with_definitions: 0
unresolved_event_count: 7
issue_counts:
  - season_mismatch: 443
  - unsupported_market_type: 12
```

Generated improvement plan reports:

```text
reports/improvement_plan/2026_asof_20260630T000000_0000.improvement_plan.json
reports/improvement_plan/2026_asof_20260630T000000_0000.improvement_plan.md
status: inputs_required
formal_edge_ready: false
top_priority: Backfill Same-Time Market Snapshots
blocking_workstream_count: 3
diagnostic_workstream_count: 2
workstreams:
  - P1 Backfill Same-Time Market Snapshots: blocks formal edge claims
  - P2 Replace or Prove Retrospective Sources: blocks formal edge claims
  - P3 Regenerate Formal Replay Freeze: blocks formal edge claims
  - P4 Recalibrate Probabilities After Input Fixes: diagnostic follow-up
  - P5 Review Misses and Model Assumptions: diagnostic follow-up
```

Generated replay calibration reports:

```text
reports/calibration/2026_asof_20260630T000000_0000.calibration.json
reports/calibration/2026_asof_20260630T000000_0000.calibration.md
status: diagnostic_only
formal_probability_claim_ready: false
scored_events: 8
market_scored_events: 1
top_pick_hit_rate: 0.375
mean_top_pick_probability: 0.3349
mean_actual_winner_probability: 0.2624
mean_winner_brier_score: 0.7182
mean_actual_log_loss: 1.4048
weighted_top_pick_calibration_gap: 0.1068
warnings: diagnostic_only, small_sample_less_than_20_scored_events, market_scored_subset_incomplete
market_edge_policy: conservative_calibration_shrinkage
```

Generated replay freeze manifest:

```text
reports/replay_freeze/2026_asof_20260630T000000_0000.freeze.json
reports/replay_freeze/2026_asof_20260630T000000_0000.freeze.md
status: diagnostic_freeze_inputs_required
manifest_payload_sha256: 0678dc930409aa51cc6982fd1870434067443cccc5f206c3aa86bc556c956fa9
source_code_files: 51
frontend_files: 3
input_data_files: 318
diagnostic_report_files: 32
integrity_flags: formal_edge_claim_not_ready, probability_calibration_diagnostic_only, readiness_blockers:12
```

Generated season forecast report:

```text
reports/season_forecast/2026_asof_20260630T000000_0000.json
status: diagnostic_only
completed_events_counted: 8
remaining_events_simulated: 14
base_points_source: fastf1_result_points_before_cutoff
event_sampling_model: strategy_aware_race_time_sampler
base_points_event_sources: fastf1_points=8, classified_order_fallback=0
top_expected_final_points: antonelli 397.41
top_champion_probability: antonelli 93.50%
next_champion_probabilities: russell 4.92%, hamilton 1.50%, verstappen 0.08%
```

The current season forecast is useful for MVP display and model-regression
tracking. It is not a formal standings model yet because only available stored
FastF1 race result points are counted at the `2026-06-30T00:00:00+00:00`
cutoff. Stored Formula1.com standings were captured later that same day and
therefore cannot seed that replay cutoff. The latest parsed Formula1.com
standings now align with the current project seed roster and can seed
current/no-cutoff forecasts; they remain cutoff-gated for historical replay.
The remaining-race sampler now shares the strategy-aware race-time model used
by single-race prediction. The latest variance-calibrated sampler no longer
collapses the season forecast to a 100% Antonelli title path, but it still needs
historical lap/stint calibration before it can support formal
season-probability claims.

Generated official standings audit:

```text
data/processed/f1_official_standings/2026_standings/2026-06-30/2026_standings_2026-06-30T18_05_52_00_00.json
source_captured_at: 2026-06-30T07:44:26+00:00
driver_row_count: 22
team_row_count: 11
matched_driver_count: 22
roster_status: aligned
can_seed_season_points: true
unmatched_official_drivers: []
unmatched_project_drivers: []
team_mismatch_drivers: []
```

Generated official roster sync plan:

```text
reports/official_roster_sync/2026_latest.json
source_captured_at: 2026-06-30T07:44:26+00:00
current_roster_status: aligned
status: no_changes
operation_count: 0
auto_apply_count: 0
review_required_count: 0
```

Research workspace files were generated under `data/research/<event_id>/` for
all eight completed races. Each workspace contains a deterministic task brief,
a machine-readable and human-readable Codex research plan, an evidence
template, a batch research packet template, a source log skeleton, and a
non-loaded `draft_evidence.jsonl`. Filled research packets can be archived with
`archive-research-packet` after `preflight-research-packet` checks schema,
source links, conflicts, factor-contract compatibility, quality-derived input
weights, and simulator factor routes. Manually validated drafts can still be
archived with `ingest-evidence`.
Both archive paths write into `data/evidence/<event_id>/packets/`, which the
prediction pipeline reads alongside legacy seed evidence.

Completed-race diagnostic evidence status:

```text
events_with_evidence: 8
events_with_source_snapshots: 8
retrospective_source_snapshots: 3
archive_backed_source_snapshots: 5
archived_completed_race_claims: 8
source_class: f1_official
```

These completed-race packets are useful for exercising the Codex evidence
pipeline and replay diagnostics. Five late local source snapshots now have
Wayback availability proof at or before their replay cutoff; three still lack a
cutoff-valid archive proof and remain formal replay blockers. The unresolved
rows are the Formula1.com race-week report sources for `miami_gp`,
`canadian_gp`, and `barcelona_gp`; replay analysis now exposes their URLs under
`retrospective_source_details`.

The unresolved source blockers were rechecked with the enhanced availability +
CDX discovery path. The recheck found no cutoff-valid archive candidates, so
these rows still require a replacement pre-cutoff source or an independently
verified historical archive proof.

Wayback archive discovery status:

```text
source_logs_scanned: 9
sources_scanned: 9
archive_candidates_written: 5
no_archive_before_cutoff: 3
not_retrospective: 1
reports/source_archives/wayback_discovery_20260630.write.json
```

Remaining source blocker CDX recheck:

```text
reports/source_archives/remaining_blockers_cdx_discovery.json
source_logs_scanned: 3
sources_scanned: 3
candidate_count: 0
status_counts:
  - no_archive_before_cutoff: 3
events: barcelona_gp, canadian_gp, miami_gp
```

Circuit, race, and weather profile status:

```text
ingest-circuit-profiles --year 2026
profiles_archived: 23
failures:
  - Spanish Grand Prix circuit profile URL returned 404
archived_f1_official_track_assets: 24
loaded_non_cancelled_events_with_track_assets: 22
loaded_non_cancelled_events_with_verified_track_map_geometry: 22
spanish_gp_geometry_fallback: derived_f1_official_track_icon
completed_generated_rows_with_verified_track_map: 5
completed_generated_rows_with_derived_track_type: 5
ingest-f1-race-profiles --year 2026
race_profiles_archived: 22
non_cancelled_season_rows_with_verified_laps: 22
completed_generated_rows_with_verified_laps: 5
ingest-weather-profiles --year 2026 --baseline-start-year 2016 --baseline-end-year 2025 --window-days 3
weather_profiles_archived: 22
completed_generated_rows_with_derived_weather_prior: 5
remaining_completed_generated_profile_heuristics: none
```

Market replay status:

```text
events_with_cutoff_valid_market_snapshots: 1
events_with_after_cutoff_market_snapshots: 2
events_missing_cutoff_valid_market_snapshots: 7
cutoff_valid_market_rows:
  - australian_gp: seed_australian_gp_winner captured 2026-03-07T12:00:00Z
after_cutoff_market_rows_excluded:
  - chinese_gp: seed_chinese_gp_winner captured 2026-03-21T12:00:00Z, cutoff 2026-03-15T00:00:00+00:00
  - japanese_gp: seed_japanese_gp_winner captured 2026-04-04T12:00:00Z, cutoff 2026-03-29T00:00:00+00:00
missing_cutoff_valid_market_rows:
  - miami_gp
  - canadian_gp
  - monaco_gp
  - barcelona_gp
  - austrian_gp
```

The seed Chinese and Japanese market rows are now excluded from replay edge
comparison because their `captured_at` timestamps are after the race cutoffs.
The current stored Polymarket raw fixture contains 2024 race markets; the
normalizer now rejects those rows for the 2026 replay with `season_mismatch`
instead of silently mapping them onto same-name 2026 events.
The price-history backfill report for that fixture likewise produces zero
definitions and zero snapshots, confirming those raw rows are not eligible for
2026 replay.
The latest 50-event Polymarket F1-tag snapshot on 2026-06-30 contains 702
market rows. Discovery found zero 2026 season event definitions and zero
snapshots; 501 event-name matches were rejected as `season_mismatch` because
they refer to 2024 or 2025 markets.
The Polymarket public-search season audit on the same date queried 129
race-name variants and inspected 12,457 returned market rows, deduplicated to
6,900 candidate markets. It found zero 2026 winner definitions and zero
snapshots. Rejection counts were `season_mismatch: 2544`,
`unsupported_market_type: 12`, and `no_matching_event_alias: 1`, so no searched
market was eligible for replay archival.
The live order-book snapshotter dry-run for `british_gp` on 2026-06-30 queried
eight British/Silverstone variants and inspected 479 returned market rows,
deduplicated to 180 candidate markets. It found zero 2026 definitions, zero
quotes, and zero snapshots; 73 matched candidates were rejected as
`season_mismatch`, so the command correctly did not write to
`data/market_snapshots/`.

The latest readiness-market scan for `2026-07-01T00:00:00+00:00` keeps the same
formal blocker open but now carries per-event review guidance. It inspected
2,701 search results for the seven market-blocked completed races and found
zero 2026 winner definitions or snapshots. Each unresolved event row records
`top_issue_code: season_mismatch`, a review summary explaining that no
cutoff-usable winner snapshot was produced, and a next action to reject the
mismatched-season markets while searching for a 2026-specific winner market or
independently reviewed historical price source.

British GP evidence status:

```text
validate-evidence --event british_gp: claim_count=4
archived_source_backed_claims: 1
predict --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00:
  evidence_quality_count: 4
  strong_evidence_quality_count: 0
  weak_evidence_quality_count: 4
  source-backed weather claim: weak_diagnostic, source_status=within_cutoff
  seed scenario claims: review_required with seed_scenario_source/source_log_missing flags
source_log: data/research/british_gp/source_log.json
packet_dir: data/evidence/british_gp/packets/
```

Generated British GP Codex research plan:

```text
data/research/british_gp/codex_research_plan.json
data/research/british_gp/codex_research_plan.md
status: review_required_evidence_present
source_task_count: 6
source_tasks:
  - P0 f1_official official/FIA context
  - P0 team_or_driver upgrades and track fit
  - P0 weather forecast and track conditions
  - P1 structured_data session and form data
  - P1 market rules and snapshot eligibility
  - P2 media independent corroboration
impact_bands: negligible, small, moderate, material
quality_gates: 7
```

Generated British GP prediction packet:

```text
reports/prediction_packets/british_gp/british_gp_20260630T120000_0000.prediction_packet.json
reports/prediction_packets/british_gp/british_gp_20260630T120000_0000.prediction_packet.md
status: diagnostic_only
formal_edge_ready: false
packet_payload_sha256: c957a2340d896ffd8e39eb306c64bdd9a4cbedd294a9c56d5e62870d67de8168
usable_market_snapshots: 1
after_cutoff_snapshot_count: 0
market_edge_count: 7
positive_edge_count: 1
evidence_count: 4
evidence_quality_count: 4
weak_evidence_quality_count: 4
strong_evidence_quality_count: 0
review_required_count: 4
max_evidence_win_delta: -0.0217
blockers:
  - codex_evidence_quality_review_required
  - probability_calibration_diagnostic_only
warnings:
  - codex_claims_require_review
```

The local server was verified at:

```text
http://127.0.0.1:8765
```

Playwright rendered the page and saved:

```text
output/playwright/f1predict-home.png
output/playwright/f1predict-official-standings-panel.png
output/playwright/f1predict-official-standings-aligned.png
output/playwright/f1predict-codex-quality-panel.png
output/playwright/codex-research-plan-panel-gates.png
output/playwright/codex-research-plan-mobile.png
output/playwright/f1predict-prediction-packet-panel.png
output/playwright/f1predict-chronological-replay-panel.png
output/playwright/f1predict-improvement-plan-panel.png
output/playwright/f1predict-cleaned-simulation-replay.png
output/playwright/replay-schematic-clean-british_gp.png
output/playwright/replay-schematic-mobile-british_gp.png
output/playwright/f1predict-cleaned-mobile.png
```

## Not Complete Yet

The full user goal is not complete. Remaining core work:

1. Keep Formula1.com roster sync in the regular ingestion loop and add human
   review for any future `review_required` driver/team additions before their
   model priors are allowed into formal forecasts.
2. Replace retrospective completed-race source snapshots with frozen
   point-in-time captures or verifiable archived-source captures for formal
   replay.
3. Keep race-week Open-Meteo forecast snapshots in the regular ingestion loop.
   The project now has cutoff-aware forecast ingestion/provider support, but
   formal race-week claims still require the relevant forecast to be captured
   before the prediction cutoff. Historical climate priors remain a fallback,
   not a substitute for point-in-time forecasts. The season opener's lack of
   previous-race form is tracked separately as non-blocking provenance;
   preseason testing or practice features would still improve it.
4. Use `capture-polymarket-snapshot` at each future prediction cutoff so new
   market rows have same-time order-book provenance instead of becoming another
   replay blocker.
5. Find or import reviewed historical 2026 F1 market definitions that include
   CLOB token ids, then use the existing Polymarket price-history backfill to
   reconstruct cutoff snapshots without using post-race prices.
6. Calibrate the strategy-aware simulator against historical lap/stint data and
   upgrade it from compact race-time proxies to a richer lap-by-lap strategy
   engine.
7. Promote the current chronological replay bundle from diagnostic-only to a
   matched first-race-to-current-date replay by filling the missing same-time
   market snapshots, retrospective source proofs, and frozen replay
   configuration.
8. Promote the current diagnostic failure analysis into a formal matched replay
   analysis after the missing point-in-time inputs are filled.

## Next Best Step

Implement the real point-in-time data ingestion layer:

```text
OpenF1/FastF1 session and result data
F1 official standings/calendar
Polymarket market discovery, live price snapshots, and historical backfill
Codex evidence packet population per race week
```
