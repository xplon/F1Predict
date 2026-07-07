"""Auditable Codex research planning for race-week evidence intake."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from f1predict.data_sources.augmented import CalendarAugmentedDataSource
from f1predict.domain import EvidenceClaim, RaceEvent, SeasonState, parse_dt, utc_now
from f1predict.intelligence.codex import CodexEvidenceProvider
from f1predict.intelligence.factor_contract import factor_metric_guidance
from f1predict.intelligence.source_registry import DEFAULT_SOURCE_RELIABILITY


class SeasonDataSource(Protocol):
    def load(self) -> SeasonState: ...


@dataclass(frozen=True)
class CodexSourceTask:
    task_id: str
    source_class: str
    title: str
    priority: str
    reliability_floor: float
    query_templates: tuple[str, ...]
    acceptance_checks: tuple[str, ...]
    rejection_rules: tuple[str, ...]
    model_metrics: tuple[str, ...]
    expected_claim_types: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_class": self.source_class,
            "title": self.title,
            "priority": self.priority,
            "reliability_floor": self.reliability_floor,
            "query_templates": list(self.query_templates),
            "acceptance_checks": list(self.acceptance_checks),
            "rejection_rules": list(self.rejection_rules),
            "model_metrics": list(self.model_metrics),
            "expected_claim_types": list(self.expected_claim_types),
        }


@dataclass(frozen=True)
class CodexImpactBand:
    band: str
    signed_magnitude_range: tuple[float, float]
    confidence_cap: float
    use_when: str
    review_rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "signed_magnitude_range": list(self.signed_magnitude_range),
            "confidence_cap": self.confidence_cap,
            "use_when": self.use_when,
            "review_rule": self.review_rule,
        }


@dataclass(frozen=True)
class CodexResearchPlan:
    generated_at: str
    event_id: str
    event_name: str
    knowledge_cutoff: str
    status: str
    event_context: dict[str, Any]
    existing_evidence: list[dict[str, Any]]
    source_tasks: tuple[CodexSourceTask, ...]
    source_reliability_rubric: dict[str, float]
    impact_bands: tuple[CodexImpactBand, ...]
    metric_guidance: dict[str, dict[str, Any]]
    quality_gates: tuple[str, ...]
    tool_workflow: tuple[str, ...]
    output_contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "knowledge_cutoff": self.knowledge_cutoff,
            "status": self.status,
            "event_context": self.event_context,
            "existing_evidence": self.existing_evidence,
            "source_tasks": [task.to_dict() for task in self.source_tasks],
            "source_reliability_rubric": self.source_reliability_rubric,
            "impact_bands": [band.to_dict() for band in self.impact_bands],
            "metric_guidance": self.metric_guidance,
            "quality_gates": list(self.quality_gates),
            "tool_workflow": list(self.tool_workflow),
            "output_contract": self.output_contract,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Codex Research Plan: {self.event_name}",
            "",
            f"- event_id: `{self.event_id}`",
            f"- knowledge_cutoff: `{self.knowledge_cutoff}`",
            f"- status: `{self.status}`",
            "",
            "## Context",
        ]
        for key, value in self.event_context.items():
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "## Source Tasks"])
        for task in self.source_tasks:
            lines.extend(
                [
                    f"### {task.title}",
                    f"- task_id: `{task.task_id}`",
                    f"- source_class: `{task.source_class}`",
                    f"- priority: `{task.priority}`",
                    f"- reliability_floor: `{task.reliability_floor}`",
                    f"- model_metrics: `{', '.join(task.model_metrics)}`",
                    "- queries:",
                ]
            )
            lines.extend(f"  - {query}" for query in task.query_templates)
            lines.append("- acceptance:")
            lines.extend(f"  - {check}" for check in task.acceptance_checks)
            lines.append("- reject:")
            lines.extend(f"  - {rule}" for rule in task.rejection_rules)
            lines.append("")
        lines.extend(["## Impact Bands"])
        for band in self.impact_bands:
            lower, upper = band.signed_magnitude_range
            lines.append(
                f"- `{band.band}` {lower:+.3f}..{upper:+.3f}, "
                f"confidence cap {band.confidence_cap:.2f}: {band.use_when}"
            )
        lines.extend(["", "## Quality Gates"])
        lines.extend(f"- {gate}" for gate in self.quality_gates)
        lines.extend(["", "## Tool Workflow"])
        lines.extend(f"{index}. {step}" for index, step in enumerate(self.tool_workflow, start=1))
        lines.extend(
            [
                "",
                "## Output Contract",
                f"- research_packet_path: `{self.output_contract['research_packet_path']}`",
                f"- source_candidate_input_path: `{self.output_contract['source_candidate_input_path']}`",
                f"- source_candidate_report_json: `{self.output_contract['source_candidate_report_json']}`",
                f"- preflight_report_json: `{self.output_contract['preflight_report_json']}`",
                f"- preflight_report_markdown: `{self.output_contract['preflight_report_markdown']}`",
                f"- draft_evidence_path: `{self.output_contract['draft_evidence_path']}`",
                f"- source_log_path: `{self.output_contract['source_log_path']}`",
                f"- source_candidate_command: `{self.output_contract['source_candidate_command']}`",
                f"- preflight_command: `{self.output_contract['preflight_command']}`",
                f"- archive_command: `{self.output_contract['archive_command']}`",
            ]
        )
        return "\n".join(lines) + "\n"


class CodexResearchPlanBuilder:
    """Builds a deterministic plan for Codex tool-using source research.

    The plan is an execution contract. It tells Codex what to search, what
    source checks must pass, and how qualitative news should be translated into
    bounded model inputs. It does not contain final probabilities.
    """

    def __init__(
        self,
        data_source: SeasonDataSource | None = None,
        evidence_provider: CodexEvidenceProvider | None = None,
    ) -> None:
        self.data_source = data_source or CalendarAugmentedDataSource()
        self.evidence_provider = evidence_provider or CodexEvidenceProvider()

    def build(self, event_id: str, knowledge_cutoff: str | None = None) -> CodexResearchPlan:
        season = self.data_source.load()
        event = next((item for item in season.events if item.event_id == event_id), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")
        cutoff = knowledge_cutoff or f"{event.date}T00:00:00+00:00"
        cutoff_dt = parse_dt(cutoff)
        evidence = self.evidence_provider.load_event_evidence(event.event_id, cutoff_dt)
        tasks = self._source_tasks(season, event)
        status = self._status(evidence)
        return CodexResearchPlan(
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            event_id=event.event_id,
            event_name=event.name,
            knowledge_cutoff=cutoff,
            status=status,
            event_context=self._event_context(event),
            existing_evidence=self._existing_evidence(evidence),
            source_tasks=tasks,
            source_reliability_rubric=dict(sorted(DEFAULT_SOURCE_RELIABILITY.items())),
            impact_bands=self._impact_bands(),
            metric_guidance=self._metric_guidance(),
            quality_gates=self._quality_gates(),
            tool_workflow=self._tool_workflow(event.event_id, cutoff),
            output_contract=self._output_contract(event.event_id, cutoff),
        )

    @staticmethod
    def write(plan: CodexResearchPlan, output_dir: Path | str = Path("data/research")) -> dict[str, Path]:
        directory = Path(output_dir) / plan.event_id
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "codex_research_plan.json"
        markdown_path = directory / "codex_research_plan.md"

        json_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(plan.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    @staticmethod
    def _event_context(event: RaceEvent) -> dict[str, Any]:
        refs = event.feature_refs or {}
        return {
            "round_number": event.round_number,
            "date": event.date,
            "track_type": event.track_type,
            "laps": event.laps,
            "completed": event.completed,
            "wet_probability_prior": event.weather_prior.get("wet_probability", 0.0),
            "input_source": refs.get("event_source", "seed"),
            "track_asset_source": (refs.get("track_map_asset") or {}).get("source"),
            "race_week_forecast_present": bool(refs.get("weather_forecast")),
        }

    @staticmethod
    def _existing_evidence(evidence: list[EvidenceClaim]) -> list[dict[str, Any]]:
        return [
            {
                "claim_id": claim.claim_id,
                "source": claim.source,
                "source_url": claim.source_url,
                "target_type": claim.target_type,
                "target_id": claim.target_id,
                "metric": claim.metric,
                "direction": claim.direction,
                "signed_impact": round(claim.signed_impact(), 4),
                "review_required": claim.review_required,
            }
            for claim in evidence
        ]

    @staticmethod
    def _status(evidence: list[EvidenceClaim]) -> str:
        if not evidence:
            return "research_required"
        if any(claim.review_required for claim in evidence):
            return "review_required_evidence_present"
        return "refresh_recommended"

    def _source_tasks(self, season: SeasonState, event: RaceEvent) -> tuple[CodexSourceTask, ...]:
        top_teams = self._top_team_names(season)
        event_name = event.name
        date = event.date
        base_tasks = [
            CodexSourceTask(
                task_id=f"{event.event_id}:f1-official-fia",
                source_class="f1_official",
                title="Official and FIA Context",
                priority="P0",
                reliability_floor=0.90,
                query_templates=(
                    f"{event_name} {date} Formula 1 official preview classification",
                    f"{event_name} {date} FIA documents race director notes",
                    f"{event_name} {date} penalties grid changes FIA",
                ),
                acceptance_checks=(
                    "Source is Formula1.com, FIA.com, or a linked official document.",
                    "Publication and observation timestamps are at or before the cutoff.",
                    "Classification, penalties, or rules claims include the governing document or official page.",
                ),
                rejection_rules=(
                    "Reject fan summaries when the official document is available.",
                    "Reject any post-cutoff classification or penalty update for replay cutoffs.",
                ),
                model_metrics=("reliability", "strategy", "qualifying_pace"),
                expected_claim_types=("rules", "penalty", "classification", "schedule"),
            ),
            CodexSourceTask(
                task_id=f"{event.event_id}:team-updates-track-fit",
                source_class="team_or_driver",
                title="Team Upgrades and Track Fit",
                priority="P0",
                reliability_floor=0.80,
                query_templates=(
                    f"{event_name} {date} team upgrades {' '.join(top_teams[:4])}",
                    f"{event_name} {date} track characteristics {event.track_type} F1",
                    f"{event_name} {date} Mercedes Ferrari McLaren Red Bull preview",
                ),
                acceptance_checks=(
                    "Prefer team releases, named team principal quotes, or established outlets quoting named staff.",
                    "Tie every claimed effect to a metric such as race_pace, race_execution, power_unit, energy_recovery, straight_line_speed, drag_efficiency, low_speed_traction, launch_performance, weight, upgrade_effect, tyre_deg, strategy, setup_quality, or reliability.",
                    "Use small magnitude unless the source says the part or issue is event-specific and already run-tested.",
                ),
                rejection_rules=(
                    "Reject unsourced upgrade rumors as model inputs; store only as review_required rumor claims if needed.",
                    "Reject generic optimism unless it maps to a specific car, circuit, weather, or reliability mechanism.",
                ),
                model_metrics=(
                    "race_pace",
                    "race_execution",
                    "qualifying_pace",
                    "power_unit",
                    "energy_recovery",
                    "straight_line_speed",
                    "drag_efficiency",
                    "low_speed_traction",
                    "launch_performance",
                    "weight",
                    "upgrade_effect",
                    "tyre_deg",
                    "setup_quality",
                    "reliability",
                ),
                expected_claim_types=("upgrade", "track_fit", "setup", "power_unit", "aero", "launch", "weight", "reliability"),
            ),
            CodexSourceTask(
                task_id=f"{event.event_id}:weather",
                source_class="weather",
                title="Weather and Track Conditions",
                priority="P0" if event.weather_prior.get("wet_probability", 0.0) >= 0.18 else "P1",
                reliability_floor=0.70,
                query_templates=(
                    f"{event_name} {date} weather forecast race rain wind track temperature",
                    f"{event_name} {date} circuit weather radar F1",
                    f"{event_name} {date} qualifying race forecast",
                ),
                acceptance_checks=(
                    "Weather claim states forecast window, race session timing, rain probability, and wind or temperature when available.",
                    "Forecast source is captured at or before the knowledge cutoff.",
                    "Wet or wind claims are translated into wet_skill, strategy, reliability, or qualifying_pace effects.",
                ),
                rejection_rules=(
                    "Reject vague 'rain possible' claims without timing or probability.",
                    "Reject forecasts updated after the cutoff unless historical archive proof is attached.",
                ),
                model_metrics=("wet_skill", "strategy", "reliability", "qualifying_pace"),
                expected_claim_types=("weather", "track_condition"),
            ),
            CodexSourceTask(
                task_id=f"{event.event_id}:structured-session-data",
                source_class="structured_data",
                title="Structured Session and Form Data",
                priority="P1",
                reliability_floor=0.85,
                query_templates=(
                    f"OpenF1 {event_name} {date} laps stints weather race control",
                    f"FastF1 {event_name} {date} session results lap times",
                    f"{event_name} {date} long run pace tyre degradation F1",
                ),
                acceptance_checks=(
                    "Structured data claims include session, metric, and cutoff availability.",
                    "Practice claims distinguish low-fuel headline pace from long-run race pace.",
                    "Race result claims are only used when the prediction cutoff is after the race.",
                ),
                rejection_rules=(
                    "Reject practice fastest-lap headlines as race pace unless stint context is available.",
                    "Reject same-event race result data for pre-race prediction cutoffs.",
                ),
                model_metrics=(
                    "race_pace",
                    "race_execution",
                    "qualifying_pace",
                    "straight_line_speed",
                    "energy_recovery",
                    "low_speed_traction",
                    "launch_performance",
                    "tyre_deg",
                    "setup_quality",
                    "reliability",
                ),
                expected_claim_types=("session_pace", "long_run", "speed_trap", "sector_pace", "launch", "tyre_deg", "setup", "race_control"),
            ),
            CodexSourceTask(
                task_id=f"{event.event_id}:market-rules",
                source_class="market",
                title="Market Rules and Snapshot Eligibility",
                priority="P1",
                reliability_floor=0.65,
                query_templates=(
                    f"{event_name} Polymarket winner market rules {date}",
                    f"{event_name} Polymarket F1 podium pole fastest lap market",
                    f"{event_name} prediction market final classification rules",
                ),
                acceptance_checks=(
                    "Market rule claims identify resolution source, cancellation handling, and post-race change handling.",
                    "Price data is not embedded as evidence; it must enter through MarketSnapshot ingestion.",
                    "Candidate market season, event, and outcome mapping are unambiguous.",
                ),
                rejection_rules=(
                    "Reject mismatched season markets even if the race name matches.",
                    "Reject price screenshots or prose odds as formal market snapshots.",
                ),
                model_metrics=("strategy",),
                expected_claim_types=("market_rules", "settlement", "candidate_market"),
            ),
            CodexSourceTask(
                task_id=f"{event.event_id}:independent-media-corroboration",
                source_class="media",
                title="Independent Corroboration",
                priority="P2",
                reliability_floor=0.70,
                query_templates=(
                    f"{event_name} {date} F1 paddock notes named reporting",
                    f"{event_name} {date} race preview upgrades reliability named sources",
                    f"{event_name} {date} driver interviews team quotes",
                ),
                acceptance_checks=(
                    "Media claim has named outlet, author or agency, and a publication timestamp.",
                    "High-impact claims are corroborated by official, team, structured-data, or second independent media source.",
                    "Conflicting sources are captured as separate claims with review_required=true.",
                ),
                rejection_rules=(
                    "Reject social reposts, anonymous rumors, and aggregation pages as standalone high-confidence evidence.",
                    "Reject claims where the original source cannot be identified.",
                ),
                model_metrics=(
                    "race_pace",
                    "race_execution",
                    "qualifying_pace",
                    "power_unit",
                    "energy_recovery",
                    "straight_line_speed",
                    "drag_efficiency",
                    "low_speed_traction",
                    "launch_performance",
                    "weight",
                    "upgrade_effect",
                    "tyre_deg",
                    "reliability",
                    "strategy",
                    "wet_skill",
                ),
                expected_claim_types=("corroboration", "quote", "contradiction", "risk"),
            ),
        ]
        return tuple(base_tasks)

    @staticmethod
    def _top_team_names(season: SeasonState) -> list[str]:
        teams = sorted(season.teams.values(), key=lambda team: team.base_strength, reverse=True)
        return [team.name for team in teams[:6]]

    @staticmethod
    def _impact_bands() -> tuple[CodexImpactBand, ...]:
        return (
            CodexImpactBand(
                band="negligible",
                signed_magnitude_range=(-0.01, 0.01),
                confidence_cap=0.75,
                use_when="Context is directionally relevant but unlikely to change simulation ordering.",
                review_rule="May be archived without review only when source reliability is at least 0.75.",
            ),
            CodexImpactBand(
                band="small",
                signed_magnitude_range=(-0.03, 0.03),
                confidence_cap=0.72,
                use_when="Single-source setup, weather, or form signal with plausible but limited race effect.",
                review_rule="Review required when source reliability is below 0.70 or timestamps are uncertain.",
            ),
            CodexImpactBand(
                band="moderate",
                signed_magnitude_range=(-0.06, 0.06),
                confidence_cap=0.68,
                use_when="Source-backed event-specific issue, upgrade, penalty, or weather signal likely to move a target group.",
                review_rule="Needs source linkage plus either official/team/structured source or independent corroboration.",
            ),
            CodexImpactBand(
                band="material",
                signed_magnitude_range=(-0.10, 0.10),
                confidence_cap=0.62,
                use_when="Confirmed grid penalty, major reliability issue, substantial rain change, or run-tested upgrade effect.",
                review_rule="Always review; require at least one high-reliability source and explicit reasoning.",
            ),
        )

    @staticmethod
    def _metric_guidance() -> dict[str, dict[str, Any]]:
        return factor_metric_guidance()

    @staticmethod
    def _quality_gates() -> tuple[str, ...]:
        return (
            "Codex must not emit final probabilities or direct trading recommendations.",
            "Every claim must link to a snapshotted source URL and claim id in source_log.json.",
            "published_at and observed_at must be at or before knowledge_cutoff unless the claim is rejected.",
            "A late local snapshot needs cutoff-valid historical_archive proof before it can support formal replay.",
            "Claims with source reliability below 0.70, unknown publication time, source conflict, or material impact must set review_required=true.",
            "Technical claims must state the mechanism and circuit context before using power_unit, energy_recovery, drag_efficiency, low_speed_traction, launch_performance, weight, or upgrade_effect.",
            "Magnitude must stay within the impact band justified by source quality and corroboration.",
            "Web-search candidates must be normalized through codex-source-candidates before they become claims.",
            "Run research packet preflight and resolve schema, source-link, conflict, weight, and routing findings before archiving.",
            "Market prices must enter through MarketSnapshot ingestion, not through Codex evidence claims.",
        )

    @staticmethod
    def _tool_workflow(event_id: str, cutoff: str) -> tuple[str, ...]:
        return (
            f"Run `python -m f1predict.cli prepare-research --event {event_id} --knowledge-cutoff {cutoff}` if workspace files are missing.",
            "Use the source tasks in this plan to search web/FIA/team/weather/market sources.",
            "Write inspected search results to data/research/<event_id>/source_candidates.json before drafting claims.",
            (
                "Run `python -m f1predict.cli codex-source-candidates "
                f"--event {event_id} --input data/research/{event_id}/source_candidates.json "
                f"--knowledge-cutoff {cutoff} "
                f"--output reports/research_candidates/{event_id}.json "
                f"--markdown-output reports/research_candidates/{event_id}.md`."
            ),
            "Fill data/research/<event_id>/research_packet_template.json with inspected sources and normalized claims.",
            "Attach historical_archive proof for any source inspected after the replay cutoff.",
            (
                "Run `python -m f1predict.cli preflight-research-packet "
                f"--input data/research/{event_id}/research_packet_template.json "
                f"--event {event_id} --knowledge-cutoff {cutoff} "
                f"--source-candidate-report reports/research_candidates/{event_id}.json "
                f"--output reports/research_preflight/{event_id}.json "
                f"--markdown-output reports/research_preflight/{event_id}.md`."
            ),
            f"Run `python -m f1predict.cli archive-research-packet --input data/research/{event_id}/research_packet_template.json --event {event_id} --knowledge-cutoff {cutoff}`.",
            f"Run `python -m f1predict.cli prediction-packet --event {event_id} --knowledge-cutoff {cutoff} --iterations 1200 --write` before discussing edge quality.",
        )

    @staticmethod
    def _output_contract(event_id: str, cutoff: str) -> dict[str, Any]:
        return {
            "research_packet_path": f"data/research/{event_id}/research_packet_template.json",
            "source_candidate_input_path": f"data/research/{event_id}/source_candidates.json",
            "source_candidate_report_json": f"reports/research_candidates/{event_id}.json",
            "source_candidate_report_markdown": f"reports/research_candidates/{event_id}.md",
            "preflight_report_json": f"reports/research_preflight/{event_id}.json",
            "preflight_report_markdown": f"reports/research_preflight/{event_id}.md",
            "draft_evidence_path": f"data/research/{event_id}/draft_evidence.jsonl",
            "source_log_path": f"data/research/{event_id}/source_log.json",
            "source_candidate_command": (
                "python -m f1predict.cli codex-source-candidates "
                f"--event {event_id} --input data/research/{event_id}/source_candidates.json "
                f"--knowledge-cutoff {cutoff} "
                f"--output reports/research_candidates/{event_id}.json "
                f"--markdown-output reports/research_candidates/{event_id}.md"
            ),
            "preflight_command": (
                "python -m f1predict.cli preflight-research-packet "
                f"--input data/research/{event_id}/research_packet_template.json "
                f"--event {event_id} --knowledge-cutoff {cutoff} "
                f"--source-candidate-report reports/research_candidates/{event_id}.json "
                f"--output reports/research_preflight/{event_id}.json "
                f"--markdown-output reports/research_preflight/{event_id}.md"
            ),
            "archive_command": (
                "python -m f1predict.cli archive-research-packet "
                f"--input data/research/{event_id}/research_packet_template.json "
                f"--event {event_id} --knowledge-cutoff {cutoff}"
            ),
            "prediction_packet_command": (
                "python -m f1predict.cli prediction-packet "
                f"--event {event_id} --knowledge-cutoff {cutoff} --iterations 1200 --write"
            ),
        }
