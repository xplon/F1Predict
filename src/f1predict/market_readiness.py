"""Market candidate scanning for readiness intake queues."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.data_sources.http_clients import PolymarketMarketClient
from f1predict.domain import SeasonState, utc_now
from f1predict.market_outcomes import CONSTRUCTOR_DOUBLE_PODIUM, DRIVER_H2H, WINNER
from f1predict.market_sources.polymarket import PolymarketSeasonSearchAuditor
from f1predict.pipeline import PredictionPipeline


MARKET_READINESS_CATEGORIES = {
    "market_snapshot_required",
    "after_cutoff_market_replacement",
}


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


@dataclass(frozen=True)
class ReadinessMarketScanReport:
    year: int
    as_of: str
    generated_at: str
    bundle_dir: str
    status: str
    market_type: str
    include_closed: bool
    limit: int
    action_count: int
    event_count: int
    query_count: int
    total_search_results: int
    events_with_search_results: int
    events_with_unique_markets: int
    events_with_snapshots: int
    events_with_definitions: int
    events_with_alternative_definitions: int
    alternative_definition_count: int
    blocking_event_count: int
    warning_event_count: int
    warning_only_event_count: int
    unresolved_event_count: int
    blocking_unresolved_event_count: int
    warning_only_unresolved_event_count: int
    blocker_code_counts: dict[str, int]
    warning_code_counts: dict[str, int]
    next_action_category_counts: dict[str, int]
    rows: tuple[dict[str, Any], ...]
    search_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "bundle_dir": self.bundle_dir,
            "status": self.status,
            "market_type": self.market_type,
            "include_closed": self.include_closed,
            "limit": self.limit,
            "action_count": self.action_count,
            "event_count": self.event_count,
            "query_count": self.query_count,
            "total_search_results": self.total_search_results,
            "events_with_search_results": self.events_with_search_results,
            "events_with_unique_markets": self.events_with_unique_markets,
            "events_with_snapshots": self.events_with_snapshots,
            "events_with_definitions": self.events_with_definitions,
            "events_with_alternative_definitions": self.events_with_alternative_definitions,
            "alternative_definition_count": self.alternative_definition_count,
            "blocking_event_count": self.blocking_event_count,
            "warning_event_count": self.warning_event_count,
            "warning_only_event_count": self.warning_only_event_count,
            "unresolved_event_count": self.unresolved_event_count,
            "blocking_unresolved_event_count": self.blocking_unresolved_event_count,
            "warning_only_unresolved_event_count": self.warning_only_unresolved_event_count,
            "blocker_code_counts": self.blocker_code_counts,
            "warning_code_counts": self.warning_code_counts,
            "next_action_category_counts": self.next_action_category_counts,
            "rows": list(self.rows),
            "search_report": self.search_report,
        }


@dataclass(frozen=True)
class CombinedAlternativeMarketRow:
    snapshot_count: int
    definition_count: int
    definitions: tuple[Any, ...]
    issues: tuple[Any, ...]


class ReadinessMarketScanner:
    """Scans Polymarket candidates for market-related readiness actions."""

    CSV_FIELDS = (
        "event_id",
        "event_name",
        "action_ids",
        "categories",
        "blocks_formal_claim",
        "blocking_action_count",
        "warning_action_count",
        "warning_only",
        "required_by",
        "status",
        "query_count",
        "search_result_count",
        "unique_market_count",
        "snapshot_count",
        "definition_count",
        "backfill_attempted",
        "backfill_output_path",
        "backfill_unique_market_count",
        "backfill_definition_count",
        "backfill_snapshot_count",
        "backfill_cutoff_valid_snapshot_count",
        "backfill_after_cutoff_snapshot_count",
        "backfill_top_issue_code",
        "backfill_issue_counts_json",
        "backfill_issue_examples_json",
        "issue_counts_json",
        "top_issue_code",
        "top_issue_detail",
        "review_summary",
        "next_action",
        "next_action_category",
        "blocker_codes_json",
        "warning_codes_json",
        "minimum_missing_requirements_json",
        "alternative_market_count",
        "alternative_snapshot_count",
        "alternative_definition_count",
        "alternative_market_counts_json",
        "alternative_market_types_json",
        "alternative_market_examples_json",
        "issue_examples_json",
        "first_query",
        "first_command",
    )

    def __init__(
        self,
        season: SeasonState | None = None,
        client: PolymarketMarketClient | None = None,
        market_normalization_dir: Path | str = Path("reports/market_normalization"),
    ) -> None:
        self.season = season or PredictionPipeline(iterations=1).data_source.load()
        self.client = client
        self.market_normalization_dir = Path(market_normalization_dir)

    def scan(
        self,
        year: int,
        as_of: str,
        bundle_root: Path | str = Path("reports/readiness_intake"),
        limit: int = 20,
        market_type: str = "winner",
        include_closed: bool = True,
    ) -> ReadinessMarketScanReport:
        bundle_dir = self._bundle_dir(year, as_of, bundle_root)
        actions = self._market_actions(bundle_dir / "actions.jsonl")
        events = self._event_summaries(actions)
        event_ids = tuple(events)
        search = PolymarketSeasonSearchAuditor(self.season, client=self.client).build(
            limit=limit,
            market_type=market_type,
            include_closed=include_closed,
            event_ids=event_ids,
        )
        search_by_event = {row.event_id: row for row in search.rows}
        alternative_search_by_event: dict[str, Any] = {}
        if market_type == WINNER:
            alternative_search_by_event = self._alternative_search_by_event(
                event_ids=event_ids,
                limit=limit,
                include_closed=include_closed,
            )
        rows = tuple(
            self._row(
                event_id,
                summary,
                search_by_event.get(event_id),
                alternative_search_by_event.get(event_id),
                self._matching_backfill_report(event_id, summary, market_type, self.market_normalization_dir),
            )
            for event_id, summary in events.items()
        )
        return ReadinessMarketScanReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            bundle_dir=str(bundle_dir),
            status=self._status(rows),
            market_type=market_type,
            include_closed=include_closed,
            limit=limit,
            action_count=len(actions),
            event_count=len(rows),
            query_count=sum(int(row["query_count"]) for row in rows),
            total_search_results=sum(int(row["search_result_count"]) for row in rows),
            events_with_search_results=sum(1 for row in rows if int(row["search_result_count"]) > 0),
            events_with_unique_markets=sum(1 for row in rows if int(row["unique_market_count"]) > 0),
            events_with_snapshots=sum(1 for row in rows if int(row["snapshot_count"]) > 0),
            events_with_definitions=sum(1 for row in rows if int(row["definition_count"]) > 0),
            events_with_alternative_definitions=sum(1 for row in rows if int(row["alternative_definition_count"]) > 0),
            alternative_definition_count=sum(int(row["alternative_definition_count"]) for row in rows),
            blocking_event_count=sum(1 for row in rows if row["blocks_formal_claim"]),
            warning_event_count=sum(1 for row in rows if int(row["warning_action_count"]) > 0),
            warning_only_event_count=sum(1 for row in rows if row["warning_only"]),
            unresolved_event_count=sum(1 for row in rows if self._row_unresolved(row)),
            blocking_unresolved_event_count=sum(
                1 for row in rows if row["blocks_formal_claim"] and self._row_unresolved(row)
            ),
            warning_only_unresolved_event_count=sum(1 for row in rows if row["warning_only"] and self._row_unresolved(row)),
            blocker_code_counts=self._row_code_counts(rows, "blocker_codes_json"),
            warning_code_counts=self._row_code_counts(rows, "warning_codes_json"),
            next_action_category_counts=self._row_action_category_counts(rows),
            rows=rows,
            search_report=search.to_dict(),
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/market_readiness"),
        bundle_root: Path | str = Path("reports/readiness_intake"),
        limit: int = 20,
        market_type: str = "winner",
        include_closed: bool = True,
    ) -> dict[str, Path]:
        report = self.scan(
            year=year,
            as_of=as_of,
            bundle_root=bundle_root,
            limit=limit,
            market_type=market_type,
            include_closed=include_closed,
        )
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        json_path = directory / f"{stem}.market_readiness.json"
        csv_path = directory / f"{stem}.market_readiness.csv"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            for row in report.rows:
                writer.writerow({field: row.get(field) for field in self.CSV_FIELDS})
        return {"json": json_path, "csv": csv_path}

    @staticmethod
    def _combine_alternative_rows(rows: list[Any]) -> CombinedAlternativeMarketRow:
        return CombinedAlternativeMarketRow(
            snapshot_count=sum(int(getattr(row, "snapshot_count", 0) or 0) for row in rows),
            definition_count=sum(int(getattr(row, "definition_count", 0) or 0) for row in rows),
            definitions=tuple(definition for row in rows for definition in getattr(row, "definitions", ())),
            issues=tuple(issue for row in rows for issue in getattr(row, "issues", ())),
        )

    def _alternative_search_by_event(
        self,
        event_ids: tuple[str, ...],
        limit: int,
        include_closed: bool,
    ) -> dict[str, CombinedAlternativeMarketRow]:
        rows_by_event: dict[str, list[Any]] = {event_id: [] for event_id in event_ids}
        auditor = PolymarketSeasonSearchAuditor(self.season, client=self.client)
        for market_type in (CONSTRUCTOR_DOUBLE_PODIUM, DRIVER_H2H):
            report = auditor.build(
                limit=limit,
                market_type=market_type,
                include_closed=include_closed,
                event_ids=event_ids,
            )
            for row in report.rows:
                rows_by_event.setdefault(row.event_id, []).append(row)
        return {
            event_id: self._combine_alternative_rows(rows)
            for event_id, rows in rows_by_event.items()
            if rows
        }

    @staticmethod
    def _market_actions(path: Path) -> tuple[dict[str, Any], ...]:
        if not path.exists():
            raise FileNotFoundError(f"readiness intake actions file not found: {path}")
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                if row.get("category") in MARKET_READINESS_CATEGORIES:
                    rows.append(row)
        return tuple(rows)

    @staticmethod
    def _event_summaries(actions: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
        events: dict[str, dict[str, Any]] = {}
        for action in actions:
            event_id = str(action.get("event_id") or "")
            if not event_id:
                continue
            summary = events.setdefault(
                event_id,
                {
                    "event_name": action.get("event_name"),
                    "action_ids": [],
                    "categories": [],
                    "blocking_action_count": 0,
                    "warning_action_count": 0,
                    "required_by": [],
                    "first_command": "",
                },
            )
            summary["action_ids"].append(action.get("action_id"))
            if action.get("blocks_formal_claim"):
                summary["blocking_action_count"] += 1
            else:
                summary["warning_action_count"] += 1
            category = action.get("category")
            if category not in summary["categories"]:
                summary["categories"].append(category)
            required_by = action.get("required_by")
            if required_by and required_by not in summary["required_by"]:
                summary["required_by"].append(required_by)
            if not summary["first_command"] and action.get("command_templates"):
                summary["first_command"] = action["command_templates"][0]
        return events

    @staticmethod
    def _row(
        event_id: str,
        summary: dict[str, Any],
        search_row: Any,
        alternative_search_row: Any = None,
        backfill_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        queries = tuple(search_row.queries) if search_row is not None else ()
        query_count = len(queries)
        search_result_count = sum(query.result_count for query in queries)
        unique_market_count = search_row.unique_market_count if search_row is not None else 0
        snapshot_count = search_row.snapshot_count if search_row is not None else 0
        definition_count = search_row.definition_count if search_row is not None else 0
        alternative_snapshot_count = alternative_search_row.snapshot_count if alternative_search_row is not None else 0
        alternative_definition_count = alternative_search_row.definition_count if alternative_search_row is not None else 0
        alternative_market_types = ReadinessMarketScanner._alternative_definition_counts(alternative_search_row)
        backfill_attempted = backfill_report is not None
        backfill_unique_market_count = int((backfill_report or {}).get("unique_market_count") or 0)
        backfill_definition_count = int((backfill_report or {}).get("definition_count") or 0)
        backfill_snapshot_count = int((backfill_report or {}).get("snapshot_count") or 0)
        backfill_cutoff_valid_snapshot_count = int((backfill_report or {}).get("cutoff_valid_snapshot_count") or 0)
        backfill_after_cutoff_snapshot_count = int((backfill_report or {}).get("after_cutoff_snapshot_count") or 0)
        backfill_issues = tuple((backfill_report or {}).get("issues") or ())
        backfill_issue_counts = ReadinessMarketScanner._dict_issue_counts(backfill_issues)
        backfill_top_issue = ReadinessMarketScanner._top_dict_issue(backfill_issue_counts, backfill_issues)
        backfill_issue_examples = ReadinessMarketScanner._dict_issue_examples(backfill_issues)
        category_values = ReadinessMarketScanner._summary_values(summary.get("categories", ()))
        blocking_action_count = int(summary.get("blocking_action_count") or 0)
        warning_action_count = int(summary.get("warning_action_count") or 0)
        if not blocking_action_count and "market_snapshot_required" in category_values:
            blocking_action_count = 1
        if not warning_action_count:
            warning_action_count = sum(
                1 for category in category_values if category in MARKET_READINESS_CATEGORIES and category != "market_snapshot_required"
            )
        blocks_formal_claim = blocking_action_count > 0
        warning_only = not blocks_formal_claim and warning_action_count > 0
        if definition_count:
            status = "candidate_definitions_found"
        elif alternative_definition_count:
            status = "alternative_definitions_found"
        elif backfill_attempted and backfill_cutoff_valid_snapshot_count:
            status = "cutoff_snapshots_backfilled"
        elif backfill_attempted and not backfill_definition_count:
            status = "backfill_attempted_no_winner_definitions"
        elif unique_market_count:
            status = "search_results_need_review"
        elif any(query.error for query in queries):
            status = "search_errors"
        else:
            status = "no_candidate_markets"
        first_query = queries[0].query if queries else ""
        issue_counts = search_row.issue_counts if search_row is not None else {}
        issues = tuple(search_row.issues) if search_row is not None else ()
        top_issue = ReadinessMarketScanner._top_issue(issue_counts, issues)
        issue_examples = ReadinessMarketScanner._issue_examples(issues)
        alternative_markets = ReadinessMarketScanner._alternative_market_candidates(issues)
        alternative_counts = ReadinessMarketScanner._alternative_market_counts(alternative_markets)
        alternative_count = sum(alternative_counts.values())
        if not definition_count and not alternative_definition_count and alternative_count:
            status = "alternative_markets_need_model_support"
        review_summary = ReadinessMarketScanner._review_summary(
            status=status,
            query_count=query_count,
            search_result_count=search_result_count,
            unique_market_count=unique_market_count,
            snapshot_count=snapshot_count,
            definition_count=definition_count,
            top_issue=top_issue,
            alternative_count=alternative_count,
            alternative_counts=alternative_counts,
            alternative_definition_count=alternative_definition_count,
            alternative_market_types=alternative_market_types,
            backfill_attempted=backfill_attempted,
            backfill_unique_market_count=backfill_unique_market_count,
            backfill_definition_count=backfill_definition_count,
            backfill_snapshot_count=backfill_snapshot_count,
            backfill_cutoff_valid_snapshot_count=backfill_cutoff_valid_snapshot_count,
            backfill_issue_counts=backfill_issue_counts,
            backfill_top_issue=backfill_top_issue,
        )
        next_action = ReadinessMarketScanner._next_action(
            status=status,
            top_issue=top_issue,
            event_id=event_id,
            required_by=",".join(str(value) for value in summary.get("required_by", ()) if value),
            alternative_counts=alternative_counts,
            alternative_market_types=alternative_market_types,
            backfill_attempted=backfill_attempted,
            backfill_top_issue=backfill_top_issue,
        )
        row = {
            "event_id": event_id,
            "event_name": summary.get("event_name") or (search_row.event_name if search_row else ""),
            "action_ids": ",".join(str(value) for value in summary.get("action_ids", ()) if value),
            "categories": ",".join(str(value) for value in summary.get("categories", ()) if value),
            "blocks_formal_claim": blocks_formal_claim,
            "blocking_action_count": blocking_action_count,
            "warning_action_count": warning_action_count,
            "warning_only": warning_only,
            "required_by": ",".join(str(value) for value in summary.get("required_by", ()) if value),
            "status": status,
            "query_count": query_count,
            "search_result_count": search_result_count,
            "unique_market_count": unique_market_count,
            "snapshot_count": snapshot_count,
            "definition_count": definition_count,
            "backfill_attempted": backfill_attempted,
            "backfill_output_path": str((backfill_report or {}).get("output") or ""),
            "backfill_unique_market_count": backfill_unique_market_count,
            "backfill_definition_count": backfill_definition_count,
            "backfill_snapshot_count": backfill_snapshot_count,
            "backfill_cutoff_valid_snapshot_count": backfill_cutoff_valid_snapshot_count,
            "backfill_after_cutoff_snapshot_count": backfill_after_cutoff_snapshot_count,
            "backfill_top_issue_code": backfill_top_issue.get("code", ""),
            "backfill_issue_counts_json": json.dumps(backfill_issue_counts, ensure_ascii=False, sort_keys=True),
            "backfill_issue_examples_json": json.dumps(backfill_issue_examples, ensure_ascii=False),
            "issue_counts_json": json.dumps(issue_counts, ensure_ascii=False, sort_keys=True),
            "top_issue_code": top_issue.get("code", ""),
            "top_issue_detail": top_issue.get("detail", ""),
            "review_summary": review_summary,
            "next_action": next_action,
            "alternative_market_count": alternative_count,
            "alternative_snapshot_count": alternative_snapshot_count,
            "alternative_definition_count": alternative_definition_count,
            "alternative_market_counts_json": json.dumps(alternative_counts, ensure_ascii=False, sort_keys=True),
            "alternative_market_types_json": json.dumps(alternative_market_types, ensure_ascii=False, sort_keys=True),
            "alternative_market_examples_json": json.dumps(alternative_markets[:3], ensure_ascii=False),
            "issue_examples_json": json.dumps(issue_examples, ensure_ascii=False),
            "first_query": first_query,
            "first_command": summary.get("first_command") or "",
        }
        blocker_codes = ReadinessMarketScanner._market_blocker_codes(row)
        warning_codes = ReadinessMarketScanner._market_warning_codes(row)
        row.update(
            {
                "next_action_category": ReadinessMarketScanner._market_next_action_category(row, blocker_codes, warning_codes),
                "blocker_codes_json": json.dumps(blocker_codes, ensure_ascii=False),
                "warning_codes_json": json.dumps(warning_codes, ensure_ascii=False),
                "minimum_missing_requirements_json": json.dumps(
                    ReadinessMarketScanner._market_missing_requirements(row, blocker_codes),
                    ensure_ascii=False,
                ),
            }
        )
        return row

    @staticmethod
    def _top_issue(issue_counts: dict[str, int], issues: tuple[Any, ...]) -> dict[str, str]:
        if not issue_counts:
            return {}
        code = max(issue_counts.items(), key=lambda item: (int(item[1]), item[0]))[0]
        issue = next((item for item in issues if item.code == code), None)
        if issue is None:
            return {"code": code, "detail": "", "question": ""}
        return {
            "code": issue.code,
            "detail": issue.detail,
            "question": issue.question,
        }

    @staticmethod
    def _issue_examples(issues: tuple[Any, ...], limit: int = 3) -> list[dict[str, str]]:
        examples = []
        seen: set[tuple[str, str]] = set()
        for issue in issues:
            key = (str(issue.code), str(issue.question))
            if key in seen:
                continue
            seen.add(key)
            examples.append(
                {
                    "code": str(issue.code),
                    "severity": str(issue.severity),
                    "question": str(issue.question),
                    "detail": str(issue.detail),
                }
            )
            if len(examples) >= limit:
                break
        return examples

    @staticmethod
    def _review_summary(
        status: str,
        query_count: int,
        search_result_count: int,
        unique_market_count: int,
        snapshot_count: int,
        definition_count: int,
        top_issue: dict[str, str],
        alternative_count: int = 0,
        alternative_counts: dict[str, int] | None = None,
        alternative_definition_count: int = 0,
        alternative_market_types: dict[str, int] | None = None,
        backfill_attempted: bool = False,
        backfill_unique_market_count: int = 0,
        backfill_definition_count: int = 0,
        backfill_snapshot_count: int = 0,
        backfill_cutoff_valid_snapshot_count: int = 0,
        backfill_issue_counts: dict[str, int] | None = None,
        backfill_top_issue: dict[str, str] | None = None,
    ) -> str:
        if definition_count:
            return (
                f"{definition_count} candidate driver-token definitions were found; "
                "review and backfill price history before archiving a cutoff snapshot."
            )
        if alternative_definition_count:
            types = alternative_market_types or {}
            families = ", ".join(f"{key}: {value}" for key, value in sorted(types.items()))
            return (
                f"{alternative_definition_count} supported non-winner market definitions were found "
                f"({families}); backfill cutoff price history before using them for diagnostic edge comparison."
            )
        if alternative_count:
            counts = alternative_counts or {}
            families = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
            return (
                f"{alternative_count} same-season non-winner market candidates were found "
                f"({families}); they need explicit model-output and normalizer support before edge comparison."
            )
        if backfill_cutoff_valid_snapshot_count:
            return (
                f"Integrated search/history backfill produced {backfill_cutoff_valid_snapshot_count} "
                "cutoff-valid snapshots; rerun formal-readiness to verify whether the action is resolved."
            )
        if backfill_attempted:
            issue = (backfill_top_issue or {}).get("code") or "no_winner_definitions"
            if issue == "season_mismatch":
                mismatch_count = int((backfill_issue_counts or {}).get("season_mismatch") or 0)
                return (
                    "Integrated search/history backfill was attempted, but it produced no cutoff-usable "
                    f"winner snapshot. It found {backfill_unique_market_count} unique Polymarket candidates; "
                    f"{mismatch_count} candidate issues were mismatched-season rejections, so no reviewed "
                    "2026 race-winner definition is available from this source."
                )
            return (
                "Integrated search/history backfill was attempted, but it produced no cutoff-usable "
                f"winner snapshot (definitions={backfill_definition_count}, snapshots={backfill_snapshot_count}); "
                f"dominant issue: {issue}."
            )
        if snapshot_count:
            return (
                f"{snapshot_count} candidate snapshots were found; verify cutoff timing "
                "and archive only if market rules match the target race."
            )
        if unique_market_count:
            issue = top_issue.get("code") or "normalization_issue"
            return (
                f"{unique_market_count} unique markets were found across {query_count} queries, "
                "but none normalized into a cutoff-usable winner snapshot; "
                f"dominant issue: {issue}."
            )
        if search_result_count:
            return (
                f"{search_result_count} raw search results were returned, but none survived "
                "event and market normalization."
            )
        return "No candidate markets were returned by the configured Polymarket searches."

    @staticmethod
    def _next_action(
        status: str,
        top_issue: dict[str, str],
        event_id: str,
        required_by: str,
        alternative_counts: dict[str, int] | None = None,
        alternative_market_types: dict[str, int] | None = None,
        backfill_attempted: bool = False,
        backfill_top_issue: dict[str, str] | None = None,
    ) -> str:
        if status == "cutoff_snapshots_backfilled":
            return "Rerun formal-readiness and replay-analysis to verify whether the cutoff-valid market snapshot now resolves this action."
        if status == "backfill_attempted_no_winner_definitions":
            issue_code = (backfill_top_issue or {}).get("code") or top_issue.get("code")
            if issue_code == "season_mismatch":
                return (
                    "Document that the integrated search found mismatched-season markets, then either keep the "
                    "winner-market action open or create a reviewed-market-template packet for an independently "
                    "verified 2026 race-winner source and archive it with archive-reviewed-market-snapshot."
                )
            return (
                "Document the no-winner-definition backfill attempt; keep the event market-unscored for formal edge "
                "unless a reviewed 2026 race-winner market source is normalized through archive-reviewed-market-snapshot."
            )
        issue_code = top_issue.get("code")
        if status == "candidate_definitions_found":
            return (
                f"Run search-backfill-polymarket-history --event {event_id} --knowledge-cutoff "
                f"{required_by or '<race-cutoff>'} --market-type winner --include-closed --write, "
                "then review the normalized cutoff-valid snapshots."
            )
        if status == "alternative_definitions_found":
            market_type = next(iter(sorted((alternative_market_types or {}).keys())), "constructor_double_podium")
            return (
                f"Run search-backfill-polymarket-history --event {event_id} --knowledge-cutoff "
                f"{required_by or '<race-cutoff>'} --market-type {market_type} --include-closed --write, "
                "then review the diagnostic non-winner market snapshots separately from formal winner-market readiness."
            )
        if status == "alternative_markets_need_model_support":
            families = ", ".join(sorted((alternative_counts or {}).keys())) or "non-winner markets"
            return (
                f"Add explicit model probability adapters and normalizers for {families}; "
                "until then, keep these markets out of winner edge scoring."
            )
        if issue_code == "season_mismatch":
            return (
                "Reject the mismatched-season markets; search for a 2026-specific winner market or normalize an "
                "independently reviewed historical price source through reviewed-market-template and "
                "archive-reviewed-market-snapshot."
            )
        if issue_code == "unsupported_market_type":
            return (
                "Reject non-winner markets for edge comparison; search for outright winner markets "
                "or keep this event market-unscored."
            )
        if issue_code == "no_matching_event_alias":
            return (
                "Add a reviewed event alias only if the market rules clearly name this race; "
                "otherwise keep the action open."
            )
        return (
            "Review candidate market rules and token mappings manually; do not archive a snapshot until event, "
            "season, market type, and cutoff timing all match, then use archive-reviewed-market-snapshot."
        )

    @staticmethod
    def _status(rows: tuple[dict[str, Any], ...]) -> str:
        if not rows:
            return "no_market_actions"
        primary_rows = tuple(row for row in rows if row.get("blocks_formal_claim")) or rows
        if any(row["status"] == "candidate_definitions_found" for row in primary_rows):
            return "candidate_definitions_found"
        if any(row["status"] == "alternative_definitions_found" for row in primary_rows):
            return "alternative_definitions_found"
        if any(row["status"] == "cutoff_snapshots_backfilled" for row in primary_rows):
            return "cutoff_snapshots_backfilled"
        if any(row["status"] == "backfill_attempted_no_winner_definitions" for row in primary_rows):
            return "backfill_attempted_no_winner_definitions"
        if any(row["status"] == "alternative_markets_need_model_support" for row in primary_rows):
            return "alternative_markets_need_model_support"
        if any(row["status"] == "search_results_need_review" for row in primary_rows):
            return "search_results_need_review"
        if any(row["status"] == "search_errors" for row in primary_rows):
            return "search_errors"
        return "no_candidate_markets"

    @staticmethod
    def _row_unresolved(row: dict[str, Any]) -> bool:
        return row.get("status") != "candidate_definitions_found"

    @staticmethod
    def _market_blocker_codes(row: dict[str, Any]) -> list[str]:
        if not row.get("blocks_formal_claim"):
            return []
        codes: list[str] = ["same_time_winner_snapshot_missing"]
        status = str(row.get("status") or "")
        top_issue = str(row.get("top_issue_code") or "")
        backfill_issue = str(row.get("backfill_top_issue_code") or "")
        issue_counts = ReadinessMarketScanner._json_dict(row.get("issue_counts_json"))
        backfill_issue_counts = ReadinessMarketScanner._json_dict(row.get("backfill_issue_counts_json"))
        definition_count = int(row.get("definition_count") or 0)
        snapshot_count = int(row.get("snapshot_count") or 0)
        backfill_definition_count = int(row.get("backfill_definition_count") or 0)
        backfill_snapshot_count = int(row.get("backfill_snapshot_count") or 0)
        backfill_cutoff_valid = int(row.get("backfill_cutoff_valid_snapshot_count") or 0)

        if status == "no_candidate_markets":
            codes.append("winner_market_not_found")
        elif status == "search_errors":
            codes.append("market_search_error")
        elif status == "search_results_need_review":
            codes.append("candidate_market_rules_need_review")
        elif status == "alternative_markets_need_model_support":
            codes.append("winner_market_model_support_missing")
        elif status == "backfill_attempted_no_winner_definitions":
            codes.append("winner_market_definition_missing")
            if not backfill_cutoff_valid:
                codes.append("cutoff_valid_winner_snapshot_missing")
        elif status == "candidate_definitions_found":
            if definition_count and not snapshot_count:
                codes.append("cutoff_price_history_missing")
        elif status == "cutoff_snapshots_backfilled":
            codes.append("readiness_rerun_required")

        if (
            top_issue == "season_mismatch"
            or backfill_issue == "season_mismatch"
            or int(issue_counts.get("season_mismatch") or 0)
            or int(backfill_issue_counts.get("season_mismatch") or 0)
        ):
            codes.append("mismatched_season_markets_rejected")
            codes.append("same_season_winner_definition_missing")
        if top_issue == "unsupported_market_type":
            codes.append("winner_market_not_supported_by_normalizer")
        if top_issue == "no_matching_event_alias":
            codes.append("event_alias_review_required")
        if status != "candidate_definitions_found" and not definition_count and not backfill_definition_count:
            codes.append("winner_market_definition_missing")
        if (
            row.get("backfill_attempted")
            and not backfill_cutoff_valid
            and (backfill_snapshot_count or int(row.get("backfill_after_cutoff_snapshot_count") or 0))
        ):
            codes.append("cutoff_valid_winner_snapshot_missing")
        return _ordered_unique(codes)

    @staticmethod
    def _market_warning_codes(row: dict[str, Any]) -> list[str]:
        codes: list[str] = []
        alternative_definition_count = int(row.get("alternative_definition_count") or 0)
        alternative_market_count = int(row.get("alternative_market_count") or 0)
        alternative_snapshot_count = int(row.get("alternative_snapshot_count") or 0)
        if row.get("warning_only"):
            codes.append("non_blocking_market_action")
        if alternative_definition_count:
            codes.append("diagnostic_non_winner_market_definitions_available")
        elif alternative_market_count:
            codes.append("unsupported_non_winner_market_candidates_available")
        if alternative_snapshot_count:
            codes.append("diagnostic_non_winner_snapshots_available")
        if int(row.get("backfill_after_cutoff_snapshot_count") or 0):
            codes.append("after_cutoff_winner_snapshots_excluded")
        categories = ReadinessMarketScanner._summary_values(row.get("categories"))
        if "after_cutoff_market_replacement" in categories:
            codes.append("after_cutoff_market_replacement_warning")
        return _ordered_unique(codes)

    @staticmethod
    def _market_next_action_category(row: dict[str, Any], blocker_codes: list[str], warning_codes: list[str]) -> str:
        status = str(row.get("status") or "")
        codes = set(blocker_codes)
        if status == "cutoff_snapshots_backfilled":
            return "rerun_formal_readiness"
        if "market_search_error" in codes:
            return "retry_market_search"
        if "same_season_winner_definition_missing" in codes:
            return "find_same_season_winner_definition"
        if "winner_market_definition_missing" in codes:
            return "find_winner_market_definition"
        if "candidate_market_rules_need_review" in codes:
            return "review_market_rules"
        if "cutoff_price_history_missing" in codes or "cutoff_valid_winner_snapshot_missing" in codes:
            return "backfill_winner_price_history"
        if "winner_market_not_supported_by_normalizer" in codes:
            return "find_supported_winner_market"
        if "event_alias_review_required" in codes:
            return "review_event_alias"
        if "winner_market_model_support_missing" in codes:
            return "add_market_model_support"
        if "winner_market_not_found" in codes:
            return "broaden_market_search"
        if "diagnostic_non_winner_market_definitions_available" in warning_codes:
            return "backfill_diagnostic_alternative_market"
        if "unsupported_non_winner_market_candidates_available" in warning_codes:
            return "add_alternative_market_support"
        return "manual_market_review"

    @staticmethod
    def _market_missing_requirements(row: dict[str, Any], blocker_codes: list[str]) -> list[str]:
        requirements: list[str] = []
        cutoff = str(row.get("required_by") or "the event cutoff")
        event_name = str(row.get("event_name") or row.get("event_id") or "the event")
        codes = set(blocker_codes)
        if "same_time_winner_snapshot_missing" in codes:
            requirements.append(f"{event_name} needs a winner-market snapshot captured at or before {cutoff}")
        if "winner_market_not_found" in codes:
            requirements.append("Polymarket search must find a market whose rules clearly resolve the target race winner")
        if "market_search_error" in codes:
            requirements.append("market search must complete successfully before readiness can be assessed")
        if "candidate_market_rules_need_review" in codes:
            requirements.append("candidate market rules must be manually reviewed for event, season, market type, and token mapping")
        if "winner_market_definition_missing" in codes:
            requirements.append("a reviewed 2026 race-winner market definition with driver token mapping is required")
        if "mismatched_season_markets_rejected" in codes:
            requirements.append("mismatched-season markets must remain rejected and cannot fill the 2026 replay cutoff")
        if "same_season_winner_definition_missing" in codes:
            requirements.append("search or import an independently reviewed same-season winner market through archive-reviewed-market-snapshot")
        if "cutoff_valid_winner_snapshot_missing" in codes:
            requirements.append("price history or reviewed-market packet must include a cutoff-valid snapshot for the reviewed winner market")
        if "cutoff_price_history_missing" in codes:
            requirements.append("run historical price backfill for the reviewed winner market before using it in edge scoring")
        if "winner_market_not_supported_by_normalizer" in codes:
            requirements.append("only supported winner markets can enter formal winner-edge comparison")
        if "event_alias_review_required" in codes:
            requirements.append("add an event alias only when market rules explicitly name the target race")
        if "winner_market_model_support_missing" in codes:
            requirements.append("add model-output and normalizer support before using non-winner markets for edge scoring")
        if "readiness_rerun_required" in codes:
            requirements.append("rerun formal-readiness and replay analysis after backfilled snapshots are written")
        return _ordered_unique(requirements)

    @staticmethod
    def _row_code_counts(rows: tuple[dict[str, Any], ...], field: str) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for row in rows:
            counter.update(ReadinessMarketScanner._json_list(row.get(field)))
        return dict(sorted(counter.items()))

    @staticmethod
    def _row_action_category_counts(rows: tuple[dict[str, Any], ...]) -> dict[str, int]:
        counter: Counter[str] = Counter(str(row.get("next_action_category") or "manual_market_review") for row in rows)
        return dict(sorted(counter.items()))

    @staticmethod
    def _json_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed]

    @staticmethod
    def _summary_values(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(part) for part in value if part)
        return ()

    @staticmethod
    def _alternative_market_candidates(issues: tuple[Any, ...]) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for issue in issues:
            if getattr(issue, "code", "") != "unsupported_market_type":
                continue
            question = str(getattr(issue, "question", "") or "")
            family = ReadinessMarketScanner._alternative_market_family(question)
            key = (family["market_family"], question)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "market_family": family["market_family"],
                    "model_requirement": family["model_requirement"],
                    "normalizer_requirement": family["normalizer_requirement"],
                    "question": question,
                    "detail": str(getattr(issue, "detail", "") or ""),
                }
            )
        return candidates

    @staticmethod
    def _alternative_market_counts(candidates: list[dict[str, str]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for candidate in candidates:
            family = candidate.get("market_family") or "other_non_winner"
            counts[family] = counts.get(family, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _alternative_definition_counts(search_row: Any) -> dict[str, int]:
        if search_row is None:
            return {}
        counts: dict[str, int] = {}
        for definition in getattr(search_row, "definitions", ()):
            market_type = str(getattr(definition, "market_type", "") or "unknown")
            counts[market_type] = counts.get(market_type, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _alternative_market_family(question: str) -> dict[str, str]:
        text = question.lower()
        if "double podium" in text:
            return {
                "market_family": "constructor_double_podium",
                "model_requirement": "sampled finishing-order distribution with team-level podium co-occurrence",
                "normalizer_requirement": "map constructor outcomes to team_id and Yes token prices",
            }
        if "constructor" in text and "2nd most points" in text:
            return {
                "market_family": "constructor_second_most_points",
                "model_requirement": "sampled finishing-order distribution converted to ranked team points",
                "normalizer_requirement": "map constructor outcomes to team_id token prices",
            }
        if "constructor" in text and "most points" in text:
            return {
                "market_family": "constructor_most_points",
                "model_requirement": "sampled finishing-order distribution converted to team points",
                "normalizer_requirement": "map constructor outcomes to team_id token prices",
            }
        if "pole winner" in text or "pole position" in text:
            return {
                "market_family": "pole_winner",
                "model_requirement": "qualifying-position probability distribution",
                "normalizer_requirement": "map driver or Yes-token pole markets to driver_id",
            }
        if "sprint winner" in text:
            return {
                "market_family": "sprint_winner",
                "model_requirement": "sprint-race simulator or sprint-specific replay features",
                "normalizer_requirement": "map sprint winner outcomes to driver_id",
            }
        if "head to head" in text or "finish ahead" in text or " vs. " in text or " vs " in text:
            return {
                "market_family": DRIVER_H2H,
                "model_requirement": "sampled finishing-order pairwise probability distribution",
                "normalizer_requirement": "parse both sides of the matchup and map to canonical driver_ahead_of_driver_b outcome ids",
            }
        if "safety car" in text:
            return {
                "market_family": "safety_car",
                "model_requirement": "safety-car occurrence probability from race simulator",
                "normalizer_requirement": "map binary safety-car market to event-level outcome",
            }
        if "fastest lap" in text:
            return {
                "market_family": "fastest_lap",
                "model_requirement": "fastest-lap probability model or lap-time simulation aggregate",
                "normalizer_requirement": "map fastest-lap outcomes to driver_id",
            }
        return {
            "market_family": "other_non_winner",
            "model_requirement": "explicit market-specific probability adapter",
            "normalizer_requirement": "manual rule parser before inclusion in edge scoring",
        }

    @staticmethod
    def _bundle_dir(year: int, as_of: str, bundle_root: Path | str) -> Path:
        return Path(bundle_root) / f"{year}_asof_{ReadinessMarketScanner._stem_time(as_of)}"

    @staticmethod
    def _stem_time(value: str) -> str:
        return value.replace(":", "").replace("+", "_").replace("-", "")

    @staticmethod
    def _matching_backfill_report(
        event_id: str,
        summary: dict[str, Any],
        market_type: str,
        output_dir: Path | str = Path("reports/market_normalization"),
    ) -> dict[str, Any] | None:
        directory = Path(output_dir)
        candidates = [directory / f"{event_id}_price_history.json"]
        if market_type != WINNER:
            candidates.insert(0, directory / f"{event_id}_{market_type}_price_history.json")
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("event_id") != event_id or payload.get("market_type") != market_type:
            return None
        required_by = {str(value) for value in summary.get("required_by", ()) if value}
        if required_by and str(payload.get("knowledge_cutoff") or "") not in required_by:
            return None
        payload["output"] = str(path)
        return payload

    @staticmethod
    def _dict_issue_counts(issues: tuple[Any, ...]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "")
            if not code:
                continue
            counts[code] = counts.get(code, 0) + 1
        return counts

    @staticmethod
    def _dict_issue_examples(issues: tuple[Any, ...], limit: int = 3) -> list[dict[str, str]]:
        examples: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "")
            question = str(issue.get("question") or "")
            if not code:
                continue
            key = (code, question)
            if key in seen:
                continue
            seen.add(key)
            examples.append(
                {
                    "code": code,
                    "severity": str(issue.get("severity") or ""),
                    "question": question,
                    "detail": str(issue.get("detail") or ""),
                }
            )
            if len(examples) >= limit:
                break
        return examples

    @staticmethod
    def _top_dict_issue(issue_counts: dict[str, int], issues: tuple[Any, ...]) -> dict[str, str]:
        if not issue_counts:
            return {}
        code = max(issue_counts.items(), key=lambda item: (int(item[1]), item[0]))[0]
        issue = next((item for item in issues if isinstance(item, dict) and item.get("code") == code), None)
        if issue is None:
            return {"code": code, "detail": "", "question": ""}
        return {
            "code": str(issue.get("code") or ""),
            "detail": str(issue.get("detail") or ""),
            "question": str(issue.get("question") or ""),
        }
