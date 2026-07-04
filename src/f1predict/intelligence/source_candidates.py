"""Normalize Codex web-search source candidates before evidence drafting."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from f1predict.domain import parse_dt, utc_now
from f1predict.intelligence.factor_trace import FACTOR_ROUTES, TRACK_CONTEXTUAL_METRICS
from f1predict.intelligence.research_plan import CodexResearchPlanBuilder
from f1predict.intelligence.source_registry import DEFAULT_SOURCE_RELIABILITY
from f1predict.models.technical_factors import (
    technical_context_breakdown,
    technical_context_multiplier,
    technical_context_reason,
)


@dataclass(frozen=True)
class CodexSourceCandidateFinding:
    severity: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CodexSourceCandidateRow:
    candidate_id: str
    event_id: str
    task_id: str | None
    query: str | None
    source: str
    source_class: str
    url: str
    title: str | None
    snippet: str | None
    published_at: str | None
    observed_at: str | None
    captured_by: str | None
    model_metrics: tuple[str, ...]
    target_hints: tuple[str, ...]
    route_preview: tuple[dict[str, Any], ...]
    impact_band_guidance: tuple[dict[str, Any], ...]
    status: str
    source_reliability: float | None
    relevance_score: float
    cutoff_status: str
    task_link_status: str
    risk_flags: tuple[str, ...]
    findings: tuple[CodexSourceCandidateFinding, ...]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "query": self.query,
            "source": self.source,
            "source_class": self.source_class,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "captured_by": self.captured_by,
            "model_metrics": list(self.model_metrics),
            "target_hints": list(self.target_hints),
            "route_preview": list(self.route_preview),
            "impact_band_guidance": list(self.impact_band_guidance),
            "status": self.status,
            "source_reliability": self.source_reliability,
            "relevance_score": self.relevance_score,
            "cutoff_status": self.cutoff_status,
            "task_link_status": self.task_link_status,
            "risk_flags": list(self.risk_flags),
            "findings": [finding.to_dict() for finding in self.findings],
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class CodexSourceCandidateReport:
    generated_at: str
    event_id: str
    event_name: str
    knowledge_cutoff: str
    status: str
    candidate_count: int
    review_ready_count: int
    blocked_count: int
    warning_count: int
    status_counts: dict[str, int]
    source_class_counts: dict[str, int]
    task_link_counts: dict[str, int]
    rows: tuple[CodexSourceCandidateRow, ...]
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "knowledge_cutoff": self.knowledge_cutoff,
            "status": self.status,
            "candidate_count": self.candidate_count,
            "review_ready_count": self.review_ready_count,
            "blocked_count": self.blocked_count,
            "warning_count": self.warning_count,
            "status_counts": self.status_counts,
            "source_class_counts": self.source_class_counts,
            "task_link_counts": self.task_link_counts,
            "rows": [row.to_dict() for row in self.rows],
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Codex Source Candidates: {self.event_name}",
            "",
            f"- event_id: `{self.event_id}`",
            f"- knowledge_cutoff: `{self.knowledge_cutoff}`",
            f"- status: `{self.status}`",
            f"- candidates: `{self.candidate_count}`",
            f"- review_ready: `{self.review_ready_count}`",
            f"- blocked: `{self.blocked_count}`",
            "",
            "## Status Counts",
        ]
        for status, count in self.status_counts.items():
            lines.append(f"- `{status}`: {count}")
        lines.extend(["", "## Candidates", ""])
        if self.rows:
            lines.append("| candidate | source_class | status | task | metrics | routes | relevance | cutoff |")
            lines.append("| --- | --- | --- | --- | --- | --- | ---: | --- |")
            for row in self.rows:
                metrics = ", ".join(row.model_metrics) or "n/a"
                routes = ", ".join(
                    f"{preview.get('metric')}->{preview.get('route')}"
                    for preview in row.route_preview
                ) or "n/a"
                lines.append(
                    f"| `{row.candidate_id}` | `{row.source_class}` | `{row.status}` | "
                    f"`{row.task_id or 'n/a'}` | {metrics} | {routes} | {row.relevance_score:.2f} | `{row.cutoff_status}` |"
                )
        else:
            lines.append("No candidates supplied yet.")
        lines.extend(["", "## Next Actions", ""])
        if self.rows:
            for row in self.rows:
                lines.append(f"- `{row.candidate_id}`: {row.next_action}")
        else:
            lines.append("- Search using the Codex research plan source tasks, then fill the candidate input JSON.")
        lines.append("")
        return "\n".join(lines)


class CodexSourceCandidateBuilder:
    """Audits Codex-collected search results before claim normalization."""

    def __init__(self, research_plan_builder: CodexResearchPlanBuilder | None = None) -> None:
        self.research_plan_builder = research_plan_builder or CodexResearchPlanBuilder()

    def build(
        self,
        event_id: str,
        knowledge_cutoff: str | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> CodexSourceCandidateReport:
        plan = self.research_plan_builder.build(event_id, knowledge_cutoff=knowledge_cutoff)
        cutoff_dt = _parse_cutoff(plan.knowledge_cutoff)
        tasks = {task.task_id: task for task in plan.source_tasks}
        rows = tuple(
            self._row(
                raw,
                index=index,
                event_id=event_id,
                event_name=plan.event_name,
                cutoff_dt=cutoff_dt,
                tasks=tasks,
                metric_guidance=plan.metric_guidance,
                impact_bands=tuple(band.to_dict() for band in plan.impact_bands),
                track_type=str(plan.event_context.get("track_type") or ""),
            )
            for index, raw in enumerate(candidates or [], start=1)
            if isinstance(raw, dict)
        )
        status_counts = dict(sorted(Counter(row.status for row in rows).items()))
        source_class_counts = dict(sorted(Counter(row.source_class for row in rows).items()))
        task_link_counts = dict(sorted(Counter(row.task_link_status for row in rows).items()))
        blocked = sum(1 for row in rows if row.status == "candidate_blocked")
        review_ready = sum(1 for row in rows if row.status == "candidate_ready_for_claim_review")
        warnings = sum(1 for row in rows if row.status == "candidate_needs_review")
        if not rows:
            status = "awaiting_codex_search_candidates"
        elif blocked:
            status = "source_candidates_blocked"
        elif warnings:
            status = "source_candidates_need_review"
        else:
            status = "source_candidates_ready_for_claim_review"
        return CodexSourceCandidateReport(
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            event_id=event_id,
            event_name=plan.event_name,
            knowledge_cutoff=plan.knowledge_cutoff,
            status=status,
            candidate_count=len(rows),
            review_ready_count=review_ready,
            blocked_count=blocked,
            warning_count=warnings,
            status_counts=status_counts,
            source_class_counts=source_class_counts,
            task_link_counts=task_link_counts,
            rows=rows,
            input_contract=self.input_contract(event_id, plan.knowledge_cutoff),
            output_contract=self.output_contract(event_id),
        )

    def build_file(
        self,
        event_id: str,
        path: Path | str,
        knowledge_cutoff: str | None = None,
    ) -> CodexSourceCandidateReport:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            candidates = raw.get("candidates")
            cutoff = knowledge_cutoff or raw.get("knowledge_cutoff")
        else:
            candidates = raw
            cutoff = knowledge_cutoff
        if not isinstance(candidates, list):
            candidates = []
        return self.build(event_id, knowledge_cutoff=str(cutoff) if cutoff else None, candidates=candidates)

    @classmethod
    def write(
        cls,
        report: CodexSourceCandidateReport,
        json_output: Path | str | None = None,
        markdown_output: Path | str | None = None,
    ) -> dict[str, str]:
        written: dict[str, str] = {}
        if json_output:
            path = Path(json_output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            written["json_output"] = str(path)
        if markdown_output:
            path = Path(markdown_output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report.to_markdown(), encoding="utf-8")
            written["markdown_output"] = str(path)
        return written

    @staticmethod
    def input_contract(event_id: str, cutoff: str) -> dict[str, Any]:
        return {
            "path": f"data/research/{event_id}/source_candidates.json",
            "knowledge_cutoff": cutoff,
            "schema": {
                "candidates": [
                    {
                        "candidate_id": f"{event_id}-source-001",
                        "task_id": f"{event_id}:team-updates-track-fit",
                        "query": "search query Codex used",
                        "source": "publisher or provider name",
                        "source_class": "f1_official|fia|team_or_driver|structured_data|media|weather|market|rumor|social",
                        "url": "https://...",
                        "title": "search result or page title",
                        "snippet": "tool-visible source-backed excerpt or summary",
                        "published_at": "ISO timestamp or null",
                        "observed_at": "ISO timestamp when Codex saw it",
                        "captured_by": "codex_web_search|codex_web_open|manual",
                        "model_metrics": ["energy_recovery"],
                        "target_hints": ["mercedes"],
                    }
                ]
            },
        }

    @staticmethod
    def output_contract(event_id: str) -> dict[str, Any]:
        return {
            "candidate_report_json": f"reports/research_candidates/{event_id}.json",
            "candidate_report_markdown": f"reports/research_candidates/{event_id}.md",
            "next_step": "Review ready candidates, inspect/snapshot accepted sources, then fill research_packet_template.json.",
        }

    def _row(
        self,
        raw: dict[str, Any],
        index: int,
        event_id: str,
        event_name: str,
        cutoff_dt: datetime | None,
        tasks: dict[str, Any],
        metric_guidance: dict[str, dict[str, Any]],
        impact_bands: tuple[dict[str, Any], ...],
        track_type: str,
    ) -> CodexSourceCandidateRow:
        candidate_id = str(raw.get("candidate_id") or f"{event_id}-candidate-{index:03d}")
        source_class = str(raw.get("source_class") or "").strip().lower()
        task_id = str(raw.get("task_id") or "").strip() or None
        task = tasks.get(task_id or "")
        findings: list[CodexSourceCandidateFinding] = []
        risk_flags: list[str] = []
        candidate_event_id = str(raw.get("event_id") or event_id)

        if candidate_event_id != event_id:
            findings.append(
                CodexSourceCandidateFinding(
                    "error",
                    "event_id_mismatch",
                    f"Candidate event_id={candidate_event_id!r} does not match requested event_id={event_id!r}.",
                )
            )
            risk_flags.append("event_id_mismatch")

        url = str(raw.get("url") or "").strip()
        if not _valid_url(url):
            findings.append(CodexSourceCandidateFinding("error", "invalid_url", "Candidate requires a valid http(s) URL."))
            risk_flags.append("invalid_url")

        if source_class not in DEFAULT_SOURCE_RELIABILITY:
            findings.append(
                CodexSourceCandidateFinding(
                    "error",
                    "unsupported_source_class",
                    f"Unsupported source_class={source_class!r}.",
                )
            )
            risk_flags.append("unsupported_source_class")
            reliability = None
        else:
            reliability = DEFAULT_SOURCE_RELIABILITY[source_class]

        task_link_status = "linked_to_research_task" if task else "unlinked_research_task"
        if task is None:
            findings.append(CodexSourceCandidateFinding("warning", "unlinked_research_task", "Candidate does not link to a source task."))
            risk_flags.append("unlinked_research_task")
        elif source_class and source_class != task.source_class:
            findings.append(
                CodexSourceCandidateFinding(
                    "warning",
                    "source_class_mismatch",
                    f"Candidate source_class={source_class} differs from task source_class={task.source_class}.",
                )
            )
            risk_flags.append("source_class_mismatch")

        cutoff_status = self._cutoff_status(raw, cutoff_dt, findings, risk_flags)
        if cutoff_status.startswith("after_cutoff"):
            findings.append(
                CodexSourceCandidateFinding(
                    "error",
                    "candidate_after_cutoff",
                    "Candidate published_at/observed_at is after the replay cutoff.",
                )
            )
            risk_flags.append("candidate_after_cutoff")

        model_metrics = _string_tuple(raw.get("model_metrics") or raw.get("metrics"))
        task_metrics = set(task.model_metrics) if task else set()
        if task_metrics and not set(model_metrics).intersection(task_metrics):
            findings.append(
                CodexSourceCandidateFinding(
                    "warning",
                    "metric_not_in_task",
                    "Candidate metrics do not overlap the linked research task model metrics.",
                )
            )
            risk_flags.append("metric_not_in_task")
        if not model_metrics:
            findings.append(CodexSourceCandidateFinding("warning", "missing_model_metrics", "Candidate should name model metrics it may support."))
            risk_flags.append("missing_model_metrics")

        snippet = str(raw.get("snippet") or raw.get("summary") or "").strip() or None
        title = str(raw.get("title") or "").strip() or None
        relevance = self._relevance_score(event_name, raw, task_metrics)
        if relevance < 0.35:
            findings.append(CodexSourceCandidateFinding("warning", "low_relevance_score", "Candidate text weakly matches the event/task context."))
            risk_flags.append("low_relevance_score")
        if not snippet:
            findings.append(CodexSourceCandidateFinding("warning", "missing_snippet", "Candidate should preserve a search-result snippet or tool-visible summary."))
            risk_flags.append("missing_snippet")

        route_preview = self._route_preview(
            model_metrics or tuple(sorted(task_metrics)),
            metric_guidance,
            track_type,
        )
        impact_band_guidance = self._impact_band_guidance(impact_bands)

        error_count = sum(1 for finding in findings if finding.severity == "error")
        warning_count = sum(1 for finding in findings if finding.severity == "warning")
        if error_count:
            status = "candidate_blocked"
            next_action = "Fix blocking fields or discard this candidate before drafting evidence claims."
        elif warning_count:
            status = "candidate_needs_review"
            next_action = "Manually inspect the source, resolve warnings, then snapshot and cite it in the research packet."
        else:
            status = "candidate_ready_for_claim_review"
            next_action = "Open and snapshot the source, then convert only source-backed facts into research_packet_template.json claims."

        return CodexSourceCandidateRow(
            candidate_id=candidate_id,
            event_id=candidate_event_id,
            task_id=task_id,
            query=str(raw.get("query") or "").strip() or None,
            source=str(raw.get("source") or title or url or candidate_id),
            source_class=source_class,
            url=url,
            title=title,
            snippet=snippet,
            published_at=str(raw.get("published_at")) if raw.get("published_at") is not None else None,
            observed_at=str(raw.get("observed_at")) if raw.get("observed_at") is not None else None,
            captured_by=str(raw.get("captured_by") or "").strip() or None,
            model_metrics=model_metrics,
            target_hints=_string_tuple(raw.get("target_hints") or raw.get("targets")),
            route_preview=route_preview,
            impact_band_guidance=impact_band_guidance,
            status=status,
            source_reliability=reliability,
            relevance_score=relevance,
            cutoff_status=cutoff_status,
            task_link_status=task_link_status,
            risk_flags=tuple(dict.fromkeys(risk_flags)),
            findings=tuple(findings),
            next_action=next_action,
        )

    @staticmethod
    def _route_preview(
        metrics: tuple[str, ...],
        metric_guidance: dict[str, dict[str, Any]],
        track_type: str,
    ) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for metric in metrics:
            route = FACTOR_ROUTES.get(metric)
            guidance = metric_guidance.get(metric, {})
            context_multiplier = None
            context_reason = None
            context_breakdown = technical_context_breakdown(metric, track_type)
            track_demand_component = None
            track_demand_value = None
            track_demand_profile = None
            if route and metric in TRACK_CONTEXTUAL_METRICS:
                context_multiplier = round(technical_context_multiplier(metric, track_type), 4)
                context_reason = technical_context_reason(metric, track_type)
                if context_breakdown:
                    track_demand_component = context_breakdown.get("demand_component")
                    track_demand_value = context_breakdown.get("demand_value")
                    profile = context_breakdown.get("track_demand_profile")
                    track_demand_profile = profile if isinstance(profile, dict) else None
            rows.append(
                {
                    "metric": metric,
                    "route": route.route if route else "unsupported_metric",
                    "model_surface": route.model_surface if route else "not routed",
                    "route_notes": list(route.notes) if route else ["Metric has no simulator route."],
                    "valid_target_types": list(guidance.get("targets") or []),
                    "valid_claim_types": list(guidance.get("valid_claim_types") or []),
                    "metric_notes": guidance.get("notes"),
                    "context_multiplier": context_multiplier,
                    "context_multiplier_reason": context_reason,
                    "track_demand_component": track_demand_component,
                    "track_demand_value": track_demand_value,
                    "track_demand_profile": track_demand_profile,
                }
            )
        return tuple(rows)

    @staticmethod
    def _impact_band_guidance(impact_bands: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "band": band.get("band"),
                "signed_magnitude_range": band.get("signed_magnitude_range"),
                "confidence_cap": band.get("confidence_cap"),
                "use_when": band.get("use_when"),
                "review_rule": band.get("review_rule"),
            }
            for band in impact_bands
        )

    @staticmethod
    def _cutoff_status(
        raw: dict[str, Any],
        cutoff_dt: datetime | None,
        findings: list[CodexSourceCandidateFinding],
        risk_flags: list[str],
    ) -> str:
        if cutoff_dt is None:
            return "no_cutoff"
        published = _parse_optional_dt(raw.get("published_at"))
        observed = _parse_optional_dt(raw.get("observed_at"))
        if raw.get("published_at") and published is None:
            findings.append(CodexSourceCandidateFinding("error", "invalid_published_at", "published_at is not parseable ISO time."))
            risk_flags.append("invalid_published_at")
            return "invalid_published_at"
        if raw.get("observed_at") and observed is None:
            findings.append(CodexSourceCandidateFinding("error", "invalid_observed_at", "observed_at is not parseable ISO time."))
            risk_flags.append("invalid_observed_at")
            return "invalid_observed_at"
        if published and _as_utc(published) > cutoff_dt:
            return "after_cutoff_published"
        if observed and _as_utc(observed) > cutoff_dt:
            return "after_cutoff_observed"
        if published is None:
            findings.append(CodexSourceCandidateFinding("warning", "unknown_published_at", "published_at is missing."))
            risk_flags.append("unknown_published_at")
            return "unknown_published_at"
        return "within_cutoff"

    @staticmethod
    def _relevance_score(
        event_name: str,
        raw: dict[str, Any],
        task_metrics: set[str],
    ) -> float:
        text = _normalize_text(" ".join(str(raw.get(key) or "") for key in ("title", "snippet", "summary", "query")))
        event_terms = [term for term in re.split(r"[^a-z0-9]+", event_name.lower()) if len(term) >= 4]
        metric_terms = [metric.replace("_", " ") for metric in _string_tuple(raw.get("model_metrics") or raw.get("metrics"))]
        if not metric_terms:
            metric_terms = [metric.replace("_", " ") for metric in sorted(task_metrics)]
        target_terms = [str(value).replace("_", " ") for value in _string_tuple(raw.get("target_hints") or raw.get("targets"))]
        score = 0.0
        if any(term in text for term in event_terms):
            score += 0.35
        if any(_normalize_text(term) in text for term in metric_terms):
            score += 0.25
        if any(_normalize_text(term) in text for term in target_terms):
            score += 0.25
        if _valid_url(str(raw.get("url") or "")):
            score += 0.15
        return round(min(1.0, score), 4)


def _parse_cutoff(value: str | None) -> datetime | None:
    parsed = _parse_optional_dt(value)
    if parsed is None:
        return None
    return _as_utc(parsed)


def _parse_optional_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return parse_dt(str(value))
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    if value:
        return (str(value),)
    return ()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
