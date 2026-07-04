# Research Packet Preflight: british_gp

- Status: `preflight_passed`
- Archive precheck can archive: `True`
- Claims: `1/1` valid
- Sources: `1`
- Blocking issues: `0`
- Warnings: `0`
- Average model input weight: `0.7023`
- Source candidate audit: `source_candidates_ready_for_claim_review`

## Route Counts

- `wet_weather`: `1`

## Claim Rows

| claim_id | metric | route | route_status | quality | conflict | weight | context | demand | effective | contract | audit |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| british_gp-weather-openmeteo-001 | wet_skill | wet_weather | routed_impact_not_measured | usable_diagnostic | no_conflict | 0.7023 | None | None | -0.0639 | ok | none |

## Limitations

- Preflight is diagnostic only: it uses an existing source_log.json when available, otherwise builds a synthetic source log.
- A passing preflight must still be archived with archive-research-packet before claims enter predictions.
- Impact movement is not measured here; model input weights and factor routes are previewed before simulation.
