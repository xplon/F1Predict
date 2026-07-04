# F1Predict Readiness Intake Bundle (2026)

- Replay cutoff: `2026-07-01T00:00:00+00:00`
- Generated at: `2026-07-01T16:51:28+00:00`
- Readiness status: **inputs_required**
- Formal backtest ready: **False**
- Blocking actions: 9
- Warning actions: 7

## Workstreams

- P1 `market_snapshot_backfill`: 6 blocking, 0 warning, 6 events
- P2 `after_cutoff_market_replacement`: 0 blocking, 2 warning, 2 events
- P3 `source_archive_proof`: 3 blocking, 0 warning, 3 events
- P6 `model_calibration_review`: 0 blocking, 5 warning, 5 events

## Files

- actions_jsonl: `reports\readiness_intake\2026_asof_20260701T000000_0000\actions.jsonl`
- after_cutoff_market_replacement_csv: `reports\readiness_intake\2026_asof_20260701T000000_0000\after_cutoff_market_replacement.actions.csv`
- after_cutoff_market_replacement_jsonl: `reports\readiness_intake\2026_asof_20260701T000000_0000\after_cutoff_market_replacement.actions.jsonl`
- manifest: `reports\readiness_intake\2026_asof_20260701T000000_0000\intake_manifest.json`
- market_snapshot_backfill_csv: `reports\readiness_intake\2026_asof_20260701T000000_0000\market_snapshot_backfill.actions.csv`
- market_snapshot_backfill_jsonl: `reports\readiness_intake\2026_asof_20260701T000000_0000\market_snapshot_backfill.actions.jsonl`
- model_calibration_review_csv: `reports\readiness_intake\2026_asof_20260701T000000_0000\model_calibration_review.actions.csv`
- model_calibration_review_jsonl: `reports\readiness_intake\2026_asof_20260701T000000_0000\model_calibration_review.actions.jsonl`
- source_archive_proof_csv: `reports\readiness_intake\2026_asof_20260701T000000_0000\source_archive_proof.actions.csv`
- source_archive_proof_jsonl: `reports\readiness_intake\2026_asof_20260701T000000_0000\source_archive_proof.actions.jsonl`
- workstreams_csv: `reports\readiness_intake\2026_asof_20260701T000000_0000\workstreams.csv`

## Verification

After filling or replacing queued inputs, re-run the verifier:

```powershell
python -m f1predict.cli verify-readiness-intake --year 2026 --as-of 2026-07-01T00:00:00+00:00 --write
```

The verifier compares this exported queue with the current readiness state and marks rows as open, resolved, or new.

For market-related rows, use the integrated Polymarket search/history backfill before rerunning the verifier:

```powershell
python -m f1predict.cli scan-readiness-markets --year 2026 --as-of 2026-07-01T00:00:00+00:00 --include-closed --write
python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type winner --include-closed --write --output reports\market_normalization\<event_id>_price_history.json --search-output reports\market_normalization\<event_id>_search_payload.json
python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type constructor_double_podium --include-closed --write --output reports\market_normalization\<event_id>_constructor_double_podium_price_history.json --search-output reports\market_normalization\<event_id>_constructor_double_podium_search_payload.json
python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type driver_h2h --include-closed --write --output reports\market_normalization\<event_id>_driver_h2h_price_history.json --search-output reports\market_normalization\<event_id>_driver_h2h_search_payload.json
python -m f1predict.cli reviewed-market-template --event <event_id> --market-type winner > data\research\markets\<event_id>_reviewed_winner_market.json
python -m f1predict.cli archive-reviewed-market-snapshot --event <event_id> --input data\research\markets\<event_id>_reviewed_winner_market.json --knowledge-cutoff <cutoff> --require-cutoff-valid
python -m f1predict.cli verify-readiness-intake --year 2026 --as-of 2026-07-01T00:00:00+00:00 --write
```

This bundle is an intake queue, not a formal backtest result. Resolve the blocking rows, re-run formal-readiness, calibration, and replay-freeze-manifest before promoting any edge claim.
