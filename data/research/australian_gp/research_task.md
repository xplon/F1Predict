# Codex Research Brief: Australian Grand Prix

## Mission
Use web/tools to gather only source-backed information available before the requested knowledge cutoff, then emit JSONL evidence claims matching docs/codex_llm_protocol.md.

## Event Context
- event_id: `australian_gp`
- round: 1
- date: 2026-03-08
- track_type: street
- laps: 58
- input_source: seed
- wet_probability_prior: 0.3143

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
- australian_gp-f1official-qualifying-russell-pole-001: russell qualifying_pace positive confidence=0.68 uncertainty=0.28

## Output Contract
Prefer a sources+claims manifest based on `data/research/australian_gp/research_packet_template.json`. Manual JSONL drafts should go to `data/research/australian_gp/draft_evidence.jsonl`; the prediction pipeline reads claims only after they are audited and archived under `data/evidence/australian_gp/packets/`. Each claim must include source_url, published_at, observed_at, metric, direction, magnitude, confidence, uncertainty, evidence_text, reasoning, and review_required.

## Guardrails
- Do not write final probabilities.
- Do not use unsourced claims.
- Do not use information after the knowledge cutoff.
- Mark rumor or low-reliability sources as review_required.
- Prefer multiple independent sources for high-impact claims.

## Point-In-Time Cutoff
- knowledge_cutoff: `2026-03-08T00:00:00+00:00`
- Reject any source where published_at or observed_at is after the cutoff.

## Search Queries
- Australian Grand Prix 2026-03-08 F1 practice qualifying race preview
- Australian Grand Prix 2026-03-08 FIA documents race director notes
- Australian Grand Prix 2026-03-08 team upgrades Mercedes Ferrari McLaren Red Bull
- Australian Grand Prix 2026-03-08 weather forecast F1
- Australian Grand Prix Polymarket winner market rules prices

## Workflow
1. Read `codex_research_plan.md` first; it defines source tasks, quality gates, metric mapping, and impact bands for this event.
2. Prefer filling `research_packet_template.json`; `f1predict archive-research-packet` will snapshot, validate, audit, and archive it.
3. For manual drafts, snapshot every inspected web/PDF/market source with `f1predict snapshot-source` before using it in a claim.
4. Write only source-backed claims to `draft_evidence.jsonl`.
5. Assign low confidence and high uncertainty to rumors, conflicting reports, or single-source claims.
6. Run `f1predict validate-evidence --event australian_gp --path data/research/australian_gp/draft_evidence.jsonl` if manually editing drafts.
7. Run `f1predict audit-evidence-sources --event australian_gp --input data/research/australian_gp/draft_evidence.jsonl --source-log data/research/australian_gp/source_log.json`.
8. Archive validated claims with `f1predict ingest-evidence --event australian_gp --input data/research/australian_gp/draft_evidence.jsonl --source-log data/research/australian_gp/source_log.json`.

## Source Snapshot Example
- `f1predict snapshot-source --event australian_gp --url <url> --source <name> --source-class media --published-at <iso> --knowledge-cutoff 2026-03-08T00:00:00+00:00 --claim-id <claim_id>`

## Batch Archive Example
- `f1predict archive-research-packet --input data/research/australian_gp/research_packet_template.json --event australian_gp --knowledge-cutoff 2026-03-08T00:00:00+00:00`

## Final Evidence Archive
- `data/evidence/australian_gp/packets/`
