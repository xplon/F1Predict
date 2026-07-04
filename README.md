# F1Predict

F1Predict is an MVP research system for F1 prediction and market edge analysis.
It is designed around a strict separation of concerns:

- Codex-normalized intelligence turns unstructured news, interviews, FIA notes,
  weather narratives, and market rules into structured evidence.
- Normalized factor traces show which simulator surface each Codex claim reaches
  and whether same-seed diagnostics observed probability movement. They also
  decompose raw claim impact into quality-weighted and track-context-effective
  simulator inputs, with a track-demand component such as `ers_demand`,
  `power_demand`, `drag_demand`, `traction_demand`, `launch_importance`, or
  `mass_sensitivity`.
- Source-aware quality diagnostics flag opposing claims for the same target and
  metric so contradictory technical reports stay diagnostic until resolved.
- The simulator applies quality-derived Codex input weights, so weak or
  conflict-prone claims can be inspected without moving probabilities like
  strong source-backed evidence.
- Structured data and evidence feed probabilistic race and season simulators.
- Market snapshots are compared with fair probabilities after uncertainty and
  execution-cost buffers; recommendations use a conservative probability
  shrinkage layer so raw overconfident Monte Carlo gaps are not promoted
  directly.
- A local frontend displays one race weekend, archived official track maps, an
  interactive selected simulation replay, model signals, season forecast, Codex evidence,
  Codex research-plan tasks, research-packet preflight diagnostics, Codex evidence-impact sensitivity, market gaps, an auditable single-event
  prediction packet, a chronological replay bundle and diagnostic timeline,
  and a prioritized improvement plan for turning diagnostic replay blockers
  into assignable workstreams.

The current implementation is intentionally an MVP with seed prediction inputs,
calendar-augmented event generation, and live raw-data snapshots. It proves the
end-to-end architecture from data loading to normalized evidence, simulation,
market comparison, diagnostic replay coverage, local API, and frontend display.
It does not yet claim a real trading edge or a formal matched 2026 season replay.

## Quick Start

```powershell
$env:PYTHONPATH = "src"
python -m f1predict.cli predict --event british_gp
python -m f1predict.cli backtest
python -m f1predict.cli validate-evidence --event british_gp
python -m f1predict.server --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

## Project Environment

The recommended local environment is a project `.venv`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\f1predict.exe predict --event british_gp
```

FastF1 is declared as a project dependency and is installed into `.venv`.

## Project Shape

```text
src/f1predict/
  domain.py          Core dataclasses and schemas
  data_sources/      Seed and future live data adapters
  intelligence/      Codex evidence contracts and validation
  models/            Pace, race, and season simulation
  market.py          Fair value vs market comparison
  market_sources/    Market-source normalizers such as Polymarket Gamma
  market_store.py    Append-only normalized market snapshot storage
  backtest.py        Point-in-time replay skeleton
  prediction_packet.py Single-event prediction audit artifact builder
  chronological_replay.py Full replay bundle orchestration
  replay_analysis.py Diagnostic replay failure analysis
  pipeline.py        End-to-end orchestration
  server.py          Local JSON API and static web server
  cli.py             CLI entry points
  ingestion.py       Raw point-in-time ingestion orchestration
  storage.py         Append-only snapshot storage
  features/          Processed summaries and model feature adjustments

data/seed/
  demo_season.json
  evidence/*.jsonl

data/raw/
  openf1/*           Point-in-time raw API snapshots
  polymarket/*
  fastf1/*
  f1_official/*
  f1_official_race_profiles/*
  weather_profiles/*

data/market_snapshots/
  <event_id>/snapshots/*  Normalized market snapshots consumed by replay

data/processed/
  openf1/*           Derived summaries from raw snapshots
  calendar/*         Normalized replay calendars

web/
  index.html
  styles.css
  app.js
```

## Codex Layer Contract

The project treats Codex as a tool-using intelligence layer, but only through a
normalized evidence boundary. Codex does not write final probabilities directly.
Codex web-search/open outputs first go through a source-candidate audit before
they can become claims. That audit checks event id, source class, linked
research task, cutoff timing, metric overlap, URL validity, and relevance so
cross-race or after-cutoff information cannot silently enter the model.
Accepted candidates still need source snapshots and review before they become
source-backed evidence claims with timestamps, affected model metrics,
confidence, uncertainty, and review flags. Prediction reports add a
source-aware evidence quality audit that combines source reliability, cutoff
status, archive support, claim uncertainty, review flags, and diagnostic model
impact. They also include a same-seed leave-one-claim sensitivity comparison so
the UI can show which Codex claims moved target-scope probabilities without
mixing together other same-target evidence. See
`docs/codex_llm_protocol.md`.

## Current MVP Limitations

- Uses seed data for prediction, but now includes raw OpenF1, FastF1,
  Polymarket, F1 official, and Open-Meteo snapshot ingestion commands.
- Missing calendar events are generated from OpenF1 calendar snapshots and
  FastF1 race results so diagnostic replay can span completed races.
- FastF1 previous-results form features are generated point-in-time from races
  that ended before the target prediction cutoff.
- FastF1 result loading is Race-session-only by default so later Sprint result
  snapshots cannot silently override the canonical race result used by replay
  and season forecasts.
- Season forecast is cutoff-aware: completed races before the cutoff seed the
  points table from stored FastF1 `Points` fields where available, falling back
  to classified order only when points are missing. Remaining races are
  simulated through the same strategy-aware event sampling boundary used by
  single-race prediction, with event-specific Codex evidence and processed
  features available at that cutoff.
- F1 official driver/team standings pages can be parsed from stored HTML
  snapshots into structured standings rows. The parser audits project-roster
  coverage before those standings are allowed to seed season base points. The
  latest stored 2026 standings are aligned with the seed roster and can seed
  current forecasts, while official standings captured after a replay cutoff
  remain warnings rather than silently changing historical forecasts. A roster
  sync planner can now turn official standings drift into an audited seed update
  plan without silently applying model-prior changes for new drivers or teams.
- Uses a strategy-aware compact Monte Carlo race-time simulator with grid,
  tyre degradation, pit-loss, weather, safety-car, and reliability proxies.
  Prediction reports include a selected simulation replay with lap-by-lap
  position, gap, compound, pit-stop, weather, safety-car, reliability, and DNF
  fields for frontend inspection. The frontend can play or scrub that selected
  sample by lap, with a schematic track replay and current-lap ranking frame.
  It is still not a fully calibrated
  lap-by-lap strategy engine, and the season forecast remains diagnostic until
  the event sampler is historically calibrated.
- Backtest is a diagnostic point-in-time harness over available prediction
  inputs. Generated events now expose field-level input provenance: OpenF1
  calendar fields, FastF1 results, and stored Multiviewer circuit geometry are
  verified where available. Archived F1 official track-map assets are attached
  to every loaded non-cancelled 2026 event for frontend display; Madrid/Madring
  uses an F1-official-image-derived geometry profile because the live circuit
  geometry endpoint currently returns 404. F1 official race profile pages
  verify planned lap counts, track-type clusters are derived from stored
  circuit geometry, and Open-Meteo historical climate profiles derive weather
  priors from pre-season baseline years. These climate priors are not race-week
  forecasts.
- Replay rows keep both the raw calendar round and a cancellation-aware race
  sequence, so expected shifts after cancelled events remain visible as
  provenance instead of being treated as source mismatches.
- Market snapshots are cutoff-filtered before edge comparison; after-cutoff
  seed or backfilled prices are reported as blockers instead of being used.
- Coverage and replay analysis expose market snapshot diagnostics with each
  event's required cutoff, cutoff-valid snapshots, and excluded after-cutoff
  snapshots.
- Normalized market snapshots can now be archived outside seed data under
  `data/market_snapshots/`, but the completed-race replay still needs real
  same-time historical market prices before any edge claim is formal.
- Polymarket public search can now be audited by season event names, but the
  latest 2026 run found no eligible 2026 F1 winner market definitions to
  archive into replay.
- Future race cutoffs can now use `capture-polymarket-snapshot` to search
  Polymarket, query CLOB order books for matched driver tokens, archive
  normalized same-time snapshots, and keep quote-level fallback/status details.
- Replay analysis is diagnostic-only and reports formal-backtest blockers
  before any result can be treated as an edge claim.
- Chronological replay bundles orchestrate coverage, replay analysis, formal
  readiness, calibration, improvement-plan, and freeze generation into a single
  JSON/Markdown artifact for first-race-to-cutoff diagnostic review.
- Replay analysis also groups event-level issues into project-level root causes
  such as market data gaps, source time-integrity gaps, and model calibration
  gaps, with evidence and improvement actions.
- Formal readiness reporting turns replay blockers into workstream batches and
  a per-event intake queue with required cutoffs, success criteria, and command
  templates for market backfills, after-cutoff market replacement, source
  archive proof, and model-calibration review.
- Replay calibration reporting computes diagnostic probability-quality metrics
  such as winner Brier score, actual-winner log loss, top-pick confidence bins,
  and market-scored subset size before any edge claim is promoted.
- Replay freeze manifests fingerprint source code, frontend assets, input data,
  and generated diagnostic reports so a replay state can be audited before any
  future edge claim is promoted. The local API and frontend expose the same
  freeze status, artifact hashes, and integrity flags.
- The local API and frontend also expose market-readiness scans so unresolved
  market blockers show searched candidates, rejected definitions, and
  normalization issue counts next to the replay and intake queues. Each blocked
  event now carries a dominant issue, a review summary, and a concrete next
  action so mismatched-season markets are rejected instead of being mistaken for
  replayable price evidence.
- Source-readiness scans are also exposed in the local API and frontend so
  remaining archive-proof blockers show which source URLs still lack
  cutoff-valid Wayback/CDX evidence.
- The frontend renders archived F1 official track-map assets first, backed by
  local provenance in each event. Stored circuit geometry remains available for
  model provenance and fallback rendering, including the Madrid/Madring profile
  derived from its official visual asset when the circuit geometry API returned
  404.
- Improvement-plan reports combine formal readiness, market-readiness scans,
  source-archive blockers, and replay calibration into a small set of
  prioritized project workstreams, keeping formal edge blockers separate from
  diagnostic model-iteration tasks.
- Simulator calibration diagnostics compare hand-curated simulator parameter
  candidates over the same replay rows and surface a review candidate with
  log-loss, Brier, calibration-gap, and actual-winner probability deltas. This
  remains diagnostic-only because the current replay sample is small and the
  candidate ranking is in-sample rather than a held-out ablation.
- MVP gate reports aggregate the user's delivery requirements into an auditable
  requirement-by-requirement status: diagnostic MVP operation, remaining MVP
  delivery blockers, formal-edge blockers, evidence paths, and next actions.
  `mvp_delivery_ready` is the diagnostic MVP delivery gate, not a claim of a
  stable trading edge: same-time market gaps, source archive proof, and
  probability calibration can remain as `formal_edge_blockers` while the
  data-to-Codex-to-simulation-to-replay-to-frontend chain is deliverable.
- Readiness intake export writes per-workstream JSONL/CSV task queues for
  market backfill, source archive proof, after-cutoff market replacement, and
  calibration review.
- Readiness intake verification compares an exported queue with the current
  formal readiness state and marks queued rows as open, resolved, or new before
  the replay state is frozen.
- Readiness market scanning reads the exported queue, searches Polymarket by
  blocked event, and reports whether candidate market definitions exist before
  any manual price-history backfill is attempted.
- Completed-race Codex evidence packets can be retrospectively backfilled from
  web sources, but those snapshots remain diagnostic until replaced by frozen
  point-in-time or verifiable archived captures.
- Source logs now support a `historical_archive` proof for late local snapshots.
  Wayback discovery uses the availability API plus a CDX fallback, and coverage
  reports archive-backed snapshots separately from retrospective snapshots.
  Coverage and replay analysis also expose URL-level source details for
  retrospective and archive-backed snapshots.
- Market analysis is no-trade research output only.
- Market edge rows now keep both raw model probability and conservative
  calibration-shrunk probability. The recommendation is based on conservative
  edge after costs, with risk flags when raw gaps are downgraded.
- Single-event prediction packets bundle the model probabilities, event-input
  audit, market context, Codex evidence-quality diagnostics, blockers,
  warnings, and a payload hash. They remain `diagnostic_only` until source,
  market, and calibration blockers are resolved.
- Codex evidence is audited separately from replay so diagnostic results cannot
  be mistaken for a source-backed edge claim.
- Codex research plans are exposed through the local API and frontend so source
  tasks, quality gates, and impact bands are visible next to evidence and
  judgement panels.
- Codex web-search source candidates are audited before claim drafting through
  `codex-source-candidates`, which blocks after-cutoff, invalid, unsupported,
  unlinked, or wrong-event candidates and writes reviewable JSON/Markdown
  reports under `reports/research_candidates/`. The local API and frontend
  expose the same audit so the single-event page shows whether Codex search/open
  results are ready, review-required, or blocked before research-packet
  preflight. Candidate rows also preview simulator routes, model surfaces,
  event-specific technical context multipliers, and impact-band guidance, while
  leaving direction/magnitude selection to the later source-backed claim step.
- Codex research can be handed off as a single sources+claims manifest through
  `archive-research-packet`, which snapshots sources, writes draft JSONL,
  audits source linkage, and archives the packet.
- Research-packet preflight now applies the shared factor contract before
  archive: each claim metric must match allowed target types and claim types,
  so technical notes such as ERS, turbo, clipping, weight, or upgrade effects
  cannot enter the simulator as loosely labeled generic evidence.
- Unfilled `research_packet_template.json` files now return an explicit
  `research_packet_template_unfilled` preflight status. Placeholder
  `REPLACE_WITH_*` rows are not routed as real Codex claims, and the frontend
  renders source-candidate and preflight panels independently of slower packet
  generation so the Codex intake gate is visible as soon as it is available.
- File-based research-packet preflight uses the adjacent
  `data/research/<event_id>/source_log.json` when it exists, so already
  snapshotted cutoff-valid sources are scored from the real audit trail instead
  of a temporary synthetic log.

## Data Ingestion Commands

```powershell
$env:PYTHONPATH = "src"

# Snapshot real OpenF1 data for a historical event.
python -m f1predict.cli ingest-openf1 --year 2024 --event-query Silverstone --include-session-data

# Snapshot and normalize the season calendar.
python -m f1predict.cli ingest-openf1-calendar --year 2026
python -m f1predict.cli build-calendar --year 2026 --write

# Snapshot source-backed circuit geometry for track maps.
python -m f1predict.cli ingest-circuit-profiles --year 2026

# Snapshot F1 official race profile pages for planned lap counts.
python -m f1predict.cli ingest-f1-race-profiles --year 2026

# Snapshot Open-Meteo climate profiles for weather priors.
python -m f1predict.cli ingest-weather-profiles --year 2026 --baseline-start-year 2016 --baseline-end-year 2025 --window-days 3

# Snapshot FastF1 schedule and F1 official pages.
python -m f1predict.cli ingest-fastf1-schedule --year 2026
python -m f1predict.cli ingest-fastf1-results --year 2026 --as-of 2026-06-30T00:00:00+00:00
python -m f1predict.cli ingest-f1-official --year 2026 --page calendar
python -m f1predict.cli ingest-f1-official --year 2026 --page drivers
python -m f1predict.cli ingest-f1-official --year 2026 --page teams

# Parse stored Formula1.com standings pages and audit roster alignment.
python -m f1predict.cli build-official-standings --year 2026
python -m f1predict.cli build-official-standings --year 2026 --write

# Plan audited seed roster updates from official standings.
python -m f1predict.cli sync-official-roster --year 2026 --plan-output reports/official_roster_sync/2026_latest.json
python -m f1predict.cli sync-official-roster --year 2026 --apply

# Build processed summaries from stored OpenF1 raw snapshots.
python -m f1predict.cli summarize-openf1 --year 2024 --event-query Silverstone --write

# Run a diagnostic full-season points/championship forecast.
python -m f1predict.cli season-forecast --knowledge-cutoff 2026-06-30T00:00:00+00:00 --iterations 1200 --output reports/season_forecast/2026_asof_20260630T000000_0000.json

# Snapshot current Polymarket F1 tagged events.
python -m f1predict.cli ingest-polymarket --limit 5

# Dry-run normalization of a Polymarket Gamma snapshot into model-ready markets.
# Use --write only after season/event/driver issues have been reviewed.
python -m f1predict.cli normalize-polymarket --event british_gp --input data/raw/polymarket/f1_events/<date>/<snapshot>.json --knowledge-cutoff 2026-07-05T00:00:00+00:00

# Scan one Polymarket Gamma payload against every season event before backfill.
python -m f1predict.cli discover-polymarket-markets --input data/raw/polymarket/f1_events/<date>/<snapshot>.json --output reports/market_normalization/f1_market_discovery.json

# Search Polymarket public search by season event names and audit candidate markets.
python -m f1predict.cli search-polymarket-season --limit 15 --include-closed --output reports/market_normalization/f1_season_search.json

# Capture current Polymarket order-book-backed prices for a future cutoff.
# Use --write at the prediction cutoff to archive the snapshot into replay.
python -m f1predict.cli capture-polymarket-snapshot --event british_gp --limit 15 --output reports/market_normalization/british_gp_live_snapshot.json
python -m f1predict.cli capture-polymarket-snapshot --event british_gp --limit 15 --write

# Backfill cutoff prices from reviewed Polymarket CLOB price history.
# This stays dry-run unless --write is passed.
python -m f1predict.cli backfill-polymarket-history --event british_gp --input data/raw/polymarket/f1_events/<date>/<snapshot>.json --knowledge-cutoff 2026-07-05T00:00:00+00:00 --output reports/market_normalization/british_gp_price_history.json

# Archive normalized market snapshots into the replayable market store.
# The input may be JSONL, a single JSON object, a JSON list, or {"snapshots": [...]}.
python -m f1predict.cli archive-market-snapshot --event miami_gp --input data/research/markets/miami_gp_market_snapshot.jsonl --knowledge-cutoff 2026-05-03T00:00:00+00:00

# Stricter Codex/manual reviewed market ingress with reviewer/source/outcome checks.
python -m f1predict.cli reviewed-market-template --event miami_gp --market-type winner > data/research/markets/miami_gp_reviewed_market.json
python -m f1predict.cli archive-reviewed-market-snapshot --event miami_gp --input data/research/markets/miami_gp_reviewed_market.json --knowledge-cutoff 2026-05-03T00:00:00+00:00 --require-cutoff-valid

# Generate a Codex research brief for normalized web research.
python -m f1predict.cli research-brief --event british_gp

# Generate a source-quality and impact-rubric plan before Codex web research.
python -m f1predict.cli codex-research-plan --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --write

# Audit missing Codex evidence, features, and market snapshots.
python -m f1predict.cli evidence-coverage --as-of 2026-06-30T00:00:00+00:00 --write --output reports/evidence_coverage_20260630.json

# Create Codex research task files for completed races that lack evidence.
python -m f1predict.cli prepare-research --as-of 2026-06-30T00:00:00+00:00 --output-dir data/research

# Audit Codex web-search/open source candidates before drafting claims.
python -m f1predict.cli codex-source-candidates --event miami_gp --input data/research/miami_gp/source_candidates.json --knowledge-cutoff 2026-05-03T00:00:00+00:00 --output reports/research_candidates/miami_gp.json --markdown-output reports/research_candidates/miami_gp.md

# Preferred: after source-candidate review and template filling, preflight the Codex sources+claims manifest.
python -m f1predict.cli preflight-research-packet --input data/research/miami_gp/research_packet_template.json --event miami_gp --knowledge-cutoff 2026-05-03T00:00:00+00:00 --source-candidate-report reports/research_candidates/miami_gp.json --output reports/research_preflight/miami_gp.json --markdown-output reports/research_preflight/miami_gp.md

# Archive only after preflight shows schema, source links, conflicts, factor contracts, and routes are acceptable.
python -m f1predict.cli archive-research-packet --input data/research/miami_gp/research_packet_template.json --event miami_gp --knowledge-cutoff 2026-05-03T00:00:00+00:00

# Manual path: validate and archive a filled research draft into the same store.
python -m f1predict.cli snapshot-source --event miami_gp --url <url> --source <name> --source-class media --published-at <iso> --knowledge-cutoff 2026-05-03T00:00:00+00:00 --claim-id miami_gp-codex-001

# Optional: attach verified historical archive proof for a source inspected after cutoff.
python -m f1predict.cli snapshot-source --event miami_gp --url <url> --source <name> --source-class media --published-at <iso> --observed-at <iso-before-cutoff> --knowledge-cutoff 2026-05-03T00:00:00+00:00 --claim-id miami_gp-codex-001 --historical-archive-url <archive-url> --historical-archived-at <iso-before-cutoff> --historical-original-url <url> --historical-verification-method wayback

# Discover Wayback archive proofs for late local source snapshots.
python -m f1predict.cli discover-source-archives --output reports/source_archives/wayback_discovery.json
python -m f1predict.cli discover-source-archives --write --output reports/source_archives/wayback_discovery.write.json

python -m f1predict.cli validate-evidence --event miami_gp --path data/research/miami_gp/draft_evidence.jsonl
python -m f1predict.cli audit-evidence-sources --event miami_gp --input data/research/miami_gp/draft_evidence.jsonl --source-log data/research/miami_gp/source_log.json --knowledge-cutoff 2026-05-03T00:00:00+00:00
python -m f1predict.cli ingest-evidence --event miami_gp --input data/research/miami_gp/draft_evidence.jsonl --source-log data/research/miami_gp/source_log.json

# Predict a generated completed event from calendar/result snapshots.
python -m f1predict.cli predict --event miami_gp --iterations 500

# British GP now includes one archived source-backed weather evidence packet.
python -m f1predict.cli validate-evidence --event british_gp
python -m f1predict.cli predict --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --iterations 500
python -m f1predict.cli prediction-packet --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --iterations 1200 --write

# Build replay coverage report from first race to a cutoff date.
python -m f1predict.cli replay-report --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Analyze replay failure modes and write JSON + Markdown reports.
python -m f1predict.cli analyze-replay --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Build the full chronological diagnostic bundle and refresh component reports.
python -m f1predict.cli chronological-replay --year 2026 --as-of 2026-06-30T00:00:00+00:00 --iterations 1200 --write

# Build the formal replay input-readiness queue.
python -m f1predict.cli formal-readiness --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Export assignable readiness workstream queues.
python -m f1predict.cli export-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00

# Verify whether exported readiness actions are still open, resolved, or new.
python -m f1predict.cli verify-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Search market candidates for the market-related readiness rows.
python -m f1predict.cli scan-readiness-markets --year 2026 --as-of 2026-06-30T00:00:00+00:00 --include-closed --write

# Diagnose probability calibration over replayable races.
python -m f1predict.cli calibration-report --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Diagnose simulator-parameter candidates over replayable races.
python -m f1predict.cli simulator-calibration --year 2026 --as-of 2026-06-30T00:00:00+00:00 --iterations 800 --write

# Build a prioritized improvement plan from readiness, source, market, and
# calibration diagnostics.
python -m f1predict.cli improvement-plan --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Build the MVP delivery gate over current diagnostic artifacts.
python -m f1predict.cli mvp-gate --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write

# Build the final diagnostic MVP completion audit.
python -m f1predict.cli mvp-completion-audit --year 2026 --as-of 2026-07-01T00:00:00+00:00 --write

# Freeze the current diagnostic replay state for reproducibility.
python -m f1predict.cli replay-freeze-manifest --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

The MVP gate separates two claims. `mvp_delivery_ready=true` means the
diagnostic project deliverable is runnable and auditable end-to-end.
`formal_edge_ready=true` is intentionally stricter and remains false until
same-time market snapshots, cutoff-valid source proof, and matched calibration
requirements are resolved.

The completion audit is the top-level handoff artifact. It checks the original
MVP objective against the current code, reports, frontend evidence, replay
diagnostics, and Codex factor-routing proof. The current expected status is
`mvp_complete_formal_edge_not_ready`, which means the diagnostic MVP is complete
without claiming a stable betting edge.

The local API and frontend resolve omitted `as_of` values to the latest generated
replay artifact for each report family. Pass `?as_of=<iso>` to any replay
endpoint when you need an exact historical snapshot, or `?live=1` on replay
analysis/readiness/calibration/freeze endpoints when you intentionally want to
recompute instead of reading the frozen disk report.
