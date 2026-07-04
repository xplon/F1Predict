# F1Predict Readiness Intake Bundle (2026)

- Replay cutoff: `2026-06-30T00:00:00+00:00`
- Generated at: `2026-06-30T17:07:35+00:00`
- Readiness status: **inputs_required**
- Formal backtest ready: **False**
- Blocking actions: 12
- Warning actions: 5

## Workstreams

- P1 `market_snapshot_backfill`: 7 blocking, 0 warning, 7 events
- P2 `after_cutoff_market_replacement`: 2 blocking, 0 warning, 2 events
- P3 `source_archive_proof`: 3 blocking, 0 warning, 3 events
- P6 `model_calibration_review`: 0 blocking, 5 warning, 5 events

## Files

- actions_jsonl: `reports\readiness_intake\2026_asof_20260630T000000_0000\actions.jsonl`
- after_cutoff_market_replacement_csv: `reports\readiness_intake\2026_asof_20260630T000000_0000\after_cutoff_market_replacement.actions.csv`
- after_cutoff_market_replacement_jsonl: `reports\readiness_intake\2026_asof_20260630T000000_0000\after_cutoff_market_replacement.actions.jsonl`
- manifest: `reports\readiness_intake\2026_asof_20260630T000000_0000\intake_manifest.json`
- market_snapshot_backfill_csv: `reports\readiness_intake\2026_asof_20260630T000000_0000\market_snapshot_backfill.actions.csv`
- market_snapshot_backfill_jsonl: `reports\readiness_intake\2026_asof_20260630T000000_0000\market_snapshot_backfill.actions.jsonl`
- model_calibration_review_csv: `reports\readiness_intake\2026_asof_20260630T000000_0000\model_calibration_review.actions.csv`
- model_calibration_review_jsonl: `reports\readiness_intake\2026_asof_20260630T000000_0000\model_calibration_review.actions.jsonl`
- source_archive_proof_csv: `reports\readiness_intake\2026_asof_20260630T000000_0000\source_archive_proof.actions.csv`
- source_archive_proof_jsonl: `reports\readiness_intake\2026_asof_20260630T000000_0000\source_archive_proof.actions.jsonl`
- workstreams_csv: `reports\readiness_intake\2026_asof_20260630T000000_0000\workstreams.csv`

## Verification

After filling or replacing queued inputs, re-run the verifier:

```powershell
python -m f1predict.cli verify-readiness-intake --year 2026 --as-of 2026-06-30T00:00:00+00:00 --write
```

The verifier compares this exported queue with the current readiness state and marks rows as open, resolved, or new.

For market-related rows, scan Polymarket candidates before manual price-history backfill:

```powershell
python -m f1predict.cli scan-readiness-markets --year 2026 --as-of 2026-06-30T00:00:00+00:00 --include-closed --write
```

This bundle is an intake queue, not a formal backtest result. Resolve the blocking rows, re-run formal-readiness, calibration, and replay-freeze-manifest before promoting any edge claim.
