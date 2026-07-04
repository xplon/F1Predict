# Codex Source Candidates: British Grand Prix

- event_id: `british_gp`
- knowledge_cutoff: `2026-06-30T12:00:00+00:00`
- status: `source_candidates_ready_for_claim_review`
- candidates: `1`
- review_ready: `1`
- blocked: `0`

## Status Counts
- `candidate_ready_for_claim_review`: 1

## Candidates

| candidate | source_class | status | task | metrics | routes | relevance | cutoff |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| `british_gp-weather-openmeteo-candidate-001` | `weather` | `candidate_ready_for_claim_review` | `british_gp:weather` | wet_skill | wet_skill->wet_weather | 1.00 | `within_cutoff` |

## Next Actions

- `british_gp-weather-openmeteo-candidate-001`: Open and snapshot the source, then convert only source-backed facts into research_packet_template.json claims.
