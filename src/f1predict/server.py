"""Local API and static frontend server."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from f1predict.backtest import Backtester
from f1predict.calibration import ReplayCalibrationBuilder
from f1predict.chronological_replay import ChronologicalReplayBundleBuilder
from f1predict.intelligence.research_packet import CodexResearchPacketPreflight
from f1predict.intelligence.research_plan import CodexResearchPlanBuilder
from f1predict.intelligence.source_candidates import CodexSourceCandidateBuilder
from f1predict.manifest import ReplayFreezeManifestBuilder
from f1predict.model_error_review import ModelErrorReviewBuilder
from f1predict.mvp_gate import MVPGateBuilder
from f1predict.official_standings import OfficialStandingsRepository
from f1predict.pipeline import PredictionPipeline
from f1predict.prediction_packet import PredictionPacketBuilder
from f1predict.readiness import FormalReadinessBuilder
from f1predict.replay_analysis import ReplayAnalysisBuilder
from f1predict.replay_artifacts import DEFAULT_REPLAY_AS_OF, latest_replay_as_of, stem_time
from f1predict.simulator_calibration import SimulatorCalibrationBuilder
from f1predict.source_replacements import DEFAULT_REPLACEMENT_REPORT


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"


class AppHandler(BaseHTTPRequestHandler):
    pipeline = PredictionPipeline(iterations=3000)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API.
        parsed = urlparse(self.path)
        if parsed.path == "/api/events":
            self._json(self.pipeline.list_events())
            return
        if parsed.path == "/api/prediction":
            query = parse_qs(parsed.query)
            event_id = query.get("event_id", ["british_gp"])[0]
            cutoff = query.get("knowledge_cutoff", [None])[0]
            try:
                report = self.pipeline.predict_event(event_id, cutoff)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(report.to_dict())
            return
        if parsed.path == "/api/prediction-packet":
            query = parse_qs(parsed.query)
            event_id = query.get("event_id", ["british_gp"])[0]
            cutoff = query.get("knowledge_cutoff", [None])[0]
            iterations = int(query.get("iterations", ["1200"])[0])
            try:
                packet = PredictionPacketBuilder(PredictionPipeline(iterations=iterations)).build(
                    event_id,
                    knowledge_cutoff=cutoff,
                    iterations=iterations,
                )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(packet.to_dict())
            return
        if parsed.path == "/api/codex-research-plan":
            query = parse_qs(parsed.query)
            event_id = query.get("event_id", ["british_gp"])[0]
            cutoff = query.get("knowledge_cutoff", [None])[0]
            try:
                plan = CodexResearchPlanBuilder().build(event_id, knowledge_cutoff=cutoff)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(plan.to_dict())
            return
        if parsed.path == "/api/research-preflight":
            query = parse_qs(parsed.query)
            event_id = query.get("event_id", ["british_gp"])[0]
            cutoff = query.get("knowledge_cutoff", [None])[0]
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                payload = self._research_preflight_payload(event_id, cutoff, live=live)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/source-candidates":
            query = parse_qs(parsed.query)
            event_id = query.get("event_id", ["british_gp"])[0]
            cutoff = query.get("knowledge_cutoff", [None])[0]
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                payload = self._source_candidates_payload(event_id, cutoff, live=live)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/season-forecast":
            query = parse_qs(parsed.query)
            cutoff = query.get("knowledge_cutoff", [None])[0]
            iterations = int(query.get("iterations", ["1200"])[0])
            try:
                report = self.pipeline.forecast_season(cutoff, iterations=iterations)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(report.to_dict())
            return
        if parsed.path == "/api/official-standings":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            cutoff = query.get("knowledge_cutoff", [None])[0]
            try:
                season = self.pipeline.data_source.load()
                report = OfficialStandingsRepository().build(year, season=season, knowledge_cutoff=cutoff)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            payload = report.to_dict()
            payload["source"] = "stored_f1_official_snapshots"
            self._json(payload)
            return
        if parsed.path == "/api/backtest":
            rows = [row.__dict__ for row in Backtester(self.pipeline).run_seed_replay()]
            self._json(rows)
            return
        if parsed.path == "/api/chronological-replay":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="chronological_replay",
                suffix=".chronological_replay.json",
            )
            iterations = int(query.get("iterations", ["1200"])[0])
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = ChronologicalReplayBundleBuilder(
                        PredictionPipeline(iterations=iterations)
                    ).build(year, as_of, iterations=iterations).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._chronological_replay_payload(year, as_of)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/replay-analysis":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="replay_analysis",
                suffix=".analysis.json",
            )
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = ReplayAnalysisBuilder(self.pipeline).build(year, as_of).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="replay_analysis",
                        suffix=".analysis.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/formal-readiness":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="formal_readiness",
                suffix=".readiness.json",
            )
            iterations = int(query.get("iterations", ["800"])[0])
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = FormalReadinessBuilder(PredictionPipeline(iterations=iterations)).build(year, as_of).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="formal_readiness",
                        suffix=".readiness.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/readiness-intake":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="readiness_intake",
                directories=True,
            )
            limit = int(query.get("limit", ["8"])[0])
            try:
                payload = self._readiness_intake_payload(year, as_of, limit)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/market-readiness":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="market_readiness",
                suffix=".market_readiness.json",
            )
            try:
                payload = self._market_readiness_payload(year, as_of)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/source-readiness":
            try:
                payload = self._source_readiness_payload()
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/source-replacements":
            try:
                payload = self._source_replacements_payload()
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/improvement-plan":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="improvement_plan",
                suffix=".improvement_plan.json",
            )
            try:
                payload = self._improvement_plan_payload(year, as_of)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, status=404)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/calibration-report":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="calibration",
                suffix=".calibration.json",
            )
            iterations = int(query.get("iterations", ["800"])[0])
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = ReplayCalibrationBuilder(PredictionPipeline(iterations=iterations)).build(year, as_of).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="calibration",
                        suffix=".calibration.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/model-error-review":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="model_error_review",
                suffix=".model_error_review.json",
            )
            iterations = int(query.get("iterations", ["800"])[0])
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = ModelErrorReviewBuilder(PredictionPipeline(iterations=iterations)).build(year, as_of).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="model_error_review",
                        suffix=".model_error_review.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/simulator-calibration":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="simulator_calibration",
                suffix=".simulator_calibration.json",
            )
            iterations = int(query.get("iterations", ["800"])[0])
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = SimulatorCalibrationBuilder(PredictionPipeline(iterations=iterations)).build(
                        year,
                        as_of,
                        iterations=iterations,
                    ).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="simulator_calibration",
                        suffix=".simulator_calibration.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/mvp-gate":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="mvp_gate",
                suffix=".mvp_gate.json",
            )
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = MVPGateBuilder().build(year, as_of).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="mvp_gate",
                        suffix=".mvp_gate.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/api/replay-freeze-manifest":
            query = parse_qs(parsed.query)
            year = int(query.get("year", ["2026"])[0])
            as_of = self._as_of_from_query(
                query,
                year,
                report_dir="replay_freeze",
                suffix=".freeze.json",
            )
            iterations = int(query.get("iterations", ["1200"])[0])
            live = query.get("live", ["0"])[0] in {"1", "true", "yes"}
            try:
                if live:
                    payload = ReplayFreezeManifestBuilder().build(year, as_of, iterations).to_dict()
                    payload["source"] = "live_build"
                else:
                    payload = self._report_payload(
                        year,
                        as_of,
                        report_dir="replay_freeze",
                        suffix=".freeze.json",
                    )
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, status=400)
                return
            self._json(payload)
            return
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self._static(parsed.path)

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if not str(candidate).startswith(str(WEB_ROOT.resolve())) or not candidate.exists():
            self.send_error(404)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or {
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(candidate.suffix.lower(), "application/octet-stream")
        if content_type.startswith("text/") or candidate.suffix in {".js", ".css"}:
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _readiness_intake_payload(self, year: int, as_of: str, limit: int) -> dict[str, object]:
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        bundle_dir = ROOT / "reports" / "readiness_intake" / stem
        manifest_path = bundle_dir / "intake_manifest.json"
        actions_path = bundle_dir / "actions.jsonl"
        if not manifest_path.exists():
            raise FileNotFoundError(f"readiness intake manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        action_preview = self._read_jsonl_preview(actions_path, limit)
        manifest["action_preview"] = action_preview
        manifest["action_preview_count"] = len(action_preview)
        manifest["source"] = "disk_snapshot"
        return manifest

    def _market_readiness_payload(self, year: int, as_of: str) -> dict[str, object]:
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        report_path = ROOT / "reports" / "market_readiness" / f"{stem}.market_readiness.json"
        if not report_path.exists():
            raise FileNotFoundError(f"market readiness report not found: {report_path}")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        payload["source"] = "disk_snapshot"
        payload["report_path"] = str(report_path.relative_to(ROOT))
        return payload

    def _source_readiness_payload(self) -> dict[str, object]:
        source_dir = ROOT / "reports" / "source_archives"
        full_path = source_dir / "wayback_discovery_20260630.write.json"
        remaining_path = source_dir / "remaining_blockers_cdx_discovery.json"
        if not full_path.exists():
            raise FileNotFoundError(f"source archive discovery report not found: {full_path}")
        if not remaining_path.exists():
            raise FileNotFoundError(f"source archive blocker recheck report not found: {remaining_path}")
        full_report = json.loads(full_path.read_text(encoding="utf-8"))
        remaining_report = json.loads(remaining_path.read_text(encoding="utf-8"))
        replacement_report = self._read_source_replacement_report(optional=True)
        status_counts = full_report.get("status_counts") or {}
        remaining_counts = remaining_report.get("status_counts") or {}
        unresolved_count = int(remaining_report.get("source_count") or 0)
        payload = {
            "status": "source_archive_blockers_remaining" if unresolved_count else "source_archives_ready",
            "generated_at": remaining_report.get("generated_at"),
            "source_count": full_report.get("source_count", 0),
            "source_log_count": full_report.get("source_log_count", 0),
            "archive_candidate_count": full_report.get("candidate_count", 0),
            "sources_updated": full_report.get("sources_updated", 0),
            "remaining_source_count": unresolved_count,
            "remaining_candidate_count": remaining_report.get("candidate_count", 0),
            "status_counts": status_counts,
            "remaining_status_counts": remaining_counts,
            "rows": remaining_report.get("rows", []),
            "source": "disk_snapshot",
            "report_path": str(remaining_path.relative_to(ROOT)),
            "full_report_path": str(full_path.relative_to(ROOT)),
        }
        if replacement_report:
            payload.update(
                {
                    "replacement_report_path": DEFAULT_REPLACEMENT_REPORT.as_posix(),
                    "replacement_status": replacement_report.get("status"),
                    "replacement_candidate_count": replacement_report.get("candidate_count", 0),
                    "cutoff_valid_replacement_count": replacement_report.get("cutoff_valid_replacement_count", 0),
                    "replacement_remaining_candidate_count": replacement_report.get("remaining_candidate_count", 0),
                    "replacement_archive_proof_required_count": replacement_report.get("archive_proof_required_count", 0),
                    "replacement_content_review_required_count": replacement_report.get("content_review_required_count", 0),
                    "replacement_lookup_failed_count": replacement_report.get("lookup_failed_count", 0),
                    "replacement_blocker_code_counts": replacement_report.get("blocker_code_counts", {}),
                    "replacement_next_action_category_counts": replacement_report.get(
                        "next_action_category_counts",
                        {},
                    ),
                    "replacement_status_counts": replacement_report.get("status_counts", {}),
                    "replacement_event_status_counts": replacement_report.get("event_status_counts", {}),
                    "replacement_rows": replacement_report.get("rows", []),
                }
            )
        return payload

    def _source_candidates_payload(
        self,
        event_id: str,
        knowledge_cutoff: str | None,
        live: bool = False,
    ) -> dict[str, object]:
        report_path = ROOT / "reports" / "research_candidates" / f"{event_id}.json"
        input_path = ROOT / "data" / "research" / event_id / "source_candidates.json"
        if report_path.exists() and not live:
            payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
            payload["source"] = "disk_snapshot"
            payload["report_path"] = str(report_path.relative_to(ROOT))
            payload["input_path"] = str(input_path.relative_to(ROOT)) if input_path.exists() else None
            return payload

        builder = CodexSourceCandidateBuilder()
        if input_path.exists():
            report = builder.build_file(
                event_id,
                input_path,
                knowledge_cutoff=knowledge_cutoff,
            )
            source = "live_candidate_audit"
        else:
            report = builder.build(event_id, knowledge_cutoff=knowledge_cutoff)
            source = "missing_candidate_input"
        payload = report.to_dict()
        payload["source"] = source
        payload["input_path"] = str(input_path.relative_to(ROOT))
        payload["report_path"] = str(report_path.relative_to(ROOT))
        return payload

    def _research_preflight_payload(
        self,
        event_id: str,
        knowledge_cutoff: str | None,
        live: bool = False,
    ) -> dict[str, object]:
        report_path = ROOT / "reports" / "research_preflight" / f"{event_id}.json"
        template_path = ROOT / "data" / "research" / event_id / "research_packet_template.json"
        if report_path.exists() and not live:
            payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
            if "source_candidate_audit" in payload:
                payload["source"] = "disk_snapshot"
                payload["report_path"] = str(report_path.relative_to(ROOT))
                payload["input_path"] = str(template_path.relative_to(ROOT)) if template_path.exists() else None
                return payload

        if not template_path.exists():
            plan = CodexResearchPlanBuilder().build(event_id, knowledge_cutoff=knowledge_cutoff)
            return {
                "event_id": event_id,
                "knowledge_cutoff": knowledge_cutoff or plan.knowledge_cutoff,
                "status": "missing_research_packet_template",
                "source": "missing_template",
                "input_path": str(template_path.relative_to(ROOT)),
                "archive_precheck_can_archive": False,
                "claim_count": 0,
                "valid_claim_count": 0,
                "source_count": 0,
                "blocking_issue_count": 1,
                "warning_count": 0,
                "findings": [
                    {
                        "severity": "error",
                        "code": "missing_research_packet_template",
                        "detail": "Run prepare-research, then fill the research packet before preflight.",
                    }
                ],
                "claims": [],
                "preflight_command": plan.output_contract.get("preflight_command"),
            }

        result = CodexResearchPacketPreflight().preflight_file(
            template_path,
            event_id=event_id,
            knowledge_cutoff=knowledge_cutoff,
            source_candidate_report_path=ROOT / "reports" / "research_candidates" / f"{event_id}.json",
            source_candidates_input_path=ROOT / "data" / "research" / event_id / "source_candidates.json",
        )
        payload = result.to_dict()
        payload["source"] = "live_template_preflight"
        payload["input_path"] = str(template_path.relative_to(ROOT))
        payload["report_path"] = str(report_path.relative_to(ROOT))
        return payload

    def _source_replacements_payload(self) -> dict[str, object]:
        payload = self._read_source_replacement_report(optional=False)
        payload["source"] = "disk_snapshot"
        payload["report_path"] = DEFAULT_REPLACEMENT_REPORT.as_posix()
        return payload

    @staticmethod
    def _read_source_replacement_report(optional: bool) -> dict[str, object]:
        path = ROOT / DEFAULT_REPLACEMENT_REPORT
        if not path.exists():
            if optional:
                return {}
            raise FileNotFoundError(f"source replacement report not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _improvement_plan_payload(self, year: int, as_of: str) -> dict[str, object]:
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        report_path = ROOT / "reports" / "improvement_plan" / f"{stem}.improvement_plan.json"
        if not report_path.exists():
            raise FileNotFoundError(f"improvement plan report not found: {report_path}")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        payload["source"] = "disk_snapshot"
        payload["report_path"] = str(report_path.relative_to(ROOT))
        return payload

    def _chronological_replay_payload(self, year: int, as_of: str) -> dict[str, object]:
        return self._report_payload(
            year,
            as_of,
            report_dir="chronological_replay",
            suffix=".chronological_replay.json",
        )

    def _report_payload(
        self,
        year: int,
        as_of: str,
        report_dir: str,
        suffix: str,
    ) -> dict[str, object]:
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        report_path = ROOT / "reports" / report_dir / f"{stem}{suffix}"
        if not report_path.exists():
            raise FileNotFoundError(f"replay report not found: {report_path}")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        payload["source"] = "disk_snapshot"
        payload["report_path"] = str(report_path.relative_to(ROOT))
        return payload

    @staticmethod
    def _read_jsonl_preview(path: Path, limit: int) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        if not path.exists():
            return rows
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(rows) >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows

    @staticmethod
    def _stem_time(value: str) -> str:
        return stem_time(value)

    @staticmethod
    def _as_of_from_query(
        query: dict[str, list[str]],
        year: int,
        report_dir: str,
        suffix: str = "",
        directories: bool = False,
    ) -> str:
        requested = query.get("as_of", [None])[0]
        if requested and requested != "latest":
            return requested
        return (
            latest_replay_as_of(
                ROOT / "reports" / report_dir,
                year,
                suffix=suffix,
                directories=directories,
            )
            or DEFAULT_REPLAY_AS_OF
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"F1Predict server running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
