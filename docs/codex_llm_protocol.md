# Codex LLM Layer Protocol

This project can use Codex as the LLM and tool-using research layer, but Codex
must be treated as a normalized intelligence provider, not as a final predictor.

## Responsibilities

Codex may:

1. Search the web for current F1 news, FIA documents, weather narratives, market
   rules, and relevant race-week context.
2. Compare multiple sources and identify contradictions.
3. Extract claims into the project evidence schema.
4. Estimate qualitative impact direction and uncertainty for model parameters.
5. Produce an audit note explaining why a claim should or should not affect the
   simulator.
6. Let the project compute source-aware quality diagnostics from the claim,
   source log, cutoff status, archive proof, and measured model sensitivity.

Codex must not:

1. Directly set final win, podium, or championship probabilities.
2. Add unsourced claims to model input.
3. Use information published after the requested `knowledge_cutoff`.
4. Hide uncertainty or source conflicts.
5. Turn market prices into recommendations without the market engine.

## Required Evidence Fields

Each claim must be a JSON object with these fields:

```json
{
  "claim_id": "stable-id",
  "event_id": "british_gp",
  "source": "source name",
  "source_url": "<source-url>",
  "published_at": "2026-07-01T10:00:00Z",
  "observed_at": "2026-07-01T10:05:00Z",
  "target_type": "team",
  "target_id": "mercedes",
  "claim_type": "upgrade",
  "metric": "race_pace",
  "direction": "positive",
  "magnitude": 0.06,
  "confidence": 0.68,
  "uncertainty": 0.14,
  "evidence_text": "Short source-backed summary.",
  "reasoning": "Why this changes the model metric.",
  "review_required": true
}
```

`magnitude` is interpreted in model-score units. Positive direction means the
target should improve for the selected metric. The simulator decides how that
affects probabilities.

Supported MVP metrics are intentionally normalized and bounded:

- `race_pace`, `race_execution`, `qualifying_pace`, `tyre_deg`, `reliability`, `wet_skill`, `strategy`
- `power_unit`, `energy_recovery`, `straight_line_speed`, `drag_efficiency`
- `low_speed_traction`, `launch_performance`, `weight`, `upgrade_effect`

Technical claims must name a mechanism and circuit context. For example,
Codex should map a sourced claim about battery deployment or reduced clipping
to `energy_recovery`, a draggy rear-wing package to `drag_efficiency`, an
overweight car to `weight` with negative direction, a launch/clutch/turbo
response start claim to `launch_performance`, and a validated floor or sidepod
package to `upgrade_effect`. The simulator applies track-specific weights, so a
high-speed Silverstone-style claim should not affect a low-speed street race in
the same way. `race_execution` is intentionally separate from generic pace:
it captures grid-to-finish conversion, overtaking/defending, traffic handling,
and clean-race execution after the sampled grid. `launch_performance` changes
start and first-lap race-time conversion after the sampled grid.

## Evidence Impact Diagnostics

Prediction reports expose `evidence_impact` rows derived from the normalized
claims. These rows do not let Codex set probabilities. They compare the full
prediction with a same-seed counterfactual where the selected claim is removed
while all other Codex evidence and structured data features remain in place.
The output is a diagnostic sensitivity trace:

```json
{
  "claim_id": "british_gp-weather-001",
  "target_type": "event",
  "target_id": "british_gp",
  "metric": "wet_skill",
  "signed_input_impact": 0.04,
  "attribution_method": "diagnostic_same_seed_leave_one_claim_comparison",
  "affected_outcomes": [
    {"driver_id": "hamilton", "win_delta": 0.018, "expected_points_delta": 0.42}
  ],
  "max_win_probability_delta": 0.018
}
```

Use this for audit and model debugging only. It is not a formal causal ablation
unless the experiment controls are explicitly matched and recorded separately.

## Normalized Factor Trace

Prediction reports also expose `factor_trace` rows. This is the canonical bridge
from a Codex-normalized claim to the simulator surface it affects. The frontend
and prediction packets should read this server-side trace instead of recreating
metric routing rules independently.

Example:

```json
{
  "claim_id": "seed-british-001",
  "target_type": "team",
  "target_id": "mercedes",
  "claim_type": "ers",
  "metric": "energy_recovery",
  "direction": "positive",
  "route": "track_contextual_pace",
  "model_surface": "track-weighted pace score",
  "route_status": "observed_probability_movement",
  "raw_signed_impact": 0.0472,
  "weighted_input_impact": 0.0189,
  "effective_race_input": 0.0095,
  "effective_qualifying_input": 0.0100,
  "signed_input_impact": 0.0189,
  "max_win_probability_delta": 0.0217,
  "affected_outcome_count": 2,
  "quality_status": "review_required",
  "source_status": "seed_scenario",
  "triangulation_status": "seed_or_test_only",
  "context_multiplier": 0.5,
  "context_multiplier_reason": "energy_recovery uses ERS deployment, recovery efficiency, and clipping exposure; track_type=high_speed, base=0.16, track_sensitivity=0.34, mode=race, context_multiplier=0.500, demand_component=ers_demand, demand_value=0.34, launch_importance=0.24, altitude_power_derate=0.00",
  "track_demand_component": "ers_demand",
  "track_demand_value": 0.34,
  "track_demand_profile": {
    "track_type": "high_speed",
    "power_demand": 0.5,
    "ers_demand": 0.34,
    "drag_demand": 0.42,
    "traction_demand": 0.1,
    "mass_sensitivity": 0.32,
    "launch_importance": 0.24,
    "braking_energy_demand": 0.34,
    "altitude_power_derate": 0.0
  },
  "route_notes": [
    "Scaled by circuit type; captures ERS deployment and clipping sensitivity.",
    "target_scope=team:mercedes",
    "track_type=high_speed",
    "track_context_multiplier_applied=true",
    "context_multiplier=0.5000",
    "track_demand_component=ers_demand",
    "track_demand_value=0.3400"
  ]
}
```

The route vocabulary is intentionally small:

- `track_contextual_pace`: `power_unit`, `energy_recovery`,
  `straight_line_speed`, `drag_efficiency`, `low_speed_traction`, `weight`,
  and `upgrade_effect`
- `race_start_launch`: `launch_performance`
- `race_pace_score`: `race_pace`
- `race_execution_score`: `race_execution`
- `qualifying_grid_score`: `qualifying_pace`
- `tyre_degradation`: `tyre_deg`
- `reliability`: `reliability`
- `pit_strategy`: `strategy`
- `wet_weather`: `wet_skill`

`route_status` explains whether the claim was routed into the simulator and
whether the same-seed leave-one-claim evidence-impact comparison observed
probability movement.
For `track_contextual_pace` rows, `context_multiplier` is the exact multiplier
the simulator applies to the weighted claim input on that event's track type.
`raw_signed_impact` is the claim's direction, magnitude, confidence, and
uncertainty before quality gating. `weighted_input_impact` applies the source
quality/conflict weight. `effective_race_input` and
`effective_qualifying_input` show the simulator-facing value after track context
is applied where relevant. `track_demand_component`, `track_demand_value`, and
`track_demand_profile` expose the profile behind that context: for example ERS
claims read `ers_demand`, straight-line claims read `power_demand`, drag claims
read `drag_demand`, traction claims read `traction_demand`, weight claims read
`mass_sensitivity`, and launch/start claims read `launch_importance`.
Launch/start claims reach the `race_start_launch` surface rather than the
generic pace score.
The current MVP derives these values from the event's sourced/derived track
cluster; future ingestion can replace them with source-backed altitude, straight
length, braking-energy, and corner-speed features without changing the evidence
contract.
This keeps technical news such as ERS clipping, straight-line speed, drag
efficiency, traction, mass, and upgrade validation auditable from source claim
to pace score.
This trace is diagnostic evidence for model debugging; it is not a formal causal
ablation unless the formal comparison contract is separately satisfied.

## Evidence Quality Diagnostics

Prediction reports also expose `evidence_quality` rows. These rows audit Codex
claims before they are presented as model inputs. The score combines:

- claim confidence and uncertainty
- source reliability from `source_log.json`
- source cutoff status and historical archive support
- triangulation across independent source URLs/classes for the same target,
  metric, and direction
- conflict detection across opposing directions for the same target and metric
- `review_required` flags
- diagnostic impact from the same-seed leave-one-claim comparison

Example:

```json
{
  "claim_id": "british_gp-weather-openmeteo-001",
  "quality_status": "weak_diagnostic",
  "quality_score": 0.5082,
  "source_reliability": 0.7,
  "source_status": "within_cutoff",
  "triangulation_status": "single_source",
  "triangulation_score": 0.78,
  "conflict_status": "no_conflict",
  "conflict_score": 1.0,
  "corroborating_claim_count": 1,
  "corroborating_source_count": 1,
  "independent_source_count": 1,
  "conflicting_claim_count": 0,
  "conflicting_source_count": 0,
  "conflicting_independent_source_count": 0,
  "model_input_weight": 0.68,
  "impact_level": "moderate",
  "risk_flags": ["claim_requires_review", "single_source_claim"],
  "reasons": [
    "claim_confidence=0.70, uncertainty=0.35",
    "source_reliability=0.70",
    "source_status=within_cutoff",
    "triangulation=single_source"
  ]
}
```

`strong` means the claim has a comparatively clean source, timestamp trail, and
triangulation trail. `independent_corroboration` requires same-direction claims
to be supported by at least two non-seed/non-test source groups; `single_source`,
`same_source_repetition`, `seed_or_test_only`, and `unlinked_source` stay
diagnostic and are surfaced as risk flags.
`independent_source_conflict`, `limited_source_conflict`,
`same_source_conflict`, and `seed_or_test_conflict` mean opposing normalized
claim directions exist for the same target and metric. Conflicted evidence can
remain in diagnostic replay so the model path is inspectable, but it must not be
treated as strong evidence until the contradiction is resolved or explicitly
modeled as a scenario split.
`model_input_weight` is the pre-model credibility weight applied to the claim's
signed impact before the simulator sees it. It is computed without using race
outcomes: source reliability, cutoff status, archive support, triangulation,
conflict status, and review flags can downweight or zero a claim. This keeps
weak Codex evidence available for debugging while preventing it from moving the
simulation as strongly as a clean, source-backed claim.
`usable_diagnostic`, `weak_diagnostic`, and `review_required` are still allowed
to exercise the MVP pipeline, but they must not be used as formal edge evidence
without resolving the underlying flags and calibration blockers.

## Source Scoring

Codex should grade source reliability before writing evidence:

| Source type | Default reliability |
|---|---:|
| FIA / F1 official document | 0.95 |
| Team official release | 0.85 |
| Established F1 outlet with named reporting | 0.75 |
| Weather provider | 0.70 |
| Anonymous paddock rumor | 0.35 |
| Social post without corroboration | 0.20 |

Low-reliability claims may be stored, but they should carry high uncertainty and
`review_required: true`.

## Source Candidate Audit

Codex web-search/open results are not evidence claims yet. Before converting
unstructured information into `research_packet_template.json`, save inspected
candidate pages or search results into
`data/research/<event_id>/source_candidates.json` and run:

```powershell
python -m f1predict.cli codex-source-candidates --event <event_id> --input data/research/<event_id>/source_candidates.json --knowledge-cutoff <cutoff> --output reports/research_candidates/<event_id>.json --markdown-output reports/research_candidates/<event_id>.md
```

The candidate audit checks:

- candidate `event_id` matches the requested race
- URL is valid and source class is supported by the reliability registry
- source is linked to a generated research-plan task
- candidate timestamps are not after `knowledge_cutoff`
- model metrics overlap the linked task's metrics
- title/snippet/query text is relevant to the event, target, and metric
- each candidate metric has a simulator route preview, model surface, technical
  context multiplier where applicable, and impact-band guidance from the
  research plan

`candidate_ready_for_claim_review` means the source is eligible for manual
inspection and snapshotting. It does not mean the claim is true or model-ready.
`candidate_needs_review` requires human or Codex follow-up before drafting a
claim. `candidate_blocked` must be fixed or discarded. Wrong-event and
after-cutoff candidates are blocking because they would contaminate
point-in-time replay.

The route preview is intentionally pre-claim guidance. It can say that a
candidate tagged `energy_recovery` would route to `track_contextual_pace` on the
event's track type, but it must not choose final `direction`, `magnitude`, or
confidence before the source is read and converted into a claim.

Research-packet preflight cross-checks packet source URLs against this
candidate audit when `source_candidates.json` or
`reports/research_candidates/<event_id>.json` is available. If a packet source
URL is missing from the candidate audit, belongs to a wrong-event candidate, or
maps to a blocked/review-required candidate, preflight records a blocking
`source_candidate_*` finding and refuses archive precheck. If no candidate audit
exists yet, preflight emits a warning so the workflow gap is visible.
If the packet is still the generated template and contains `REPLACE_WITH_*`
placeholders, preflight returns `research_packet_template_unfilled` and does not
route placeholder rows through factor contracts or simulator previews. Replace
the placeholders with inspected source-candidate URLs and normalized claims
before treating preflight output as a claim-level gate.

After claims are drafted, preflight also applies the shared factor contract.
The contract maps each metric to allowed target types, allowed claim types,
simulator route, model surface, and technical mechanism. A claim such as
`metric=energy_recovery` must target a team or driver and use an ERS, battery,
clipping, or deployment style claim type; a weather or event-level ERS claim is
blocked with `factor_contract_*` findings before archive. This keeps Codex's
unstructured technical interpretation inside auditable simulator inputs.

## Knowledge Cutoff

For backtesting and historical replay, Codex must only use sources where:

```text
published_at <= knowledge_cutoff
observed_at <= knowledge_cutoff
```

When the timestamp is unclear, use the latest plausible timestamp and mark the
claim for review.

If Codex inspects a page after the replay cutoff but can verify a historical
archive capture at or before the cutoff, the source record may include a
`historical_archive` object. This does not change claim timestamps: the claim
still needs `published_at <= knowledge_cutoff` and `observed_at <=
knowledge_cutoff`. It only proves the late local snapshot is backed by a
cutoff-valid archived copy.

```json
{
  "historical_archive": {
    "archive_url": "https://web.archive.org/web/...",
    "archived_at": "2026-05-02T09:00:00Z",
    "original_url": "https://example.com/source",
    "verified_at": "2026-06-30T00:00:00Z",
    "verification_method": "wayback",
    "notes": "Archive capture matched the cited source page."
  }
}
```

The source audit rejects archive proofs when the archive timestamp is after the
cutoff, the original URL does not match the source URL, required fields are
missing, or the source publication time is later than the archive timestamp.

## Research Workflow Commands

Before researching a race, generate a deterministic source-quality and impact
rubric plan. This is the executable contract for Codex tool use: it lists source
classes to search, acceptance and rejection rules, impact bands, metric mapping,
quality gates, and the archive command for the final packet.

```powershell
python -m f1predict.cli codex-research-plan --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --write
```

The generated files live under `data/research/<event_id>/`:

```text
codex_research_plan.json
codex_research_plan.md
source_candidates.json
research_packet_template.json
```

Codex should treat the plan as binding guidance. If a source does not satisfy
the plan's acceptance checks, it can be recorded for diagnostic context only and
must not become a high-confidence model input.

After search/open tool use, normalize candidate sources before drafting claims:

```powershell
python -m f1predict.cli codex-source-candidates --event british_gp --input data/research/british_gp/source_candidates.json --knowledge-cutoff 2026-06-30T12:00:00+00:00 --output reports/research_candidates/british_gp.json --markdown-output reports/research_candidates/british_gp.md
```

Only candidates that are ready or explicitly resolved after review should be
snapshotted and converted into source-backed research-packet claims.

Then preflight the research packet with the same candidate-gate report:

```powershell
python -m f1predict.cli preflight-research-packet --input data/research/british_gp/research_packet_template.json --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --source-candidate-report reports/research_candidates/british_gp.json --output reports/research_preflight/british_gp.json --markdown-output reports/research_preflight/british_gp.md
```

Audit which completed replay rows still lack Codex evidence, structured
features, or market context:

```powershell
python -m f1predict.cli evidence-coverage --as-of 2026-06-30T00:00:00+00:00 --write --output reports\evidence_coverage_20260630.json
```

Coverage rows also expose `event_input_quality` and field-level event-input
risk codes. For OpenF1-calendar-generated rows,
`generated_verified` means the generated event row exposes sourced calendar,
result, circuit geometry, planned lap-count, and weather-prior provenance, with
model-only fields marked as derived. Weather priors currently come from
Open-Meteo historical climate profiles over pre-season baseline years; they are
not race-week forecasts. `generated_with_partial_verified_profile` remains the
warning state for generated rows where any simulation-driving profile field
falls back to a static heuristic or placeholder.

Coverage rows additionally include `retrospective_source_details` and
`archive_backed_source_details`. These are URL-level audit records showing which
late local snapshots still lack cutoff-valid archive proof and which snapshots
are supported by historical archives.

Coverage rows also include `market_snapshot_details`,
`market_snapshot_after_cutoff_details`, and `missing_market_snapshot_detail`.
Use these records to identify the exact market cutoff that still needs a
same-time snapshot or reviewed price-history backfill.

Build a formal replay readiness queue when deciding what Codex or data
collection should do next:

```powershell
python -m f1predict.cli formal-readiness --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

The readiness report is not a backtest result. It is an intake manifest that
groups blockers into workstreams, then lists per-event blockers, required
cutoffs, success criteria, and command templates for market backfill,
after-cutoff market replacement, source archive proof, and calibration review.

Parse stored Formula1.com standings pages before using official points as a
season-forecast input:

```powershell
python -m f1predict.cli build-official-standings --year 2026 --write
```

The parser extracts the official driver and team results tables, then audits
whether those rows match the project seed roster. Season forecasts may use the
official standings only when the snapshot is available before the forecast
cutoff and the roster audit is aligned.

Export the same readiness state as assignable task queues before handing work
to Codex, a human reviewer, or an external tracker:

```powershell
python -m f1predict.cli export-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00
```

The exported bundle writes JSONL and CSV rows per workstream. Each row keeps the
action id, event cutoff, command templates, source/market details, and an
acceptance check that must pass before the action can be considered resolved.

After a data-fix pass, verify the exported queue before freezing the replay
state:

```powershell
python -m f1predict.cli verify-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

The verifier re-runs formal readiness, compares current action ids with the
exported queue, and writes `verification.json` plus `verification.csv` with
open, resolved, and newly introduced actions. A row is not resolved until its
original `action_id` disappears from the current readiness report.

For market-related rows, scan Polymarket candidates before attempting manual
price-history backfill:

```powershell
python -m f1predict.cli scan-readiness-markets --year 2026 --as-of 2026-06-30T00:00:00+00:00 --limit 30 --include-closed --write
```

The market scan reads the exported intake queue, searches each blocked event,
and writes a JSON/CSV report showing search results, unique market candidates,
normalized snapshots, token definitions, and normalization issue counts. A
candidate market still cannot be used for replay until it is converted into a
cutoff-valid normalized snapshot and the readiness action disappears.

After replay generation, run probability calibration diagnostics before treating
any model-market gap as meaningful:

```powershell
python -m f1predict.cli calibration-report --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

This report computes diagnostic Brier score, actual-winner log loss, top-pick
confidence bins, and the market-scored subset size. It remains diagnostic until
the replay inputs, market snapshots, and evaluation configuration are frozen.

For a single race, generate a prediction packet before discussing edge quality:

```powershell
python -m f1predict.cli prediction-packet --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --iterations 1200 --write
```

The packet is the auditable handoff artifact for an event. It bundles the model
probability summary, event-input audit, Codex evidence-quality diagnostics,
market snapshot context, top market-gap rows, blocker codes, warning codes, and
a payload hash. A packet with `diagnostic_only` status or
`formal_edge_ready: false` must not be described as a real trading edge.

After readiness, market/source scans, and calibration diagnostics are available,
build the project improvement plan:

```powershell
python -m f1predict.cli improvement-plan --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

The improvement plan is the handoff from diagnostics to project execution. It
keeps formal-edge blockers, such as missing same-time market snapshots and
unproved retrospective sources, separate from diagnostic model-iteration tasks.
It should be regenerated before the replay state is frozen.

After the replay, readiness, and calibration reports are available, prefer the
chronological replay bundle command when reviewing the first-race-to-cutoff
state:

```powershell
python -m f1predict.cli chronological-replay --year 2026 --as-of 2026-06-30T00:00:00+00:00 --iterations 1200 --write
```

This command regenerates the ordered replay coverage, replay analysis, formal
readiness, calibration, improvement plan, and replay freeze, then writes one
JSON/Markdown bundle under `reports/chronological_replay/`. The bundle is still
diagnostic unless its readiness and calibration gates are formal-ready.

The local API resolves omitted `as_of` query parameters to the latest generated
disk artifact for each replay report family. Use an explicit `as_of` for a
reproducible historical view, and use `live=1` only when you intentionally want
to recompute analysis, readiness, calibration, or freeze reports.

After the component reports are written, freeze the current diagnostic state:

```powershell
python -m f1predict.cli replay-freeze-manifest --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

The freeze manifest fingerprints source code, frontend assets, input data, and
generated reports. Its status must still be read together with readiness and
calibration flags; a manifest that says `diagnostic_freeze_inputs_required`
does not promote a model-market gap into a formal edge claim.

For future prediction cutoffs, capture same-time market context through the
market engine rather than by embedding prices in an LLM claim:

```powershell
python -m f1predict.cli capture-polymarket-snapshot --event british_gp --limit 15 --write
```

The command records normalized snapshots plus quote-level `status`,
`best_bid`, `best_ask`, `midpoint`, `last_trade_price`, spread, and fallback
details. LLM/Codex may inspect those audit records, but market-price
differences enter predictions only through `MarketSnapshot` and `MarketAnalyzer`.
The market analyzer preserves raw model gap diagnostics, but recommendations
are made from conservative calibration-shrunk probabilities and include risk
flags such as `raw_edge_removed_by_calibration` when overconfidence changes the
decision.

When Codex or a human reviewer finds a market source outside the automated
Gamma/CLOB path, do not write directly to `data/market_snapshots`. First create
a reviewed market packet:

```powershell
python -m f1predict.cli reviewed-market-template --event miami_gp --market-type winner > data\research\markets\miami_gp_reviewed_market.json
```

The packet must include normalized model outcome ids in `prices`, a matching
`review.outcome_mapping`, `review.status` in `accepted`, `verified`,
`supports_market`, or `supports_claim`, `reviewed_by`, `reviewed_at`,
`source_url`, `source_captured_at`, and review notes explaining the resolution
rule and mapping. Archive only after validation:

```powershell
python -m f1predict.cli archive-reviewed-market-snapshot --event miami_gp --input data\research\markets\miami_gp_reviewed_market.json --knowledge-cutoff 2026-05-03T00:00:00+00:00 --require-cutoff-valid
```

This path still writes a normal `MarketSnapshot`, so the prediction pipeline and
replay analysis consume it through the same market store. It only proves that a
market input was reviewed and cutoff-valid; calibration and formal edge gates
remain diagnostic until the replay readiness reports clear.

Create deterministic research workspaces for completed races that still need
source-backed evidence:

```powershell
python -m f1predict.cli prepare-research --as-of 2026-06-30T00:00:00+00:00 --output-dir data\research
```

Each workspace contains:

- `research_task.md`: event context, cutoff, required source classes, search
  queries, and guardrails.
- `codex_research_plan.json`: machine-readable source tasks, quality gates,
  metric mapping, and impact bands.
- `codex_research_plan.md`: human-readable version of the same Codex research
  execution contract.
- `evidence_template.json`: a non-loaded template for JSONL evidence claims.
- `research_packet_template.json`: the preferred Codex handoff format containing
  both inspected sources and normalized claims.
- `source_log.json`: a source audit skeleton that records inspected URLs and
  which claim ids use them.
- `draft_evidence.jsonl`: editable workspace draft. The prediction pipeline
  does not read this file until it is validated and archived.

Preferred batch archive path after replacing template placeholders with real
sources and claims:

```powershell
python -m f1predict.cli preflight-research-packet --input data\research\miami_gp\research_packet_template.json --event miami_gp --knowledge-cutoff 2026-05-03T00:00:00+00:00 --output reports\research_preflight\miami_gp.json --markdown-output reports\research_preflight\miami_gp.md
python -m f1predict.cli archive-research-packet --input data\research\miami_gp\research_packet_template.json --event miami_gp --knowledge-cutoff 2026-05-03T00:00:00+00:00
```

`preflight-research-packet` is a dry-run gate. It checks packet schema,
source-to-claim links, source-audit blockers/warnings, conflict status,
factor-contract target/claim-type compatibility, triangulation,
quality-derived model input weights, and simulator factor routes.
Generated templates with `REPLACE_WITH_*` placeholders produce
`research_packet_template_unfilled`; those rows are not real claims and are not
routed into the simulator preview.
When the packet file sits beside `source_log.json`, preflight uses that existing
audit log for source status and quality weights; otherwise it builds a temporary
synthetic source log for diagnostic checks. It does not fetch pages or archive
evidence, so a passing preflight still must be followed by
`archive-research-packet`.
The local API exposes the same diagnostic state at
`/api/research-preflight?event_id=<event_id>`, and the frontend renders it in
the Research Packet Preflight panel so unresolved LLM intake blockers are visible
before prediction evidence is archived.

`archive-research-packet` snapshots every listed source, writes
`draft_evidence.jsonl`, audits source-to-claim linkage, enforces the cutoff, and
archives the validated packet under `data/evidence/<event_id>/packets/`.

Before a source can support a claim, snapshot it into the audit trail:

```powershell
python -m f1predict.cli snapshot-source --event miami_gp --url <url> --source <name> --source-class media --published-at <iso> --knowledge-cutoff 2026-05-03T00:00:00+00:00 --claim-id miami_gp-codex-001
```

For a source inspected after the cutoff but backed by a verified historical
archive capture:

```powershell
python -m f1predict.cli snapshot-source --event miami_gp --url <url> --source <name> --source-class media --published-at <iso> --observed-at <iso-before-cutoff> --knowledge-cutoff 2026-05-03T00:00:00+00:00 --claim-id miami_gp-codex-001 --historical-archive-url <archive-url> --historical-archived-at <iso-before-cutoff> --historical-original-url <url> --historical-verification-method wayback
```

The project can also query Wayback for retrospective local source snapshots.
Discovery tries the availability API first, then a CDX fallback over the source
URL and its http/https scheme variant. Use dry-run first, then `--write` only
after reviewing the report:

```powershell
python -m f1predict.cli discover-source-archives --output reports\source_archives\wayback_discovery.json
python -m f1predict.cli discover-source-archives --write --output reports\source_archives\wayback_discovery.write.json
```

When a readiness queue still has `source_archive_required` rows, recheck only
those events before seeking replacement sources:

```powershell
python -m f1predict.cli discover-source-archives --event miami_gp --event canadian_gp --event barcelona_gp --output reports\source_archives\remaining_blockers_cdx_discovery.json
```

If direct archive proof is unavailable, generate a replacement-source review
queue. A candidate is not usable merely because current content looks right; it
must become `formal_replacement_ready` through content checks, cutoff-valid
archive proof, archive-content validation, and archive timing checks:

```powershell
python -m f1predict.cli source-replacement-candidates --event miami_gp --event canadian_gp --event barcelona_gp --write
```

For candidates marked as requiring manual content review, a tool-content
override can clear only the current-content review blocker when it includes an
explicit structured review conclusion. It does not replace historical archive
proof or archive-content validation. The accepted shape is:

```json
{
  "url": "https://example.com/replacement-source",
  "captured_by": "codex_web_open",
  "captured_at": "2026-07-01T13:05:00+00:00",
  "manual_review_status": "supports_claim",
  "reviewed_by": "codex_structured_review",
  "reviewed_at": "2026-07-01T13:10:00+00:00",
  "manual_review_notes": "Explain which cited claim IDs are supported and why unrelated page payload text was excluded.",
  "content_text": "Normalized current-content extract used for expected-term checks."
}
```

`manual_review_status: supports_claim` is ignored unless `reviewed_by` and
review notes are present. Without a cutoff-valid archive, the candidate remains
diagnostic even when current content is manually reviewed.

Only formal-ready candidates may be applied. `apply-source-replacement` snapshots
the replacement source with its `historical_archive`, rewrites the affected
claim ids into a new archived evidence packet with the replacement `source_url`,
and reruns `SourceLogAuditor`. Non-ready candidates are rejected before write:

```powershell
python -m f1predict.cli apply-source-replacement --candidate-id <formal-ready-candidate-id> --replacement-report reports\source_replacements\remaining_blockers.source_replacements.json
```

This writes an append-only raw snapshot under `data/raw/research_sources/` and
adds a record to `data/research/<event_id>/source_log.json`. The record includes
default source reliability, content length, snapshot capture time, snapshot
path, and whether the source is inside the point-in-time cutoff.

If manually writing draft claims, validate and archive them before replay:

```powershell
python -m f1predict.cli validate-evidence --event miami_gp --path data\research\miami_gp\draft_evidence.jsonl
python -m f1predict.cli audit-evidence-sources --event miami_gp --input data\research\miami_gp\draft_evidence.jsonl --source-log data\research\miami_gp\source_log.json --knowledge-cutoff 2026-05-03T00:00:00+00:00
python -m f1predict.cli ingest-evidence --event miami_gp --input data\research\miami_gp\draft_evidence.jsonl --source-log data\research\miami_gp\source_log.json
python -m f1predict.cli replay-report --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

Archived packets are stored under `data/evidence/<event_id>/packets/` with a
sidecar metadata file. The provider reads legacy seed evidence and archived
packets, de-duplicates by `claim_id`, and still enforces `published_at` and
`observed_at` against the replay knowledge cutoff.

`ingest-evidence` refuses to archive a packet if a claim's `source_url` is not
present in the source log, if the matching source does not list the claim id in
`used_in_claim_ids`, if the source is after the cutoff, if the claim itself is
after the cutoff, or if the source/claim timestamps are later than the recorded
source snapshot capture time. Late local source snapshots remain diagnostic
unless they include a valid `historical_archive`; coverage reports such rows via
`archive_backed_source_snapshot_count` instead of
`retrospective_source_snapshot_count`.
