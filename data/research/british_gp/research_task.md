# Codex Research Brief: British Grand Prix

## Mission
Use web/tools to gather only source-backed information available before the requested knowledge cutoff, then emit JSONL evidence claims matching docs/codex_llm_protocol.md.

## Event Context
- event_id: `british_gp`
- round: 11
- date: 2026-07-05
- track_type: high_speed
- laps: 52
- input_source: seed
- wet_probability_prior: 0.4143

## Leading Drivers In Seed State
- Kimi Antonelli (Mercedes): 171 pts
- George Russell (Mercedes): 131 pts
- Lewis Hamilton (Ferrari): 125 pts
- Oscar Piastri (McLaren): 80 pts
- Charles Leclerc (Ferrari): 79 pts
- Lando Norris (McLaren): 79 pts
- Max Verstappen (Red Bull Racing): 73 pts
- Isack Hadjar (Red Bull Racing): 42 pts
- Pierre Gasly (Alpine): 41 pts
- Liam Lawson (Racing Bulls): 30 pts

## Required Source Classes
- F1 official event, standings, and classification pages
- FIA documents and race director notes
- OpenF1/FastF1 session data if available
- Team official upgrade or preview notes
- Established F1 reporting from named outlets
- Weather forecast or radar provider
- Polymarket market rules and orderbook snapshots

## Evidence Already Loaded
- seed-british-001: mercedes energy_recovery positive confidence=0.72 uncertainty=0.18
- seed-british-002: red_bull upgrade_effect positive confidence=0.58 uncertainty=0.24
- seed-british-003: ferrari straight_line_speed negative confidence=0.56 uncertainty=0.28
- seed-british-004: ferrari tyre_deg negative confidence=0.55 uncertainty=0.3
- british_gp-weather-openmeteo-001: british_gp wet_skill negative confidence=0.7 uncertainty=0.35

## Output Contract
Prefer a sources+claims manifest based on `data/research/british_gp/research_packet_template.json`. Manual JSONL drafts should go to `data/research/british_gp/draft_evidence.jsonl`; the prediction pipeline reads claims only after they are audited and archived under `data/evidence/british_gp/packets/`. Each claim must include source_url, published_at, observed_at, metric, direction, magnitude, confidence, uncertainty, evidence_text, reasoning, and review_required.

## Guardrails
- Do not write final probabilities.
- Do not use unsourced claims.
- Do not use information after the knowledge cutoff.
- Mark rumor or low-reliability sources as review_required.
- Prefer multiple independent sources for high-impact claims.

## Point-In-Time Cutoff
- knowledge_cutoff: `2026-06-30T12:00:00+00:00`
- Reject any source where published_at or observed_at is after the cutoff.

## Search Queries
- British Grand Prix 2026-07-05 F1 practice qualifying race preview
- British Grand Prix 2026-07-05 FIA documents race director notes
- British Grand Prix 2026-07-05 team upgrades Mercedes Ferrari McLaren Red Bull
- British Grand Prix 2026-07-05 weather forecast F1
- British Grand Prix Polymarket winner market rules prices

## Workflow
1. Read `codex_research_plan.md` first; it defines source tasks, quality gates, metric mapping, and impact bands for this event.
2. Prefer filling `research_packet_template.json`; `f1predict archive-research-packet` will snapshot, validate, audit, and archive it.
3. For manual drafts, snapshot every inspected web/PDF/market source with `f1predict snapshot-source` before using it in a claim.
4. Write only source-backed claims to `draft_evidence.jsonl`.
5. Assign low confidence and high uncertainty to rumors, conflicting reports, or single-source claims.
6. Run `f1predict validate-evidence --event british_gp --path data/research/british_gp/draft_evidence.jsonl` if manually editing drafts.
7. Run `f1predict audit-evidence-sources --event british_gp --input data/research/british_gp/draft_evidence.jsonl --source-log data/research/british_gp/source_log.json`.
8. Archive validated claims with `f1predict ingest-evidence --event british_gp --input data/research/british_gp/draft_evidence.jsonl --source-log data/research/british_gp/source_log.json`.

## Source Snapshot Example
- `f1predict snapshot-source --event british_gp --url <url> --source <name> --source-class media --published-at <iso> --knowledge-cutoff 2026-06-30T12:00:00+00:00 --claim-id <claim_id>`

## Batch Archive Example
- `f1predict archive-research-packet --input data/research/british_gp/research_packet_template.json --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00`

## Final Evidence Archive
- `data/evidence/british_gp/packets/`
