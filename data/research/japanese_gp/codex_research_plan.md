# Codex Research Plan: Japanese Grand Prix

- event_id: `japanese_gp`
- knowledge_cutoff: `2026-03-29T00:00:00+00:00`
- status: `review_required_evidence_present`

## Context
- round_number: `3`
- date: `2026-03-29`
- track_type: `technical`
- laps: `53`
- completed: `True`
- wet_probability_prior: `0.4143`
- input_source: `seed`
- track_asset_source: `f1_official_circuit_map`
- race_week_forecast_present: `False`

## Source Tasks
### Official and FIA Context
- task_id: `japanese_gp:f1-official-fia`
- source_class: `f1_official`
- priority: `P0`
- reliability_floor: `0.9`
- model_metrics: `reliability, strategy, qualifying_pace`
- queries:
  - Japanese Grand Prix 2026-03-29 Formula 1 official preview classification
  - Japanese Grand Prix 2026-03-29 FIA documents race director notes
  - Japanese Grand Prix 2026-03-29 penalties grid changes FIA
- acceptance:
  - Source is Formula1.com, FIA.com, or a linked official document.
  - Publication and observation timestamps are at or before the cutoff.
  - Classification, penalties, or rules claims include the governing document or official page.
- reject:
  - Reject fan summaries when the official document is available.
  - Reject any post-cutoff classification or penalty update for replay cutoffs.

### Team Upgrades and Track Fit
- task_id: `japanese_gp:team-updates-track-fit`
- source_class: `team_or_driver`
- priority: `P0`
- reliability_floor: `0.8`
- model_metrics: `race_pace, qualifying_pace, power_unit, energy_recovery, straight_line_speed, drag_efficiency, low_speed_traction, weight, upgrade_effect, tyre_deg, reliability`
- queries:
  - Japanese Grand Prix 2026-03-29 team upgrades Mercedes Ferrari McLaren Red Bull Racing
  - Japanese Grand Prix 2026-03-29 track characteristics technical F1
  - Japanese Grand Prix 2026-03-29 Mercedes Ferrari McLaren Red Bull preview
- acceptance:
  - Prefer team releases, named team principal quotes, or established outlets quoting named staff.
  - Tie every claimed effect to a metric such as race_pace, power_unit, energy_recovery, straight_line_speed, drag_efficiency, low_speed_traction, weight, upgrade_effect, tyre_deg, strategy, or reliability.
  - Use small magnitude unless the source says the part or issue is event-specific and already run-tested.
- reject:
  - Reject unsourced upgrade rumors as model inputs; store only as review_required rumor claims if needed.
  - Reject generic optimism unless it maps to a specific car, circuit, weather, or reliability mechanism.

### Weather and Track Conditions
- task_id: `japanese_gp:weather`
- source_class: `weather`
- priority: `P0`
- reliability_floor: `0.7`
- model_metrics: `wet_skill, strategy, reliability, qualifying_pace`
- queries:
  - Japanese Grand Prix 2026-03-29 weather forecast race rain wind track temperature
  - Japanese Grand Prix 2026-03-29 circuit weather radar F1
  - Japanese Grand Prix 2026-03-29 qualifying race forecast
- acceptance:
  - Weather claim states forecast window, race session timing, rain probability, and wind or temperature when available.
  - Forecast source is captured at or before the knowledge cutoff.
  - Wet or wind claims are translated into wet_skill, strategy, reliability, or qualifying_pace effects.
- reject:
  - Reject vague 'rain possible' claims without timing or probability.
  - Reject forecasts updated after the cutoff unless historical archive proof is attached.

### Structured Session and Form Data
- task_id: `japanese_gp:structured-session-data`
- source_class: `structured_data`
- priority: `P1`
- reliability_floor: `0.85`
- model_metrics: `race_pace, qualifying_pace, straight_line_speed, energy_recovery, low_speed_traction, tyre_deg, reliability`
- queries:
  - OpenF1 Japanese Grand Prix 2026-03-29 laps stints weather race control
  - FastF1 Japanese Grand Prix 2026-03-29 session results lap times
  - Japanese Grand Prix 2026-03-29 long run pace tyre degradation F1
- acceptance:
  - Structured data claims include session, metric, and cutoff availability.
  - Practice claims distinguish low-fuel headline pace from long-run race pace.
  - Race result claims are only used when the prediction cutoff is after the race.
- reject:
  - Reject practice fastest-lap headlines as race pace unless stint context is available.
  - Reject same-event race result data for pre-race prediction cutoffs.

### Market Rules and Snapshot Eligibility
- task_id: `japanese_gp:market-rules`
- source_class: `market`
- priority: `P1`
- reliability_floor: `0.65`
- model_metrics: `strategy`
- queries:
  - Japanese Grand Prix Polymarket winner market rules 2026-03-29
  - Japanese Grand Prix Polymarket F1 podium pole fastest lap market
  - Japanese Grand Prix prediction market final classification rules
- acceptance:
  - Market rule claims identify resolution source, cancellation handling, and post-race change handling.
  - Price data is not embedded as evidence; it must enter through MarketSnapshot ingestion.
  - Candidate market season, event, and outcome mapping are unambiguous.
- reject:
  - Reject mismatched season markets even if the race name matches.
  - Reject price screenshots or prose odds as formal market snapshots.

### Independent Corroboration
- task_id: `japanese_gp:independent-media-corroboration`
- source_class: `media`
- priority: `P2`
- reliability_floor: `0.7`
- model_metrics: `race_pace, qualifying_pace, power_unit, energy_recovery, straight_line_speed, drag_efficiency, low_speed_traction, weight, upgrade_effect, tyre_deg, reliability, strategy, wet_skill`
- queries:
  - Japanese Grand Prix 2026-03-29 F1 paddock notes named reporting
  - Japanese Grand Prix 2026-03-29 race preview upgrades reliability named sources
  - Japanese Grand Prix 2026-03-29 driver interviews team quotes
- acceptance:
  - Media claim has named outlet, author or agency, and a publication timestamp.
  - High-impact claims are corroborated by official, team, structured-data, or second independent media source.
  - Conflicting sources are captured as separate claims with review_required=true.
- reject:
  - Reject social reposts, anonymous rumors, and aggregation pages as standalone high-confidence evidence.
  - Reject claims where the original source cannot be identified.

## Impact Bands
- `negligible` -0.010..+0.010, confidence cap 0.75: Context is directionally relevant but unlikely to change simulation ordering.
- `small` -0.030..+0.030, confidence cap 0.72: Single-source setup, weather, or form signal with plausible but limited race effect.
- `moderate` -0.060..+0.060, confidence cap 0.68: Source-backed event-specific issue, upgrade, penalty, or weather signal likely to move a target group.
- `material` -0.100..+0.100, confidence cap 0.62: Confirmed grid penalty, major reliability issue, substantial rain change, or run-tested upgrade effect.

## Quality Gates
- Codex must not emit final probabilities or direct trading recommendations.
- Every claim must link to a snapshotted source URL and claim id in source_log.json.
- published_at and observed_at must be at or before knowledge_cutoff unless the claim is rejected.
- A late local snapshot needs cutoff-valid historical_archive proof before it can support formal replay.
- Claims with source reliability below 0.70, unknown publication time, source conflict, or material impact must set review_required=true.
- Technical claims must state the mechanism and circuit context before using power_unit, energy_recovery, drag_efficiency, low_speed_traction, weight, or upgrade_effect.
- Magnitude must stay within the impact band justified by source quality and corroboration.
- Market prices must enter through MarketSnapshot ingestion, not through Codex evidence claims.

## Tool Workflow
1. Run `python -m f1predict.cli prepare-research --event japanese_gp --knowledge-cutoff 2026-03-29T00:00:00+00:00` if workspace files are missing.
2. Use the source tasks in this plan to search web/FIA/team/weather/market sources.
3. Fill data/research/<event_id>/research_packet_template.json with inspected sources and normalized claims.
4. Attach historical_archive proof for any source inspected after the replay cutoff.
5. Run `python -m f1predict.cli archive-research-packet --input data/research/japanese_gp/research_packet_template.json --event japanese_gp --knowledge-cutoff 2026-03-29T00:00:00+00:00`.
6. Run `python -m f1predict.cli prediction-packet --event japanese_gp --knowledge-cutoff 2026-03-29T00:00:00+00:00 --iterations 1200 --write` before discussing edge quality.

## Output Contract
- research_packet_path: `data/research/japanese_gp/research_packet_template.json`
- draft_evidence_path: `data/research/japanese_gp/draft_evidence.jsonl`
- source_log_path: `data/research/japanese_gp/source_log.json`
- archive_command: `python -m f1predict.cli archive-research-packet --input data/research/japanese_gp/research_packet_template.json --event japanese_gp --knowledge-cutoff 2026-03-29T00:00:00+00:00`
