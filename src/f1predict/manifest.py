"""Replay freeze manifests for reproducible diagnostic runs."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size_bytes: int
    sha256: str
    modified_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True)
class ManifestArtifactGroup:
    group_id: str
    title: str
    patterns: tuple[str, ...]
    file_count: int
    total_bytes: int
    content_sha256: str
    errors: tuple[str, ...]
    files: tuple[ManifestFile, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "title": self.title,
            "patterns": list(self.patterns),
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "content_sha256": self.content_sha256,
            "errors": list(self.errors),
            "files": [file.to_dict() for file in self.files],
        }


@dataclass(frozen=True)
class ReplayFreezeManifest:
    year: int
    as_of: str
    generated_at: str
    status: str
    manifest_payload_sha256: str
    python: dict[str, Any]
    command_plan: tuple[str, ...]
    report_summaries: dict[str, Any]
    integrity_flags: tuple[str, ...]
    artifact_groups: tuple[ManifestArtifactGroup, ...]

    def to_dict(self, include_payload_hash: bool = True) -> dict[str, Any]:
        payload = {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "python": self.python,
            "command_plan": list(self.command_plan),
            "report_summaries": self.report_summaries,
            "integrity_flags": list(self.integrity_flags),
            "artifact_groups": [group.to_dict() for group in self.artifact_groups],
        }
        if include_payload_hash:
            payload["manifest_payload_sha256"] = self.manifest_payload_sha256
        return payload

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict Replay Freeze Manifest ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Manifest payload SHA-256: `{self.manifest_payload_sha256}`",
            "",
            "## Report Summaries",
            "",
        ]
        for report_id, summary in self.report_summaries.items():
            lines.extend(
                [
                    f"### {report_id}",
                    "",
                    f"- Status: {summary.get('status')}",
                    f"- Path: `{summary.get('path') or 'n/a'}`",
                ]
            )
            for key, value in summary.get("summary", {}).items():
                lines.append(f"- {key}: {value}")
            lines.append("")
        lines.extend(["## Artifact Groups", ""])
        for group in self.artifact_groups:
            lines.extend(
                [
                    f"### {group.title} (`{group.group_id}`)",
                    "",
                    f"- Files: {group.file_count}",
                    f"- Bytes: {group.total_bytes}",
                    f"- Content SHA-256: `{group.content_sha256}`",
                ]
            )
            if group.errors:
                lines.append("- Errors:")
                for error in group.errors:
                    lines.append(f"  - {error}")
            lines.append("")
        if self.integrity_flags:
            lines.extend(["## Integrity Flags", ""])
            for flag in self.integrity_flags:
                lines.append(f"- {flag}")
            lines.append("")
        lines.extend(["## Command Plan", ""])
        for command in self.command_plan:
            lines.append(f"- `{command}`")
        return "\n".join(lines).rstrip() + "\n"


class ReplayFreezeManifestBuilder:
    """Builds a hashable manifest for a replay/evaluation state."""

    GROUP_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        (
            "source_code",
            "Source Code and CLI Scripts",
            ("src/**/*.py", "scripts/**/*.py", "pyproject.toml"),
        ),
        (
            "frontend",
            "Frontend Assets",
            ("web/**/*",),
        ),
        (
            "input_data",
            "Prediction and Replay Input Data",
            ("data/**/*",),
        ),
        (
            "diagnostic_reports",
            "Generated Diagnostic Reports",
            ("reports/**/*.json", "reports/**/*.md"),
        ),
    )

    EXCLUDED_PARTS = {".git", ".venv", "__pycache__"}
    EXCLUDED_PREFIXES = ("reports/replay_freeze/",)

    def __init__(self, workspace_root: Path | str = Path(".")) -> None:
        self.workspace_root = Path(workspace_root)

    def build(self, year: int, as_of: str, iterations: int = 1200) -> ReplayFreezeManifest:
        groups = tuple(self._artifact_group(group_id, title, patterns) for group_id, title, patterns in self.GROUP_SPECS)
        report_summaries = self._report_summaries(year, as_of)
        flags = self._integrity_flags(groups, report_summaries)
        status = self._status(flags, report_summaries)
        manifest = ReplayFreezeManifest(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            status=status,
            manifest_payload_sha256="",
            python={
                "version": sys.version.split()[0],
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
            command_plan=self._command_plan(year, as_of, iterations),
            report_summaries=report_summaries,
            integrity_flags=flags,
            artifact_groups=groups,
        )
        payload_hash = self._payload_sha256(manifest.to_dict(include_payload_hash=False))
        return ReplayFreezeManifest(
            year=manifest.year,
            as_of=manifest.as_of,
            generated_at=manifest.generated_at,
            status=manifest.status,
            manifest_payload_sha256=payload_hash,
            python=manifest.python,
            command_plan=manifest.command_plan,
            report_summaries=manifest.report_summaries,
            integrity_flags=manifest.integrity_flags,
            artifact_groups=manifest.artifact_groups,
        )

    def write(
        self,
        year: int,
        as_of: str,
        iterations: int = 1200,
        output_dir: Path | str = Path("reports/replay_freeze"),
    ) -> dict[str, Path]:
        manifest = self.build(year, as_of, iterations)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        json_path = directory / f"{stem}.freeze.json"
        markdown_path = directory / f"{stem}.freeze.md"
        json_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(manifest.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def _artifact_group(
        self,
        group_id: str,
        title: str,
        patterns: tuple[str, ...],
    ) -> ManifestArtifactGroup:
        files: list[ManifestFile] = []
        errors: list[str] = []
        for path in self._matched_files(patterns):
            try:
                files.append(self._manifest_file(path))
            except OSError as exc:
                errors.append(f"{self._relative(path)}: {exc}")
        files.sort(key=lambda file: file.path)
        return ManifestArtifactGroup(
            group_id=group_id,
            title=title,
            patterns=patterns,
            file_count=len(files),
            total_bytes=sum(file.size_bytes for file in files),
            content_sha256=self._group_sha256(files),
            errors=tuple(errors),
            files=tuple(files),
        )

    def _matched_files(self, patterns: tuple[str, ...]) -> tuple[Path, ...]:
        paths: dict[str, Path] = {}
        for pattern in patterns:
            for path in self.workspace_root.glob(pattern):
                if not path.is_file() or self._excluded(path):
                    continue
                paths[self._relative(path)] = path
        return tuple(paths[key] for key in sorted(paths))

    def _manifest_file(self, path: Path) -> ManifestFile:
        stat = path.stat()
        return ManifestFile(
            path=self._relative(path),
            size_bytes=stat.st_size,
            sha256=self._file_sha256(path),
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        )

    def _excluded(self, path: Path) -> bool:
        relative = self._relative(path)
        if any(part in self.EXCLUDED_PARTS for part in path.parts):
            return True
        return any(relative.startswith(prefix) for prefix in self.EXCLUDED_PREFIXES)

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.workspace_root.resolve()).as_posix()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _group_sha256(files: list[ManifestFile]) -> str:
        digest = hashlib.sha256()
        for file in files:
            digest.update(file.path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(file.size_bytes).encode("ascii"))
            digest.update(b"\0")
            digest.update(file.sha256.encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _report_summaries(self, year: int, as_of: str) -> dict[str, Any]:
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        report_paths = {
            "replay_coverage": Path("reports/replay") / f"{stem}.json",
            "replay_analysis": Path("reports/replay_analysis") / f"{stem}.analysis.json",
            "formal_readiness": Path("reports/formal_readiness") / f"{stem}.readiness.json",
            "calibration": Path("reports/calibration") / f"{stem}.calibration.json",
            "model_error_review": Path("reports/model_error_review") / f"{stem}.model_error_review.json",
            "improvement_plan": Path("reports/improvement_plan") / f"{stem}.improvement_plan.json",
            "source_replacements": Path("reports/source_replacements/remaining_blockers.source_replacements.json"),
        }
        summaries: dict[str, Any] = {}
        for report_id, relative_path in report_paths.items():
            path = self.workspace_root / relative_path
            summaries[report_id] = self._report_summary(report_id, path)
        return summaries

    def _report_summary(self, report_id: str, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"status": "missing", "path": self._relative_if_possible(path), "summary": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "status": "invalid_json",
                "path": self._relative_if_possible(path),
                "summary": {"error": str(exc)},
            }
        summary_extractors = {
            "replay_coverage": self._replay_coverage_summary,
            "replay_analysis": self._replay_analysis_summary,
            "formal_readiness": self._formal_readiness_summary,
            "calibration": self._calibration_summary,
            "model_error_review": self._model_error_review_summary,
            "improvement_plan": self._improvement_plan_summary,
            "source_replacements": self._source_replacement_summary,
        }
        summary = summary_extractors.get(report_id, lambda value: {})(payload)
        return {"status": "present", "path": self._relative_if_possible(path), "summary": summary}

    def _relative_if_possible(self, path: Path) -> str:
        try:
            return self._relative(path)
        except ValueError:
            return str(path)

    @staticmethod
    def _replay_coverage_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "due_events": payload.get("due_events"),
            "replayed_events": payload.get("replayed_events"),
            "result_available_events": payload.get("result_available_events"),
            "missing_due_events": payload.get("missing_due_events"),
        }

    @staticmethod
    def _replay_analysis_summary(payload: dict[str, Any]) -> dict[str, Any]:
        coverage = payload.get("replay_coverage", {})
        metrics = payload.get("diagnostic_metrics", {})
        return {
            "status": payload.get("status"),
            "formal_backtest_ready": payload.get("formal_backtest_ready"),
            "due_events": coverage.get("due_events"),
            "replayed_events": coverage.get("replayed_events"),
            "top_pick_hit_rate": metrics.get("top_pick_hit_rate"),
            "root_cause_count": len(payload.get("root_causes", [])),
        }

    @staticmethod
    def _formal_readiness_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": payload.get("status"),
            "formal_backtest_ready": payload.get("formal_backtest_ready"),
            "blocking_action_count": payload.get("blocking_action_count"),
            "warning_action_count": payload.get("warning_action_count"),
            "workstream_count": len(payload.get("workstreams", [])),
            "action_category_counts": payload.get("action_category_counts", {}),
        }

    @staticmethod
    def _calibration_summary(payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary", {})
        return {
            "status": payload.get("status"),
            "formal_probability_claim_ready": payload.get("formal_probability_claim_ready"),
            "scored_events": payload.get("scored_events"),
            "market_scored_events": payload.get("market_scored_events"),
            "top_pick_hit_rate": summary.get("top_pick_hit_rate"),
            "mean_winner_brier_score": summary.get("mean_winner_brier_score"),
        }

    @staticmethod
    def _model_error_review_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": payload.get("status"),
            "formal_model_claim_ready": payload.get("formal_model_claim_ready"),
            "reviewed_events": payload.get("reviewed_events"),
            "missed_events": payload.get("missed_events"),
            "issue_counts": payload.get("issue_counts", {}),
        }

    @staticmethod
    def _improvement_plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": payload.get("status"),
            "formal_edge_ready": payload.get("formal_edge_ready"),
            "top_priority": payload.get("top_priority"),
            "blocking_workstream_count": payload.get("blocking_workstream_count"),
            "diagnostic_workstream_count": payload.get("diagnostic_workstream_count"),
        }

    @staticmethod
    def _source_replacement_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": payload.get("status"),
            "blocker_count": payload.get("blocker_count"),
            "candidate_count": payload.get("candidate_count"),
            "cutoff_valid_replacement_count": payload.get("cutoff_valid_replacement_count"),
            "event_status_counts": payload.get("event_status_counts", {}),
            "status_counts": payload.get("status_counts", {}),
        }

    @staticmethod
    def _integrity_flags(
        groups: tuple[ManifestArtifactGroup, ...],
        report_summaries: dict[str, Any],
    ) -> tuple[str, ...]:
        flags: list[str] = []
        if any(group.errors for group in groups):
            flags.append("artifact_hash_errors_present")
        missing_reports = [
            report_id for report_id, summary in report_summaries.items() if summary.get("status") != "present"
        ]
        for report_id in missing_reports:
            flags.append(f"missing_report:{report_id}")
        readiness = report_summaries.get("formal_readiness", {}).get("summary", {})
        if readiness and not readiness.get("formal_backtest_ready"):
            flags.append("formal_edge_claim_not_ready")
        calibration = report_summaries.get("calibration", {}).get("summary", {})
        if calibration and not calibration.get("formal_probability_claim_ready"):
            flags.append("probability_calibration_diagnostic_only")
        if readiness.get("blocking_action_count"):
            flags.append(f"readiness_blockers:{readiness.get('blocking_action_count')}")
        replacements = report_summaries.get("source_replacements", {}).get("summary", {})
        if replacements.get("candidate_count") and not replacements.get("cutoff_valid_replacement_count"):
            flags.append("source_replacements_need_archive_proof")
        return tuple(flags)

    @staticmethod
    def _status(flags: tuple[str, ...], report_summaries: dict[str, Any]) -> str:
        if any(flag.startswith("missing_report:") for flag in flags) or "artifact_hash_errors_present" in flags:
            return "incomplete_freeze"
        readiness = report_summaries.get("formal_readiness", {}).get("summary", {})
        if readiness.get("formal_backtest_ready"):
            return "formal_ready_freeze"
        return "diagnostic_freeze_inputs_required"

    @staticmethod
    def _command_plan(year: int, as_of: str, iterations: int) -> tuple[str, ...]:
        return (
            f"python -m f1predict.cli replay-report --year {year} --as-of {as_of} --write",
            f"python -m f1predict.cli analyze-replay --year {year} --as-of {as_of} --iterations {iterations} --write",
            f"python -m f1predict.cli formal-readiness --year {year} --as-of {as_of} --iterations {iterations} --write",
            f"python -m f1predict.cli calibration-report --year {year} --as-of {as_of} --iterations {iterations} --write",
            f"python -m f1predict.cli model-error-review --year {year} --as-of {as_of} --iterations {iterations} --write",
            f"python -m f1predict.cli improvement-plan --year {year} --as-of {as_of} --iterations {iterations} --write",
            "python -m f1predict.cli source-replacement-candidates --write",
            f"python -m f1predict.cli replay-freeze-manifest --year {year} --as-of {as_of} --iterations {iterations} --write",
            f"python -m f1predict.cli mvp-gate --year {year} --as-of {as_of} --write",
        )

    @staticmethod
    def _payload_sha256(payload: dict[str, Any]) -> str:
        stable_payload = ReplayFreezeManifestBuilder._stable_hash_payload(payload)
        encoded = json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _stable_hash_payload(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ReplayFreezeManifestBuilder._stable_hash_payload(item)
                for key, item in value.items()
                if key not in {"generated_at", "modified_at"}
            }
        if isinstance(value, list):
            return [ReplayFreezeManifestBuilder._stable_hash_payload(item) for item in value]
        return value

    @staticmethod
    def _stem_time(value: str) -> str:
        return value.replace(":", "").replace("+", "_").replace("-", "")
