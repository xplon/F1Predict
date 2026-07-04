"""Export formal-readiness actions into assignable intake bundles."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now
from f1predict.pipeline import PredictionPipeline
from f1predict.readiness import FormalReadinessAction, FormalReadinessBuilder, FormalReadinessReport, FormalReadinessWorkstream
from f1predict.replay_artifacts import replay_stem


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def _ordered_unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


@dataclass(frozen=True)
class ReadinessIntakeBundle:
    year: int
    as_of: str
    generated_at: str
    bundle_dir: str
    readiness_status: str
    formal_backtest_ready: bool
    blocking_action_count: int
    warning_action_count: int
    workstream_count: int
    action_count: int
    workstreams: tuple[dict[str, Any], ...]
    files: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "bundle_dir": self.bundle_dir,
            "readiness_status": self.readiness_status,
            "formal_backtest_ready": self.formal_backtest_ready,
            "blocking_action_count": self.blocking_action_count,
            "warning_action_count": self.warning_action_count,
            "workstream_count": self.workstream_count,
            "action_count": self.action_count,
            "workstreams": list(self.workstreams),
            "files": self.files,
        }


@dataclass(frozen=True)
class ReadinessIntakeVerificationReport:
    year: int
    as_of: str
    generated_at: str
    bundle_dir: str
    status: str
    readiness_status: str
    formal_backtest_ready: bool
    queued_action_count: int
    open_action_count: int
    resolved_action_count: int
    new_action_count: int
    open_blocking_action_count: int
    open_warning_action_count: int
    rows: tuple[dict[str, Any], ...]
    new_actions: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "bundle_dir": self.bundle_dir,
            "status": self.status,
            "readiness_status": self.readiness_status,
            "formal_backtest_ready": self.formal_backtest_ready,
            "queued_action_count": self.queued_action_count,
            "open_action_count": self.open_action_count,
            "resolved_action_count": self.resolved_action_count,
            "new_action_count": self.new_action_count,
            "open_blocking_action_count": self.open_blocking_action_count,
            "open_warning_action_count": self.open_warning_action_count,
            "rows": list(self.rows),
            "new_actions": list(self.new_actions),
        }


class ReadinessIntakeExporter:
    """Writes readiness workstreams as JSONL and CSV task queues."""

    CSV_FIELDS = (
        "queue_id",
        "workstream_id",
        "workstream_priority",
        "category",
        "event_id",
        "event_name",
        "action_id",
        "severity",
        "blocks_formal_claim",
        "required_by",
        "status",
        "summary",
        "acceptance_check",
        "first_command",
        "next_action_category",
        "blocker_codes_json",
        "warning_codes_json",
        "minimum_missing_requirements_json",
        "success_criteria_json",
        "command_templates_json",
        "details_json",
    )

    def __init__(self, pipeline: PredictionPipeline | None = None, reports_root: Path | str = Path("reports")) -> None:
        self.builder = FormalReadinessBuilder(pipeline or PredictionPipeline(iterations=1200))
        self.reports_root = Path(reports_root)

    def build(self, year: int, as_of: str) -> tuple[FormalReadinessReport, tuple[dict[str, Any], ...]]:
        report = self.builder.build(year, as_of)
        enrichment = self._load_enrichment_reports(year, as_of)
        rows: list[dict[str, Any]] = []
        for workstream in report.workstreams:
            for index, action in enumerate(workstream.actions, start=1):
                rows.append(self._enrich_action_row(self._action_row(workstream, action, index), enrichment))
        return report, tuple(rows)

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/readiness_intake"),
    ) -> ReadinessIntakeBundle:
        report, rows = self.build(year, as_of)
        bundle_dir = Path(output_dir) / f"{year}_asof_{self._stem_time(as_of)}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        files: dict[str, str] = {}
        all_actions_jsonl = bundle_dir / "actions.jsonl"
        self._write_jsonl(all_actions_jsonl, rows)
        files["actions_jsonl"] = str(all_actions_jsonl)

        workstreams_csv = bundle_dir / "workstreams.csv"
        self._write_workstreams_csv(workstreams_csv, report)
        files["workstreams_csv"] = str(workstreams_csv)

        for workstream in report.workstreams:
            workstream_rows = tuple(row for row in rows if row["workstream_id"] == workstream.workstream_id)
            jsonl_path = bundle_dir / f"{workstream.workstream_id}.actions.jsonl"
            csv_path = bundle_dir / f"{workstream.workstream_id}.actions.csv"
            self._write_jsonl(jsonl_path, workstream_rows)
            self._write_actions_csv(csv_path, workstream_rows)
            files[f"{workstream.workstream_id}_jsonl"] = str(jsonl_path)
            files[f"{workstream.workstream_id}_csv"] = str(csv_path)

        bundle = ReadinessIntakeBundle(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            bundle_dir=str(bundle_dir),
            readiness_status=report.status,
            formal_backtest_ready=report.formal_backtest_ready,
            blocking_action_count=report.blocking_action_count,
            warning_action_count=report.warning_action_count,
            workstream_count=len(report.workstreams),
            action_count=len(rows),
            workstreams=tuple(self._workstream_summary(workstream) for workstream in report.workstreams),
            files=files,
        )
        manifest_path = bundle_dir / "intake_manifest.json"
        manifest_path.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        files["manifest"] = str(manifest_path)

        readme_path = bundle_dir / "README.md"
        readme_path.write_text(self._readme(bundle), encoding="utf-8")
        files["readme"] = str(readme_path)
        return ReadinessIntakeBundle(
            year=bundle.year,
            as_of=bundle.as_of,
            generated_at=bundle.generated_at,
            bundle_dir=bundle.bundle_dir,
            readiness_status=bundle.readiness_status,
            formal_backtest_ready=bundle.formal_backtest_ready,
            blocking_action_count=bundle.blocking_action_count,
            warning_action_count=bundle.warning_action_count,
            workstream_count=bundle.workstream_count,
            action_count=bundle.action_count,
            workstreams=bundle.workstreams,
            files=files,
        )

    def _action_row(
        self,
        workstream: FormalReadinessWorkstream,
        action: FormalReadinessAction,
        index: int,
    ) -> dict[str, Any]:
        return {
            "queue_id": f"P{workstream.priority:02d}-{index:03d}-{action.action_id}",
            "workstream_id": workstream.workstream_id,
            "workstream_title": workstream.title,
            "workstream_priority": workstream.priority,
            "category": action.category,
            "event_id": action.event_id,
            "event_name": action.event_name,
            "action_id": action.action_id,
            "severity": action.severity,
            "blocks_formal_claim": action.blocks_formal_claim,
            "required_by": action.required_by,
            "status": "open",
            "next_action_category": "",
            "blocker_codes": [],
            "warning_codes": [],
            "minimum_missing_requirements": [],
            "summary": action.summary,
            "acceptance_check": self._acceptance_check(action),
            "success_criteria": list(workstream.success_criteria),
            "command_templates": list(action.command_templates),
            "details": action.details,
        }

    def _load_enrichment_reports(self, year: int, as_of: str) -> dict[str, Any]:
        stem = replay_stem(year, as_of)
        return {
            "market_readiness": self._read_optional_json(
                self.reports_root / "market_readiness" / f"{stem}.market_readiness.json"
            ),
            "source_archives": self._read_optional_json(
                self.reports_root / "source_archives" / "remaining_blockers_cdx_discovery.json"
            ),
            "source_replacements": self._read_optional_json(
                self.reports_root / "source_replacements" / "remaining_blockers.source_replacements.json"
            ),
        }

    @staticmethod
    def _read_optional_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _enrich_action_row(self, row: dict[str, Any], reports: dict[str, Any]) -> dict[str, Any]:
        category = row.get("category")
        if category in {"market_snapshot_required", "after_cutoff_market_replacement"}:
            return self._enrich_market_action(row, reports.get("market_readiness") or {})
        if category == "source_archive_required":
            return self._enrich_source_action(
                row,
                reports.get("source_archives") or {},
                reports.get("source_replacements") or {},
            )
        return row

    def _enrich_market_action(self, row: dict[str, Any], market_report: dict[str, Any]) -> dict[str, Any]:
        event_id = str(row.get("event_id") or "")
        market_row = next(
            (item for item in market_report.get("rows", []) if isinstance(item, dict) and item.get("event_id") == event_id),
            None,
        )
        if not market_row:
            return row
        blocker_codes = _json_list(market_row.get("blocker_codes_json"))
        warning_codes = _json_list(market_row.get("warning_codes_json"))
        missing = _json_list(market_row.get("minimum_missing_requirements_json"))
        if not blocker_codes and row.get("blocks_formal_claim"):
            blocker_codes = self._fallback_market_blocker_codes(row, market_row)
        if not warning_codes:
            warning_codes = self._fallback_market_warning_codes(row, market_row)
        if not missing:
            missing = self._fallback_market_missing_requirements(row, blocker_codes, market_row)
        action_category = market_row.get("next_action_category") or self._fallback_market_action_category(
            blocker_codes,
            warning_codes,
        )
        enrichment = {
            "source": "market_readiness_report",
            "status": market_row.get("status"),
            "next_action": market_row.get("next_action"),
            "next_action_category": action_category,
            "blocker_codes": blocker_codes,
            "warning_codes": warning_codes,
            "minimum_missing_requirements": missing,
            "review_summary": market_row.get("review_summary"),
            "top_issue_code": market_row.get("backfill_top_issue_code") or market_row.get("top_issue_code"),
            "backfill_attempted": bool(market_row.get("backfill_attempted")),
            "backfill_output_path": market_row.get("backfill_output_path"),
        }
        return self._row_with_enrichment(row, enrichment)

    @staticmethod
    def _fallback_market_blocker_codes(row: dict[str, Any], market_row: dict[str, Any]) -> list[str]:
        codes = ["same_time_winner_snapshot_missing"]
        status = str(market_row.get("status") or "")
        top_issue = str(market_row.get("backfill_top_issue_code") or market_row.get("top_issue_code") or "")
        if status in {"backfill_attempted_no_winner_definitions", "no_candidate_markets"}:
            codes.append("winner_market_definition_missing")
        if status == "no_candidate_markets":
            codes.append("winner_market_not_found")
        if top_issue == "season_mismatch":
            codes.extend(["mismatched_season_markets_rejected", "same_season_winner_definition_missing"])
        if int(market_row.get("backfill_cutoff_valid_snapshot_count") or 0) == 0:
            codes.append("cutoff_valid_winner_snapshot_missing")
        return _ordered_unique(codes)

    @staticmethod
    def _fallback_market_warning_codes(row: dict[str, Any], market_row: dict[str, Any]) -> list[str]:
        codes: list[str] = []
        if row.get("category") == "after_cutoff_market_replacement":
            codes.append("after_cutoff_market_replacement_warning")
        if int(market_row.get("alternative_definition_count") or 0):
            codes.append("diagnostic_non_winner_market_definitions_available")
        if int(market_row.get("alternative_snapshot_count") or 0):
            codes.append("diagnostic_non_winner_snapshots_available")
        return _ordered_unique(codes)

    @staticmethod
    def _fallback_market_action_category(blocker_codes: list[str], warning_codes: list[str]) -> str:
        codes = set(blocker_codes)
        if "same_season_winner_definition_missing" in codes:
            return "find_same_season_winner_definition"
        if "winner_market_definition_missing" in codes:
            return "find_winner_market_definition"
        if "cutoff_valid_winner_snapshot_missing" in codes:
            return "backfill_winner_price_history"
        if "diagnostic_non_winner_market_definitions_available" in warning_codes:
            return "backfill_diagnostic_alternative_market"
        if "after_cutoff_market_replacement_warning" in warning_codes:
            return "review_after_cutoff_market_exclusion"
        return "manual_market_review"

    @staticmethod
    def _fallback_market_missing_requirements(
        row: dict[str, Any],
        blocker_codes: list[str],
        market_row: dict[str, Any],
    ) -> list[str]:
        event_name = str(row.get("event_name") or row.get("event_id") or "the event")
        cutoff = str(row.get("required_by") or "the event cutoff")
        requirements: list[str] = []
        codes = set(blocker_codes)
        if "same_time_winner_snapshot_missing" in codes:
            requirements.append(f"{event_name} needs a winner-market snapshot captured at or before {cutoff}")
        if "same_season_winner_definition_missing" in codes:
            requirements.append("search or import an independently reviewed same-season winner market definition")
        if "winner_market_definition_missing" in codes:
            requirements.append("a reviewed race-winner market definition with driver token mapping is required")
        if "cutoff_valid_winner_snapshot_missing" in codes:
            requirements.append("price history must include a cutoff-valid snapshot for the reviewed winner market")
        return _ordered_unique(requirements)

    def _enrich_source_action(
        self,
        row: dict[str, Any],
        source_report: dict[str, Any],
        replacement_report: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = str(row.get("event_id") or "")
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        source_index = details.get("source_index")
        original_url = str(details.get("url") or "")
        source_row = next(
            (
                item
                for item in source_report.get("rows", [])
                if isinstance(item, dict)
                and item.get("event_id") == event_id
                and (
                    source_index is None
                    or item.get("source_index") == source_index
                    or str(item.get("url") or "") == original_url
                )
            ),
            None,
        )
        candidates = [
            item
            for item in replacement_report.get("rows", [])
            if isinstance(item, dict)
            and item.get("event_id") == event_id
            and (
                source_index is None
                or item.get("source_index") == source_index
                or str(item.get("original_url") or "") == original_url
            )
        ]
        if not source_row and not candidates:
            return row
        blocker_codes = _ordered_unique(
            code
            for candidate in candidates
            for code in candidate.get("blocker_codes", [])
            if code
        )
        missing = _ordered_unique(
            requirement
            for candidate in candidates
            for requirement in candidate.get("minimum_missing_requirements", [])
            if requirement
        )
        best_candidate = self._best_source_candidate(candidates)
        action_category = best_candidate.get("next_action_category") if best_candidate else ""
        if not action_category:
            action_category = "find_cutoff_archive"
        commands = list(row.get("command_templates") or [])
        if best_candidate:
            for command in best_candidate.get("command_templates", []):
                if command and command not in commands:
                    commands.append(command)
        enrichment = {
            "source": "source_archive_and_replacement_reports",
            "source_status": source_row.get("status") if source_row else "",
            "source_next_action": source_row.get("next_action") if source_row else "",
            "next_action_category": action_category,
            "blocker_codes": blocker_codes or ["cutoff_archive_missing"],
            "warning_codes": [],
            "minimum_missing_requirements": missing or list((source_row or {}).get("acceptance_criteria") or []),
            "candidate_count": len(candidates),
            "best_candidate_id": best_candidate.get("candidate_id") if best_candidate else "",
            "best_candidate_status": best_candidate.get("status") if best_candidate else "",
            "review_summary": best_candidate.get("review_summary") if best_candidate else (source_row or {}).get("review_summary"),
        }
        enriched = self._row_with_enrichment(row, enrichment)
        enriched["command_templates"] = commands
        return enriched

    @staticmethod
    def _best_source_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            return {}
        priority = {
            "apply_ready_candidate": 0,
            "find_cutoff_archive": 1,
            "review_current_content": 2,
            "review_current_content_and_find_archive": 3,
            "find_archive_after_evidence_time": 4,
            "review_archive_content": 5,
            "retry_lookup": 6,
        }
        return min(
            candidates,
            key=lambda candidate: (
                priority.get(str(candidate.get("next_action_category") or ""), 99),
                str(candidate.get("candidate_id") or ""),
            ),
        )

    @staticmethod
    def _row_with_enrichment(row: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
        details = dict(row.get("details") or {})
        details["readiness_enrichment"] = enrichment
        row = dict(row)
        row["next_action_category"] = enrichment.get("next_action_category") or row.get("next_action_category") or ""
        row["blocker_codes"] = list(enrichment.get("blocker_codes") or row.get("blocker_codes") or [])
        row["warning_codes"] = list(enrichment.get("warning_codes") or row.get("warning_codes") or [])
        row["minimum_missing_requirements"] = list(
            enrichment.get("minimum_missing_requirements") or row.get("minimum_missing_requirements") or []
        )
        row["details"] = details
        return row

    @staticmethod
    def _acceptance_check(action: FormalReadinessAction) -> str:
        if action.category == "market_snapshot_required":
            return "Archive a cutoff-valid model-supported market snapshot, using archive-reviewed-market-snapshot for manual/Codex-reviewed inputs, and verify formal-readiness no longer emits this action_id."
        if action.category == "after_cutoff_market_replacement":
            return "Replace or exclude after-cutoff rows and verify replay analysis has no usable post-cutoff market input."
        if action.category == "source_archive_required":
            return "Attach a cutoff-valid historical_archive proof or replacement source and verify source audit passes."
        if action.category == "model_calibration_review":
            return "Re-run prediction and calibration after blocking input gaps are fixed; record whether the miss remains."
        return "Resolve the action, re-run formal-readiness, and verify this action_id is absent or downgraded."

    @staticmethod
    def _workstream_summary(workstream: FormalReadinessWorkstream) -> dict[str, Any]:
        return {
            "workstream_id": workstream.workstream_id,
            "title": workstream.title,
            "priority": workstream.priority,
            "category": workstream.category,
            "severity": workstream.severity,
            "blocks_formal_claim": workstream.blocks_formal_claim,
            "blocking_action_count": workstream.blocking_action_count,
            "warning_action_count": workstream.warning_action_count,
            "event_ids": list(workstream.event_ids),
            "success_criteria": list(workstream.success_criteria),
        }

    def _write_jsonl(self, path: Path, rows: tuple[dict[str, Any], ...]) -> None:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def _write_actions_csv(self, path: Path, rows: tuple[dict[str, Any], ...]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(self._csv_row(row))

    @staticmethod
    def _write_workstreams_csv(path: Path, report: FormalReadinessReport) -> None:
        fields = (
            "workstream_id",
            "priority",
            "category",
            "title",
            "severity",
            "blocks_formal_claim",
            "blocking_action_count",
            "warning_action_count",
            "event_ids",
            "success_criteria_json",
        )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for workstream in report.workstreams:
                writer.writerow(
                    {
                        "workstream_id": workstream.workstream_id,
                        "priority": workstream.priority,
                        "category": workstream.category,
                        "title": workstream.title,
                        "severity": workstream.severity,
                        "blocks_formal_claim": workstream.blocks_formal_claim,
                        "blocking_action_count": workstream.blocking_action_count,
                        "warning_action_count": workstream.warning_action_count,
                        "event_ids": ",".join(workstream.event_ids),
                        "success_criteria_json": json.dumps(list(workstream.success_criteria), ensure_ascii=False),
                    }
                )

    def _csv_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "queue_id": row["queue_id"],
            "workstream_id": row["workstream_id"],
            "workstream_priority": row["workstream_priority"],
            "category": row["category"],
            "event_id": row["event_id"],
            "event_name": row["event_name"],
            "action_id": row["action_id"],
            "severity": row["severity"],
            "blocks_formal_claim": row["blocks_formal_claim"],
            "required_by": row["required_by"] or "",
            "status": row["status"],
            "summary": row["summary"],
            "acceptance_check": row["acceptance_check"],
            "first_command": (row["command_templates"] or [""])[0],
            "next_action_category": row.get("next_action_category") or "",
            "blocker_codes_json": json.dumps(row.get("blocker_codes") or [], ensure_ascii=False),
            "warning_codes_json": json.dumps(row.get("warning_codes") or [], ensure_ascii=False),
            "minimum_missing_requirements_json": json.dumps(
                row.get("minimum_missing_requirements") or [],
                ensure_ascii=False,
            ),
            "success_criteria_json": json.dumps(row["success_criteria"], ensure_ascii=False),
            "command_templates_json": json.dumps(row["command_templates"], ensure_ascii=False),
            "details_json": json.dumps(row["details"], ensure_ascii=False, sort_keys=True),
        }

    @staticmethod
    def _readme(bundle: ReadinessIntakeBundle) -> str:
        lines = [
            f"# F1Predict Readiness Intake Bundle ({bundle.year})",
            "",
            f"- Replay cutoff: `{bundle.as_of}`",
            f"- Generated at: `{bundle.generated_at}`",
            f"- Readiness status: **{bundle.readiness_status}**",
            f"- Formal backtest ready: **{bundle.formal_backtest_ready}**",
            f"- Blocking actions: {bundle.blocking_action_count}",
            f"- Warning actions: {bundle.warning_action_count}",
            "",
            "## Workstreams",
            "",
        ]
        for workstream in bundle.workstreams:
            lines.append(
                f"- P{workstream['priority']} `{workstream['workstream_id']}`: "
                f"{workstream['blocking_action_count']} blocking, "
                f"{workstream['warning_action_count']} warning, "
                f"{len(workstream['event_ids'])} events"
            )
        lines.extend(
            [
                "",
                "## Files",
                "",
            ]
        )
        for label, path in sorted(bundle.files.items()):
            lines.append(f"- {label}: `{path}`")
        lines.extend(
            [
                "",
                "## Verification",
                "",
                "After filling or replacing queued inputs, re-run the verifier:",
                "",
                "```powershell",
                f"python -m f1predict.cli verify-readiness-intake --year {bundle.year} --as-of {bundle.as_of} --write",
                "```",
                "",
                "The verifier compares this exported queue with the current readiness state and marks rows as open, resolved, or new.",
                "",
                "For market-related rows, use the integrated Polymarket search/history backfill before rerunning the verifier:",
                "",
                "```powershell",
                f"python -m f1predict.cli scan-readiness-markets --year {bundle.year} --as-of {bundle.as_of} --include-closed --write",
                "python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type winner --include-closed --write --output reports\\market_normalization\\<event_id>_price_history.json --search-output reports\\market_normalization\\<event_id>_search_payload.json",
                "python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type constructor_double_podium --include-closed --write --output reports\\market_normalization\\<event_id>_constructor_double_podium_price_history.json --search-output reports\\market_normalization\\<event_id>_constructor_double_podium_search_payload.json",
                "python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type driver_h2h --include-closed --write --output reports\\market_normalization\\<event_id>_driver_h2h_price_history.json --search-output reports\\market_normalization\\<event_id>_driver_h2h_search_payload.json",
                "python -m f1predict.cli reviewed-market-template --event <event_id> --market-type winner > data\\research\\markets\\<event_id>_reviewed_winner_market.json",
                "python -m f1predict.cli archive-reviewed-market-snapshot --event <event_id> --input data\\research\\markets\\<event_id>_reviewed_winner_market.json --knowledge-cutoff <cutoff> --require-cutoff-valid",
                f"python -m f1predict.cli verify-readiness-intake --year {bundle.year} --as-of {bundle.as_of} --write",
                "```",
                "",
                "This bundle is an intake queue, not a formal backtest result. Resolve the blocking rows, re-run formal-readiness, calibration, and replay-freeze-manifest before promoting any edge claim.",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _stem_time(value: str) -> str:
        return value.replace(":", "").replace("+", "_").replace("-", "")


class ReadinessIntakeVerifier:
    """Compares an exported intake queue against the current readiness state."""

    CSV_FIELDS = (
        "queue_id",
        "action_id",
        "workstream_id",
        "event_id",
        "category",
        "verification_status",
        "still_blocks_formal_claim",
        "current_severity",
        "current_required_by",
        "summary",
        "acceptance_check",
    )

    def __init__(self, pipeline: PredictionPipeline | None = None) -> None:
        self.builder = FormalReadinessBuilder(pipeline or PredictionPipeline(iterations=1200))

    def verify(
        self,
        year: int,
        as_of: str,
        bundle_root: Path | str = Path("reports/readiness_intake"),
    ) -> ReadinessIntakeVerificationReport:
        bundle_dir = self._bundle_dir(year, as_of, bundle_root)
        queued_rows = self._read_jsonl(bundle_dir / "actions.jsonl")
        report = self.builder.build(year, as_of)
        current_actions = {
            action.action_id: action
            for event in report.events
            for action in event.actions
        }
        rows = tuple(self._verification_row(row, current_actions.get(str(row.get("action_id")))) for row in queued_rows)
        queued_ids = {str(row.get("action_id")) for row in queued_rows}
        new_actions = tuple(
            action.to_dict()
            for action_id, action in sorted(current_actions.items())
            if action_id not in queued_ids
        )
        open_rows = [row for row in rows if row["verification_status"] == "open"]
        resolved_rows = [row for row in rows if row["verification_status"] == "resolved"]
        open_blocking = sum(1 for row in open_rows if row["still_blocks_formal_claim"])
        status = self._status(len(open_rows), len(new_actions), report.formal_backtest_ready)
        return ReadinessIntakeVerificationReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            bundle_dir=str(bundle_dir),
            status=status,
            readiness_status=report.status,
            formal_backtest_ready=report.formal_backtest_ready,
            queued_action_count=len(queued_rows),
            open_action_count=len(open_rows),
            resolved_action_count=len(resolved_rows),
            new_action_count=len(new_actions),
            open_blocking_action_count=open_blocking,
            open_warning_action_count=len(open_rows) - open_blocking,
            rows=rows,
            new_actions=new_actions,
        )

    def write(
        self,
        year: int,
        as_of: str,
        bundle_root: Path | str = Path("reports/readiness_intake"),
    ) -> dict[str, Path]:
        report = self.verify(year, as_of, bundle_root)
        bundle_dir = Path(report.bundle_dir)
        json_path = bundle_dir / "verification.json"
        csv_path = bundle_dir / "verification.csv"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_csv(csv_path, report.rows)
        return {"json": json_path, "csv": csv_path}

    def _verification_row(
        self,
        queued: dict[str, Any],
        current: FormalReadinessAction | None,
    ) -> dict[str, Any]:
        if current is None:
            return {
                "queue_id": queued.get("queue_id"),
                "action_id": queued.get("action_id"),
                "workstream_id": queued.get("workstream_id"),
                "event_id": queued.get("event_id"),
                "category": queued.get("category"),
                "verification_status": "resolved",
                "still_blocks_formal_claim": False,
                "current_severity": None,
                "current_required_by": None,
                "summary": queued.get("summary"),
                "acceptance_check": queued.get("acceptance_check"),
            }
        return {
            "queue_id": queued.get("queue_id"),
            "action_id": queued.get("action_id"),
            "workstream_id": queued.get("workstream_id"),
            "event_id": queued.get("event_id"),
            "category": queued.get("category"),
            "verification_status": "open",
            "still_blocks_formal_claim": current.blocks_formal_claim,
            "current_severity": current.severity,
            "current_required_by": current.required_by,
            "summary": current.summary,
            "acceptance_check": queued.get("acceptance_check"),
        }

    def _write_csv(self, path: Path, rows: tuple[dict[str, Any], ...]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field) for field in self.CSV_FIELDS})

    @staticmethod
    def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        if not path.exists():
            raise FileNotFoundError(f"readiness intake actions file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return tuple(rows)

    @staticmethod
    def _bundle_dir(year: int, as_of: str, bundle_root: Path | str) -> Path:
        root = Path(bundle_root)
        if (root / "actions.jsonl").exists():
            return root
        return root / f"{year}_asof_{ReadinessIntakeExporter._stem_time(as_of)}"

    @staticmethod
    def _status(open_count: int, new_count: int, formal_backtest_ready: bool) -> str:
        if new_count:
            return "stale_queue_new_actions"
        if open_count:
            return "open_actions_remaining"
        if formal_backtest_ready:
            return "all_actions_resolved_formal_ready"
        return "all_queued_actions_resolved_but_inputs_not_formal"
