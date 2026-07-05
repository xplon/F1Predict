"""Run registry, information intake snapshots, and matched prediction diffs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import EvidenceClaim, parse_dt, utc_now
from f1predict.intelligence.codex import CodexEvidenceProvider
from f1predict.storage import safe_name


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _stem_time(value: str | None) -> str:
    if not value:
        return "latest"
    return (
        value.replace(":", "")
        .replace("-", "")
        .replace("+", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 6) -> float:
    return round(_as_float(value), digits)


@dataclass(frozen=True)
class PredictionRunRecord:
    run_id: str
    event_id: str
    event_name: str
    created_at: str
    generated_at: str | None
    knowledge_cutoff: str | None
    iterations: int
    status: str
    formal_edge_ready: bool
    prediction_packet_path: str | None
    packet_payload_sha256: str | None
    input_fingerprint: str
    evidence_fingerprint: str
    probability_fingerprint: str
    information_intake_id: str | None
    information_intake_path: str | None
    summary: dict[str, Any]
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "created_at": self.created_at,
            "generated_at": self.generated_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "iterations": self.iterations,
            "status": self.status,
            "formal_edge_ready": self.formal_edge_ready,
            "prediction_packet_path": self.prediction_packet_path,
            "packet_payload_sha256": self.packet_payload_sha256,
            "input_fingerprint": self.input_fingerprint,
            "evidence_fingerprint": self.evidence_fingerprint,
            "probability_fingerprint": self.probability_fingerprint,
            "information_intake_id": self.information_intake_id,
            "information_intake_path": self.information_intake_path,
            "summary": self.summary,
            "notes": self.notes,
        }


class PredictionRunRegistry:
    """Append-only registry for prediction artifacts.

    A prediction packet says "what the model predicted". A run record says
    "this exact packet was a versioned prediction run and can be compared".
    """

    def __init__(self, root: Path | str = Path("reports/prediction_runs")) -> None:
        self.root = Path(root)
        self.runs_root = self.root / "runs"
        self.index_path = self.root / "index.json"

    def register_packet(
        self,
        packet_path: Path | str,
        information_intake_path: Path | str | None = None,
        notes: str | None = None,
    ) -> PredictionRunRecord:
        packet_file = Path(packet_path)
        packet = _read_json(packet_file)
        return self.register_payload(
            packet,
            prediction_packet_path=packet_file,
            information_intake_path=information_intake_path,
            notes=notes,
        )

    def register_payload(
        self,
        packet: dict[str, Any],
        prediction_packet_path: Path | str | None = None,
        information_intake_path: Path | str | None = None,
        notes: str | None = None,
    ) -> PredictionRunRecord:
        event_id = str(packet.get("event_id") or packet.get("prediction", {}).get("event", {}).get("event_id") or "")
        if not event_id:
            raise ValueError("Prediction packet is missing event_id")
        event_name = str(packet.get("event_name") or packet.get("prediction", {}).get("event", {}).get("name") or event_id)
        generated_at = packet.get("generated_at")
        knowledge_cutoff = packet.get("knowledge_cutoff")
        iterations = int(packet.get("iterations") or packet.get("prediction", {}).get("iterations") or 0)
        packet_hash = packet.get("packet_payload_sha256") or _canonical_hash(packet)
        input_fingerprint = self._input_fingerprint(packet)
        evidence_fingerprint = self._evidence_fingerprint(packet)
        probability_fingerprint = self._probability_fingerprint(packet)
        intake_id, intake_path_text = self._intake_ref(information_intake_path)
        run_id = safe_name(
            f"{event_id}_{_stem_time(str(knowledge_cutoff) if knowledge_cutoff else None)}_"
            f"{_stem_time(str(generated_at) if generated_at else None)}_{str(packet_hash)[:10]}"
        )
        record = PredictionRunRecord(
            run_id=run_id,
            event_id=event_id,
            event_name=event_name,
            created_at=utc_now().replace(microsecond=0).isoformat(),
            generated_at=str(generated_at) if generated_at else None,
            knowledge_cutoff=str(knowledge_cutoff) if knowledge_cutoff else None,
            iterations=iterations,
            status=str(packet.get("status") or "unknown"),
            formal_edge_ready=bool(packet.get("formal_edge_ready", False)),
            prediction_packet_path=str(prediction_packet_path) if prediction_packet_path else None,
            packet_payload_sha256=str(packet_hash) if packet_hash else None,
            input_fingerprint=input_fingerprint,
            evidence_fingerprint=evidence_fingerprint,
            probability_fingerprint=probability_fingerprint,
            information_intake_id=intake_id,
            information_intake_path=intake_path_text,
            summary=self._summary(packet),
            notes=notes,
        )
        return self.write(record)

    def write(self, record: PredictionRunRecord) -> PredictionRunRecord:
        run_dir = self.runs_root / safe_name(record.event_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_path = run_dir / f"{record.run_id}.prediction_run.json"
        run_path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_index(record, run_path)
        return record

    def load(self, run_id: str) -> PredictionRunRecord:
        for row in self._index().get("runs", []):
            if row.get("run_id") != run_id:
                continue
            path = row.get("path")
            if not path:
                break
            return self._record_from_dict(_read_json(path))
        for path in self.runs_root.rglob("*.prediction_run.json"):
            payload = _read_json(path)
            if payload.get("run_id") == run_id:
                return self._record_from_dict(payload)
        raise ValueError(f"Unknown prediction run_id: {run_id}")

    def list_records(self, event_id: str | None = None) -> list[PredictionRunRecord]:
        rows = []
        for row in self._index().get("runs", []):
            if event_id and row.get("event_id") != event_id:
                continue
            path = row.get("path")
            if path and Path(path).exists():
                rows.append(self._record_from_dict(_read_json(path)))
        return rows

    def latest(self, event_id: str, knowledge_cutoff: str | None = None) -> PredictionRunRecord | None:
        rows = [
            row for row in self.list_records(event_id)
            if knowledge_cutoff is None or row.knowledge_cutoff == knowledge_cutoff
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: (row.created_at, row.run_id))

    def _write_index(self, record: PredictionRunRecord, path: Path) -> None:
        payload = self._index()
        rows = [row for row in payload.get("runs", []) if row.get("run_id") != record.run_id]
        rows.append(
            {
                "run_id": record.run_id,
                "event_id": record.event_id,
                "event_name": record.event_name,
                "created_at": record.created_at,
                "generated_at": record.generated_at,
                "knowledge_cutoff": record.knowledge_cutoff,
                "status": record.status,
                "input_fingerprint": record.input_fingerprint,
                "evidence_fingerprint": record.evidence_fingerprint,
                "probability_fingerprint": record.probability_fingerprint,
                "information_intake_id": record.information_intake_id,
                "path": str(path),
            }
        )
        rows.sort(key=lambda row: (str(row.get("created_at")), str(row.get("run_id"))))
        payload = {
            "updated_at": utc_now().replace(microsecond=0).isoformat(),
            "run_count": len(rows),
            "runs": rows,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"runs": []}
        return _read_json(self.index_path)

    @staticmethod
    def _record_from_dict(payload: dict[str, Any]) -> PredictionRunRecord:
        return PredictionRunRecord(
            run_id=str(payload["run_id"]),
            event_id=str(payload["event_id"]),
            event_name=str(payload.get("event_name") or payload["event_id"]),
            created_at=str(payload["created_at"]),
            generated_at=payload.get("generated_at"),
            knowledge_cutoff=payload.get("knowledge_cutoff"),
            iterations=int(payload.get("iterations") or 0),
            status=str(payload.get("status") or "unknown"),
            formal_edge_ready=bool(payload.get("formal_edge_ready", False)),
            prediction_packet_path=payload.get("prediction_packet_path"),
            packet_payload_sha256=payload.get("packet_payload_sha256"),
            input_fingerprint=str(payload.get("input_fingerprint") or ""),
            evidence_fingerprint=str(payload.get("evidence_fingerprint") or ""),
            probability_fingerprint=str(payload.get("probability_fingerprint") or ""),
            information_intake_id=payload.get("information_intake_id"),
            information_intake_path=payload.get("information_intake_path"),
            summary=dict(payload.get("summary") or {}),
            notes=payload.get("notes"),
        )

    @staticmethod
    def _input_fingerprint(packet: dict[str, Any]) -> str:
        prediction = packet.get("prediction") if isinstance(packet.get("prediction"), dict) else {}
        return _canonical_hash(
            {
                "event_input_audit": packet.get("event_input_audit"),
                "market_context": packet.get("market_context"),
                "model_context": packet.get("model_context"),
                "evidence": prediction.get("evidence"),
                "feature_adjustments": prediction.get("feature_adjustments"),
                "event": prediction.get("event"),
                "knowledge_cutoff": packet.get("knowledge_cutoff"),
                "iterations": packet.get("iterations"),
            }
        )

    @staticmethod
    def _evidence_fingerprint(packet: dict[str, Any]) -> str:
        prediction = packet.get("prediction") if isinstance(packet.get("prediction"), dict) else {}
        return _canonical_hash(
            {
                "evidence": prediction.get("evidence"),
            }
        )

    @staticmethod
    def _probability_fingerprint(packet: dict[str, Any]) -> str:
        prediction = packet.get("prediction") if isinstance(packet.get("prediction"), dict) else {}
        return _canonical_hash(
            {
                "probability_summary": packet.get("probability_summary"),
                "race_probabilities": prediction.get("race_probabilities"),
                "market_edges": prediction.get("market_edges"),
            }
        )

    @staticmethod
    def _summary(packet: dict[str, Any]) -> dict[str, Any]:
        prediction = packet.get("prediction") if isinstance(packet.get("prediction"), dict) else {}
        probabilities = prediction.get("race_probabilities") or packet.get("probability_summary", {}).get("top_win_probabilities") or []
        driver_rows = []
        for row in probabilities:
            if not isinstance(row, dict) or not row.get("driver_id"):
                continue
            driver_rows.append(
                {
                    "driver_id": str(row.get("driver_id")),
                    "win": _round(row.get("win")),
                    "podium": _round(row.get("podium")),
                    "points": _round(row.get("points")),
                    "expected_points": _round(row.get("expected_points")),
                    "average_finish": _round(row.get("average_finish")),
                }
            )
        ranked = sorted(driver_rows, key=lambda row: (row["average_finish"] or 999.0, -row["expected_points"]))
        rank_by_driver = {row["driver_id"]: index for index, row in enumerate(ranked, start=1)}
        driver_probabilities = {
            row["driver_id"]: {**row, "expected_rank": rank_by_driver.get(row["driver_id"])}
            for row in driver_rows
        }
        codex_context = packet.get("codex_context") if isinstance(packet.get("codex_context"), dict) else {}
        market_context = packet.get("market_context") if isinstance(packet.get("market_context"), dict) else {}
        return {
            "driver_probabilities": driver_probabilities,
            "ranked_driver_ids": [row["driver_id"] for row in ranked],
            "top_win_driver_ids": [
                row["driver_id"]
                for row in sorted(driver_rows, key=lambda item: item["win"], reverse=True)[:8]
            ],
            "evidence_count": int(codex_context.get("evidence_count") or 0),
            "factor_trace_count": int(codex_context.get("factor_trace_count") or 0),
            "factor_route_counts": codex_context.get("factor_route_counts") or {},
            "market_snapshot_count": int(market_context.get("usable_snapshot_count") or 0),
            "market_edge_count": int(market_context.get("market_edge_count") or 0),
            "blocker_codes": list(packet.get("blocker_codes") or []),
            "warning_codes": list(packet.get("warning_codes") or []),
        }

    @staticmethod
    def _intake_ref(path: Path | str | None) -> tuple[str | None, str | None]:
        if path is None:
            return None, None
        payload = _read_json(path)
        return payload.get("intake_id"), str(path)


@dataclass(frozen=True)
class InformationIntakeRecord:
    intake_id: str
    event_id: str
    created_at: str
    knowledge_cutoff: str | None
    status: str
    claim_count: int
    unique_source_count: int
    claim_fingerprint: str
    source_fingerprint: str
    metric_counts: dict[str, int]
    target_counts: dict[str, int]
    direction_counts: dict[str, int]
    source_class_counts: dict[str, int]
    claim_ids: list[str]
    source_urls: list[str]
    evidence_paths: list[str]
    source_log_path: str | None
    source_candidate_report_path: str | None
    research_preflight_report_path: str | None
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "intake_id": self.intake_id,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "status": self.status,
            "claim_count": self.claim_count,
            "unique_source_count": self.unique_source_count,
            "claim_fingerprint": self.claim_fingerprint,
            "source_fingerprint": self.source_fingerprint,
            "metric_counts": self.metric_counts,
            "target_counts": self.target_counts,
            "direction_counts": self.direction_counts,
            "source_class_counts": self.source_class_counts,
            "claim_ids": self.claim_ids,
            "source_urls": self.source_urls,
            "evidence_paths": self.evidence_paths,
            "source_log_path": self.source_log_path,
            "source_candidate_report_path": self.source_candidate_report_path,
            "research_preflight_report_path": self.research_preflight_report_path,
            "warnings": self.warnings,
        }


class InformationIntakeStore:
    """Stores the local structured information available to a prediction run."""

    def __init__(
        self,
        root: Path | str = Path("data/intake"),
        evidence_provider: CodexEvidenceProvider | None = None,
        research_root: Path | str = Path("data/research"),
        reports_root: Path | str = Path("reports"),
    ) -> None:
        self.root = Path(root)
        self.evidence_provider = evidence_provider or CodexEvidenceProvider()
        self.research_root = Path(research_root)
        self.reports_root = Path(reports_root)

    def build(self, event_id: str, knowledge_cutoff: str | None = None) -> InformationIntakeRecord:
        cutoff_dt = parse_dt(knowledge_cutoff) if knowledge_cutoff else None
        claims = self.evidence_provider.load_event_evidence(event_id, cutoff_dt)
        source_log_path = self.research_root / safe_name(event_id) / "source_log.json"
        candidate_path = self.reports_root / "research_candidates" / f"{safe_name(event_id)}.json"
        preflight_path = self.reports_root / "research_preflight" / f"{safe_name(event_id)}.json"
        source_log = _read_json(source_log_path) if source_log_path.exists() else {}
        source_rows = source_log.get("sources") if isinstance(source_log.get("sources"), list) else []
        evidence_paths = [str(path) for path in self._evidence_paths(event_id) if path.exists()]
        warnings = self._warnings(claims, source_log_path, candidate_path, preflight_path)
        claim_payload = [claim.__dict__ for claim in sorted(claims, key=lambda item: item.claim_id)]
        source_urls = sorted({claim.source_url for claim in claims if claim.source_url})
        source_payload = {
            "claim_source_urls": source_urls,
            "source_log_urls": sorted(
                {
                    str(row.get("url"))
                    for row in source_rows
                    if isinstance(row, dict) and row.get("url")
                }
            ),
        }
        status = self._status(claims, warnings)
        claim_hash = _canonical_hash(claim_payload)
        source_hash = _canonical_hash(source_payload)
        intake_id = safe_name(
            f"{event_id}_{_stem_time(knowledge_cutoff)}_{claim_hash[:10]}_{source_hash[:10]}"
        )
        return InformationIntakeRecord(
            intake_id=intake_id,
            event_id=event_id,
            created_at=utc_now().replace(microsecond=0).isoformat(),
            knowledge_cutoff=knowledge_cutoff,
            status=status,
            claim_count=len(claims),
            unique_source_count=len(source_urls),
            claim_fingerprint=claim_hash,
            source_fingerprint=source_hash,
            metric_counts=self._count(claims, "metric"),
            target_counts=self._target_counts(claims),
            direction_counts=self._count(claims, "direction"),
            source_class_counts=self._source_class_counts(source_rows),
            claim_ids=[claim.claim_id for claim in sorted(claims, key=lambda item: item.claim_id)],
            source_urls=source_urls,
            evidence_paths=evidence_paths,
            source_log_path=str(source_log_path) if source_log_path.exists() else None,
            source_candidate_report_path=str(candidate_path) if candidate_path.exists() else None,
            research_preflight_report_path=str(preflight_path) if preflight_path.exists() else None,
            warnings=warnings,
        )

    def write(self, record: InformationIntakeRecord) -> Path:
        directory = self.root / safe_name(record.event_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record.intake_id}.information_intake.json"
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_index(record, path)
        return path

    def build_and_write(self, event_id: str, knowledge_cutoff: str | None = None) -> tuple[InformationIntakeRecord, Path]:
        record = self.build(event_id, knowledge_cutoff=knowledge_cutoff)
        return record, self.write(record)

    def _write_index(self, record: InformationIntakeRecord, path: Path) -> None:
        index_path = self.root / "index.json"
        payload = _read_json(index_path) if index_path.exists() else {"intakes": []}
        rows = [row for row in payload.get("intakes", []) if row.get("intake_id") != record.intake_id]
        rows.append(
            {
                "intake_id": record.intake_id,
                "event_id": record.event_id,
                "created_at": record.created_at,
                "knowledge_cutoff": record.knowledge_cutoff,
                "status": record.status,
                "claim_count": record.claim_count,
                "unique_source_count": record.unique_source_count,
                "claim_fingerprint": record.claim_fingerprint,
                "source_fingerprint": record.source_fingerprint,
                "path": str(path),
            }
        )
        rows.sort(key=lambda row: (str(row.get("created_at")), str(row.get("intake_id"))))
        payload = {
            "updated_at": utc_now().replace(microsecond=0).isoformat(),
            "intake_count": len(rows),
            "intakes": rows,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _evidence_paths(self, event_id: str) -> list[Path]:
        paths = []
        legacy = self.evidence_provider.evidence_dir / f"{event_id}.jsonl"
        if legacy.exists():
            paths.append(legacy)
        paths.extend(self.evidence_provider.packet_store.event_packet_paths(event_id))
        return sorted(paths)

    @staticmethod
    def _warnings(
        claims: list[EvidenceClaim],
        source_log_path: Path,
        candidate_path: Path,
        preflight_path: Path,
    ) -> list[str]:
        warnings = []
        if not claims:
            warnings.append("no_codex_claims_available")
        if any(claim.review_required for claim in claims):
            warnings.append("claims_require_review")
        if not source_log_path.exists():
            warnings.append("source_log_missing")
        if not candidate_path.exists():
            warnings.append("source_candidate_report_missing")
        if not preflight_path.exists():
            warnings.append("research_preflight_report_missing")
        return warnings

    @staticmethod
    def _status(claims: list[EvidenceClaim], warnings: list[str]) -> str:
        if not claims:
            return "no_information_intake"
        if any(warning.endswith("_missing") for warning in warnings):
            return "intake_with_missing_audit_artifacts"
        if "claims_require_review" in warnings:
            return "intake_ready_with_review_risks"
        return "intake_ready"

    @staticmethod
    def _count(claims: list[EvidenceClaim], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for claim in claims:
            value = str(getattr(claim, field))
            counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _target_counts(claims: list[EvidenceClaim]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for claim in claims:
            key = f"{claim.target_type}:{claim.target_id}"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _source_class_counts(source_rows: list[Any]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("source_class") or row.get("source_type") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))


@dataclass(frozen=True)
class PredictionRunDiff:
    diff_id: str
    generated_at: str
    base_run_id: str
    candidate_run_id: str
    event_id: str
    match_warnings: list[str]
    input_changed: bool
    evidence_changed: bool
    probability_changed: bool
    information_intake_changed: bool
    driver_deltas: list[dict[str, Any]]
    largest_changes: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "diff_id": self.diff_id,
            "generated_at": self.generated_at,
            "base_run_id": self.base_run_id,
            "candidate_run_id": self.candidate_run_id,
            "event_id": self.event_id,
            "match_warnings": self.match_warnings,
            "input_changed": self.input_changed,
            "evidence_changed": self.evidence_changed,
            "probability_changed": self.probability_changed,
            "information_intake_changed": self.information_intake_changed,
            "driver_deltas": self.driver_deltas,
            "largest_changes": self.largest_changes,
            "summary": self.summary,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prediction Run Diff: {self.event_id}",
            "",
            f"- Base run: `{self.base_run_id}`",
            f"- Candidate run: `{self.candidate_run_id}`",
            f"- Generated at: `{self.generated_at}`",
            f"- Input changed: `{self.input_changed}`",
            f"- Evidence changed: `{self.evidence_changed}`",
            f"- Probability changed: `{self.probability_changed}`",
            f"- Information intake changed: `{self.information_intake_changed}`",
            "",
            "## Summary",
            "",
        ]
        for key, value in self.summary.items():
            lines.append(f"- `{key}`: {value}")
        if self.match_warnings:
            lines.extend(["", "## Match Warnings", ""])
            for warning in self.match_warnings:
                lines.append(f"- `{warning}`")
        lines.extend(["", "## Largest Driver Changes", ""])
        for row in self.largest_changes[:10]:
            lines.append(
                f"- `{row['driver_id']}` win_delta={row['win_delta']:+.4f}, "
                f"expected_points_delta={row['expected_points_delta']:+.3f}, "
                f"rank_delta={row['expected_rank_delta']:+d}"
            )
        return "\n".join(lines).rstrip() + "\n"


class MatchedPredictionDiff:
    """Compares two registered prediction runs under the same output schema."""

    def __init__(
        self,
        registry: PredictionRunRegistry | None = None,
        output_dir: Path | str = Path("reports/prediction_diffs"),
    ) -> None:
        self.registry = registry or PredictionRunRegistry()
        self.output_dir = Path(output_dir)

    def build(self, base_run_id: str, candidate_run_id: str) -> PredictionRunDiff:
        base = self.registry.load(base_run_id)
        candidate = self.registry.load(candidate_run_id)
        warnings = self._match_warnings(base, candidate)
        driver_deltas = self._driver_deltas(base, candidate)
        largest = sorted(
            driver_deltas,
            key=lambda row: (
                abs(row["win_delta"]),
                abs(row["expected_points_delta"]),
                abs(row["expected_rank_delta"]),
            ),
            reverse=True,
        )
        changed = [
            row for row in driver_deltas
            if abs(row["win_delta"]) > 0.000001
            or abs(row["podium_delta"]) > 0.000001
            or abs(row["expected_points_delta"]) > 0.000001
            or row["expected_rank_delta"] != 0
        ]
        material = [
            row for row in changed
            if abs(row["win_delta"]) >= 0.005
            or abs(row["podium_delta"]) >= 0.01
            or abs(row["expected_points_delta"]) >= 0.10
            or abs(row["expected_rank_delta"]) >= 1
        ]
        diff_hash = _canonical_hash({"base_run_id": base.run_id, "candidate_run_id": candidate.run_id})[:12]
        diff_id = safe_name(f"{base.event_id}_{_stem_time(candidate.knowledge_cutoff)}_{diff_hash}")
        return PredictionRunDiff(
            diff_id=diff_id,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            base_run_id=base.run_id,
            candidate_run_id=candidate.run_id,
            event_id=candidate.event_id,
            match_warnings=warnings,
            input_changed=base.input_fingerprint != candidate.input_fingerprint,
            evidence_changed=base.evidence_fingerprint != candidate.evidence_fingerprint,
            probability_changed=base.probability_fingerprint != candidate.probability_fingerprint,
            information_intake_changed=base.information_intake_id != candidate.information_intake_id,
            driver_deltas=driver_deltas,
            largest_changes=largest[:10],
            summary={
                "driver_count": len(driver_deltas),
                "changed_driver_count": len(changed),
                "material_driver_change_count": len(material),
                "max_abs_win_delta": max((abs(row["win_delta"]) for row in driver_deltas), default=0.0),
                "max_abs_expected_points_delta": max(
                    (abs(row["expected_points_delta"]) for row in driver_deltas),
                    default=0.0,
                ),
                "rank_change_count": sum(1 for row in driver_deltas if row["expected_rank_delta"] != 0),
            },
        )

    def write(self, diff: PredictionRunDiff) -> dict[str, Path]:
        directory = self.output_dir / safe_name(diff.event_id)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{diff.diff_id}.prediction_diff.json"
        markdown_path = directory / f"{diff.diff_id}.prediction_diff.md"
        json_path.write_text(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(diff.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    @staticmethod
    def _match_warnings(base: PredictionRunRecord, candidate: PredictionRunRecord) -> list[str]:
        warnings = []
        if base.event_id != candidate.event_id:
            warnings.append("event_id_mismatch")
        if base.knowledge_cutoff != candidate.knowledge_cutoff:
            warnings.append("knowledge_cutoff_mismatch")
        if base.iterations != candidate.iterations:
            warnings.append("iteration_count_mismatch")
        if base.status != candidate.status:
            warnings.append("status_mismatch")
        return warnings

    @staticmethod
    def _driver_deltas(base: PredictionRunRecord, candidate: PredictionRunRecord) -> list[dict[str, Any]]:
        base_rows = base.summary.get("driver_probabilities") or {}
        candidate_rows = candidate.summary.get("driver_probabilities") or {}
        driver_ids = sorted(set(base_rows) | set(candidate_rows))
        rows = []
        for driver_id in driver_ids:
            base_row = base_rows.get(driver_id) or {}
            candidate_row = candidate_rows.get(driver_id) or {}
            base_rank = int(base_row.get("expected_rank") or 0)
            candidate_rank = int(candidate_row.get("expected_rank") or 0)
            rows.append(
                {
                    "driver_id": driver_id,
                    "base_win": _round(base_row.get("win")),
                    "candidate_win": _round(candidate_row.get("win")),
                    "win_delta": round(_as_float(candidate_row.get("win")) - _as_float(base_row.get("win")), 6),
                    "base_podium": _round(base_row.get("podium")),
                    "candidate_podium": _round(candidate_row.get("podium")),
                    "podium_delta": round(
                        _as_float(candidate_row.get("podium")) - _as_float(base_row.get("podium")),
                        6,
                    ),
                    "base_expected_points": _round(base_row.get("expected_points"), 4),
                    "candidate_expected_points": _round(candidate_row.get("expected_points"), 4),
                    "expected_points_delta": round(
                        _as_float(candidate_row.get("expected_points")) - _as_float(base_row.get("expected_points")),
                        4,
                    ),
                    "base_average_finish": _round(base_row.get("average_finish"), 4),
                    "candidate_average_finish": _round(candidate_row.get("average_finish"), 4),
                    "average_finish_delta": round(
                        _as_float(candidate_row.get("average_finish")) - _as_float(base_row.get("average_finish")),
                        4,
                    ),
                    "base_expected_rank": base_rank,
                    "candidate_expected_rank": candidate_rank,
                    "expected_rank_delta": candidate_rank - base_rank if base_rank and candidate_rank else 0,
                }
            )
        return rows
