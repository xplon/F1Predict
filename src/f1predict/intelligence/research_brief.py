"""Codex research brief generation."""

from __future__ import annotations

from typing import Protocol

from f1predict.data_sources.augmented import CalendarAugmentedDataSource
from f1predict.domain import SeasonState
from f1predict.intelligence.codex import CodexEvidenceProvider


class SeasonDataSource(Protocol):
    def load(self) -> SeasonState: ...


class ResearchBriefBuilder:
    """Creates a deterministic brief for Codex tool-using research."""

    def __init__(
        self,
        data_source: SeasonDataSource | None = None,
        evidence_provider: CodexEvidenceProvider | None = None,
    ) -> None:
        self.data_source = data_source or CalendarAugmentedDataSource()
        self.evidence_provider = evidence_provider or CodexEvidenceProvider()

    def build(self, event_id: str) -> str:
        season = self.data_source.load()
        event = next((item for item in season.events if item.event_id == event_id), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")
        drivers = [driver for driver in season.drivers.values()]
        drivers.sort(key=lambda item: item.current_points, reverse=True)
        evidence = self.evidence_provider.load_event_evidence(event_id)

        lines = [
            f"# Codex Research Brief: {event.name}",
            "",
            "## Mission",
            "Use web/tools to gather only source-backed information available before the requested knowledge cutoff, then emit JSONL evidence claims matching docs/codex_llm_protocol.md.",
            "",
            "## Event Context",
            f"- event_id: `{event.event_id}`",
            f"- round: {event.round_number}",
            f"- date: {event.date}",
            f"- track_type: {event.track_type}",
            f"- laps: {event.laps}",
            f"- input_source: {event.feature_refs.get('event_source', 'seed')}",
            f"- wet_probability_prior: {event.weather_prior.get('wet_probability', 0.0)}",
            "",
            "## Leading Drivers In Seed State",
        ]
        for driver in drivers[:10]:
            team = season.teams[driver.team_id]
            lines.append(f"- {driver.name} ({team.name}): {driver.current_points} pts")

        lines.extend(
            [
                "",
                "## Required Source Classes",
                "- F1 official event, standings, and classification pages",
                "- FIA documents and race director notes",
                "- OpenF1/FastF1 session data if available",
                "- Team official upgrade or preview notes",
                "- Established F1 reporting from named outlets",
                "- Weather forecast or radar provider",
                "- Polymarket market rules and orderbook snapshots",
                "",
                "## Evidence Already Loaded",
            ]
        )
        if evidence:
            for claim in evidence:
                lines.append(
                    f"- {claim.claim_id}: {claim.target_id} {claim.metric} {claim.direction} "
                    f"confidence={claim.confidence} uncertainty={claim.uncertainty}"
                )
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Output Contract",
                f"Prefer a sources+claims manifest based on `data/research/{event.event_id}/research_packet_template.json`. Manual JSONL drafts should go to `data/research/{event.event_id}/draft_evidence.jsonl`; the prediction pipeline reads claims only after they are audited and archived under `data/evidence/{event.event_id}/packets/`. Each claim must include source_url, published_at, observed_at, metric, direction, magnitude, confidence, uncertainty, evidence_text, reasoning, and review_required.",
                "",
                "## Guardrails",
                "- Do not write final probabilities.",
                "- Do not use unsourced claims.",
                "- Do not use information after the knowledge cutoff.",
                "- Mark rumor or low-reliability sources as review_required.",
                "- Prefer multiple independent sources for high-impact claims.",
            ]
        )
        return "\n".join(lines) + "\n"
