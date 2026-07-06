"""Backend API v2 service layer.

The HTTP server delegates to this module, but the code is intentionally free of
web-framework dependencies so tests and CLI tools can call the same backend
workflow directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import parse_dt, utc_now
from f1predict.explainability import PredictionExplainer
from f1predict.impact_trace_sidecar import PredictionImpactTraceSidecarStore
from f1predict.intelligence.codex import CodexEvidenceProvider
from f1predict.pipeline import PredictionPipeline
from f1predict.prediction_anomaly import PredictionAnomalyAuditor
from f1predict.prediction_packet import PredictionPacketBuilder
from f1predict.run_tracking import InformationIntakeStore, MatchedPredictionDiff, PredictionRunRegistry
from f1predict.storage import safe_name
from f1predict.track_features import track_feature_vector


API_VERSION = "v2"


@dataclass(frozen=True)
class ApiResponse:
    payload: dict[str, Any] | list[Any]
    status: int = 200


class BackendApiV2:
    """Implements the backend-only v2 API contract."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
        self.registry = PredictionRunRegistry(self.root / "reports" / "prediction_runs")
        self.intake_store = InformationIntakeStore(
            root=self.root / "data" / "intake",
            evidence_provider=CodexEvidenceProvider(
                evidence_dir=self.root / "data" / "seed" / "evidence",
                packet_root=self.root / "data" / "evidence",
            ),
            research_root=self.root / "data" / "research",
            reports_root=self.root / "reports",
        )
        self.explainer = PredictionExplainer(self.root, registry=self.registry)
        self.impact_trace_store = PredictionImpactTraceSidecarStore(self.root, registry=self.registry)

    def handle_get(self, path: str, query: dict[str, list[str]]) -> ApiResponse | None:
        if not path.startswith("/api/v2/"):
            return None
        route = path.removeprefix("/api/v2")
        if route in {"", "/"}:
            return ApiResponse(self.index())
        if route == "/openapi.json":
            return ApiResponse(self.openapi())
        if route == "/health":
            return ApiResponse(self.health())
        if route == "/verified-facts":
            return ApiResponse(self.verified_facts())
        if route == "/season-state":
            return ApiResponse(self.season_state())
        if route == "/track-features":
            event_id = _first(query, "event_id", "british_gp")
            cutoff = _first(query, "knowledge_cutoff", None)
            return ApiResponse(self.track_features(str(event_id), cutoff))
        if route == "/information-intake":
            event_id = _first(query, "event_id", "british_gp")
            cutoff = _first(query, "knowledge_cutoff", None)
            record = self.intake_store.build(event_id, knowledge_cutoff=cutoff)
            return ApiResponse(record.to_dict())
        if route == "/prediction-runs":
            event_id = _first(query, "event_id", None)
            rows = [record.to_dict() for record in self.registry.list_records(event_id=event_id)]
            return ApiResponse({"run_count": len(rows), "runs": rows})
        if route == "/prediction-runs/latest":
            event_id = _first(query, "event_id", "british_gp")
            cutoff = _first(query, "knowledge_cutoff", None)
            record = self.registry.latest(event_id, knowledge_cutoff=cutoff)
            if record is None:
                return ApiResponse({"error": "prediction_run_not_found", "event_id": event_id}, status=404)
            return ApiResponse(record.to_dict())
        if route == "/prediction-packets/latest":
            event_id = _first(query, "event_id", "british_gp")
            cutoff = _first(query, "knowledge_cutoff", None)
            record = self.registry.latest(event_id, knowledge_cutoff=cutoff)
            if record is None:
                return ApiResponse({"error": "prediction_run_not_found", "event_id": event_id}, status=404)
            payload = self._load_registered_prediction_packet(record)
            if payload is None:
                return ApiResponse(
                    {
                        "error": "prediction_packet_not_found",
                        "event_id": event_id,
                        "run_id": record.run_id,
                    },
                    status=404,
                )
            return ApiResponse(payload)
        if route.startswith("/prediction-runs/") and route.endswith("/packet"):
            run_id = route.removeprefix("/prediction-runs/").removesuffix("/packet").strip("/")
            if not run_id:
                return ApiResponse({"error": "missing_run_id"}, status=400)
            record = self.registry.load(run_id)
            payload = self._load_registered_prediction_packet(record)
            if payload is None:
                return ApiResponse(
                    {"error": "prediction_packet_not_found", "run_id": record.run_id},
                    status=404,
                )
            return ApiResponse(payload)
        if route.startswith("/prediction-runs/") and route.endswith("/impact-traces"):
            run_id = route.removeprefix("/prediction-runs/").removesuffix("/impact-traces").strip("/")
            if not run_id:
                return ApiResponse({"error": "missing_run_id"}, status=400)
            payload = self._prediction_impact_trace_page(query, run_id=run_id)
            if payload is None:
                return ApiResponse({"error": "prediction_impact_trace_sidecar_not_found", "run_id": run_id}, status=404)
            return ApiResponse(payload)
        if route == "/prediction-impact-traces/latest":
            event_id = str(_first(query, "event_id", "british_gp"))
            run_id = _first(query, "run_id", None)
            payload = self._prediction_impact_trace_page(query, event_id=event_id, run_id=run_id)
            if payload is None:
                return ApiResponse(
                    {
                        "error": "prediction_impact_trace_sidecar_not_found",
                        "event_id": event_id,
                        "run_id": run_id,
                    },
                    status=404,
                )
            return ApiResponse(payload)
        if route == "/prediction-impact-traces/readiness":
            event_id = str(_first(query, "event_id", "british_gp"))
            run_id = _first(query, "run_id", None)
            return ApiResponse(self.impact_trace_store.readiness(event_id=event_id, run_id=run_id))
        if route.startswith("/prediction-runs/"):
            run_id = route.removeprefix("/prediction-runs/").strip("/")
            if not run_id:
                return ApiResponse({"error": "missing_run_id"}, status=400)
            return ApiResponse(self.registry.load(run_id).to_dict())
        if route == "/prediction-diffs":
            event_id = _first(query, "event_id", None)
            return ApiResponse(self._list_prediction_diffs(event_id=event_id))
        if route.startswith("/prediction-diffs/"):
            diff_id = route.removeprefix("/prediction-diffs/").strip("/")
            payload = self._load_prediction_diff(diff_id)
            if payload is None:
                return ApiResponse({"error": "prediction_diff_not_found", "diff_id": diff_id}, status=404)
            return ApiResponse(payload)
        if route == "/prediction-explanations":
            question = _first(query, "question", None)
            if not question:
                return ApiResponse({"error": "question_required"}, status=400)
            event_id = str(_first(query, "event_id", "british_gp"))
            run_id = _first(query, "run_id", None)
            cutoff = _first(query, "knowledge_cutoff", None)
            language = str(_first(query, "language", "zh"))
            max_evidence = int(_first(query, "max_evidence", "10") or "10")
            write = _bool_query(query, "write", default=False)
            payload = self._prediction_explanation_payload(
                question=question,
                event_id=event_id,
                run_id=run_id,
                knowledge_cutoff=cutoff,
                language=language,
                max_evidence=max_evidence,
                write=write,
                output_dir=self.root / "reports" / "prediction_explanations",
            )
            return ApiResponse(payload, status=201 if write else 200)
        return ApiResponse({"error": "unknown_api_v2_route", "path": path}, status=404)

    def handle_post(self, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> ApiResponse | None:
        if not path.startswith("/api/v2/"):
            return None
        route = path.removeprefix("/api/v2")
        if route == "/information-intake":
            event_id = str(body.get("event_id") or _first(query, "event_id", "british_gp"))
            cutoff = body.get("knowledge_cutoff") or _first(query, "knowledge_cutoff", None)
            record, artifact_path = self.intake_store.build_and_write(event_id, knowledge_cutoff=cutoff)
            payload = record.to_dict()
            payload["path"] = str(_relative_to_root(artifact_path, self.root))
            return ApiResponse(payload, status=201)
        if route == "/prediction-runs":
            payload = self.create_prediction_run(body, query=query)
            return ApiResponse(payload, status=201)
        if route == "/prediction-diffs":
            base_run_id = str(body.get("base_run_id") or body.get("base_run") or "")
            candidate_run_id = str(body.get("candidate_run_id") or body.get("candidate_run") or "")
            if not base_run_id or not candidate_run_id:
                return ApiResponse({"error": "base_run_id_and_candidate_run_id_required"}, status=400)
            write = bool(body.get("write", True))
            output_dir = body.get("output_dir") or self.root / "reports" / "prediction_diffs"
            differ = MatchedPredictionDiff(self.registry, output_dir=Path(output_dir))
            diff = differ.build(base_run_id, candidate_run_id)
            result = diff.to_dict()
            if write:
                paths = differ.write(diff)
                result["paths"] = {key: str(_relative_to_root(path, self.root)) for key, path in paths.items()}
            return ApiResponse(result, status=201)
        if route == "/prediction-explanations":
            question = str(body.get("question") or _first(query, "question", "") or "")
            if not question:
                return ApiResponse({"error": "question_required"}, status=400)
            event_id = str(body.get("event_id") or _first(query, "event_id", "british_gp"))
            run_id = body.get("run_id") or _first(query, "run_id", None)
            cutoff = body.get("knowledge_cutoff") or _first(query, "knowledge_cutoff", None)
            language = str(body.get("language") or _first(query, "language", "zh"))
            max_evidence = int(body.get("max_evidence") or _first(query, "max_evidence", "10") or "10")
            write = bool(body.get("write", False))
            output_dir = Path(body.get("output_dir") or self.root / "reports" / "prediction_explanations")
            payload = self._prediction_explanation_payload(
                question=question,
                event_id=event_id,
                run_id=str(run_id) if run_id else None,
                knowledge_cutoff=str(cutoff) if cutoff else None,
                language=language,
                max_evidence=max_evidence,
                write=write,
                output_dir=output_dir,
            )
            return ApiResponse(payload, status=201 if write else 200)
        if route == "/prediction-impact-traces":
            payload = self._build_prediction_impact_trace_sidecar(body, query)
            return ApiResponse(payload, status=201)
        return ApiResponse({"error": "unknown_api_v2_route", "path": path}, status=404)

    def create_prediction_run(
        self,
        body: dict[str, Any],
        query: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        query = query or {}
        event_id = str(body.get("event_id") or _first(query, "event_id", "british_gp"))
        cutoff = body.get("knowledge_cutoff") or _first(query, "knowledge_cutoff", None)
        iterations = int(body.get("iterations") or _first(query, "iterations", "1200"))
        isolated_impact_limit = int(body.get("isolated_impact_limit") or _first(query, "isolated_impact_limit", "12"))
        isolated_source_group_limit = int(
            body.get("isolated_source_group_limit")
            or _first(query, "isolated_source_group_limit", "0")
        )
        output_dir = Path(body.get("output_dir") or self._default_prediction_packet_output_dir(event_id))
        register = bool(body.get("register", True))
        write_intake = bool(body.get("write_information_intake", True))
        compare_to_latest = bool(body.get("compare_to_latest", True))
        base_run_id = body.get("base_run_id")

        base_record = None
        if base_run_id:
            base_record = self.registry.load(str(base_run_id))
        elif compare_to_latest:
            base_record = self.registry.latest(event_id, knowledge_cutoff=cutoff)

        intake_record = None
        intake_path = None
        if write_intake:
            intake_record, intake_path = self.intake_store.build_and_write(event_id, knowledge_cutoff=cutoff)

        builder = PredictionPacketBuilder(
            PredictionPipeline(
                iterations=iterations,
                isolated_impact_limit=isolated_impact_limit,
                isolated_source_group_limit=isolated_source_group_limit,
            ),
            reports_root=self.root / "reports",
        )
        packet_paths = builder.write(
            event_id,
            knowledge_cutoff=cutoff,
            iterations=iterations,
            output_dir=output_dir,
        )
        result: dict[str, Any] = {
            "event_id": event_id,
            "knowledge_cutoff": cutoff,
            "iterations": iterations,
            "isolated_impact_limit": isolated_impact_limit,
            "isolated_source_group_limit": isolated_source_group_limit,
            "prediction_packet_paths": {
                key: str(_relative_to_root(path, self.root))
                for key, path in packet_paths.items()
            },
            "information_intake": intake_record.to_dict() if intake_record else None,
            "information_intake_path": str(_relative_to_root(intake_path, self.root)) if intake_path else None,
            "registered": False,
            "prediction_run": None,
            "comparison": None,
        }
        if not register:
            return result

        record = self.registry.register_packet(packet_paths["json"], information_intake_path=intake_path)
        result["registered"] = True
        result["prediction_run"] = record.to_dict()
        if base_record is not None and base_record.run_id != record.run_id:
            differ = MatchedPredictionDiff(self.registry, output_dir=self.root / "reports" / "prediction_diffs")
            diff = differ.build(base_record.run_id, record.run_id)
            diff_paths = differ.write(diff)
            result["comparison"] = {
                "base_run_id": base_record.run_id,
                "candidate_run_id": record.run_id,
                "diff": diff.to_dict(),
                "paths": {
                    key: str(_relative_to_root(path, self.root))
                    for key, path in diff_paths.items()
                },
            }
        return result

    def _default_prediction_packet_output_dir(self, event_id: str) -> Path:
        timestamp = safe_name(utc_now().replace(microsecond=0).isoformat())
        return self.root / "reports" / "prediction_packets_v2" / safe_name(event_id) / timestamp

    def _prediction_explanation_payload(
        self,
        question: str,
        event_id: str,
        run_id: str | None,
        knowledge_cutoff: str | None,
        language: str,
        max_evidence: int,
        write: bool,
        output_dir: Path,
    ) -> dict[str, Any]:
        if write:
            explanation, paths = self.explainer.answer_and_write(
                question=question,
                event_id=event_id,
                run_id=run_id,
                knowledge_cutoff=knowledge_cutoff,
                language=language,
                max_evidence=max_evidence,
                output_dir=output_dir,
            )
            payload = explanation.to_dict()
            payload["paths"] = {key: str(_relative_to_root(path, self.root)) for key, path in paths.items()}
            return payload
        return self.explainer.answer(
            question=question,
            event_id=event_id,
            run_id=run_id,
            knowledge_cutoff=knowledge_cutoff,
            language=language,
            max_evidence=max_evidence,
        ).to_dict()

    def index(self) -> dict[str, Any]:
        return {
            "api": "f1predict_backend",
            "version": API_VERSION,
            "openapi": "/api/v2/openapi.json",
            "health": "/api/v2/health",
            "primary_workflow": [
                "POST /api/v2/information-intake",
                "POST /api/v2/prediction-runs",
                "POST /api/v2/prediction-diffs",
                "POST /api/v2/prediction-explanations",
            ],
        }

    def health(self) -> dict[str, Any]:
        season = PredictionPipeline(iterations=1).data_source.load()
        latest_british = self.registry.latest("british_gp")
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "backend_only": True,
            "season": season.season,
            "team_count": len(season.teams),
            "driver_count": len(season.drivers),
            "event_count": len(season.events),
            "latest_british_gp_run_id": latest_british.run_id if latest_british else None,
            "expectation_doc": "docs/user_project_expectations_cn.md",
            "api_design_doc": "docs/backend_api_v2_cn.md",
            "verified_facts_doc": "docs/verified_facts_2026_cn.md",
        }

    def verified_facts(self) -> dict[str, Any]:
        return {
            "facts": [
                {
                    "fact_id": "2026_f1_roster_11_teams_22_drivers",
                    "status": "verified",
                    "verified_on": "2026-07-05",
                    "source": "Formula 1 official teams page",
                    "source_url": "https://www.formula1.com/en/teams",
                    "claim": "2026 season lists 11 teams and 22 drivers, including Cadillac with Sergio Perez and Valtteri Bottas.",
                    "local_artifact": "docs/verified_facts_2026_cn.md",
                }
            ]
        }

    def season_state(self) -> dict[str, Any]:
        season = PredictionPipeline(iterations=1).data_source.load()
        teams = [
            {
                "team_id": team.team_id,
                "name": team.name,
                "drivers": [
                    {"driver_id": driver.driver_id, "name": driver.name}
                    for driver in season.drivers.values()
                    if driver.team_id == team.team_id
                ],
            }
            for team in season.teams.values()
        ]
        events = [
            {
                "event_id": event.event_id,
                "name": event.name,
                "round_number": event.round_number,
                "date": event.date,
                "completed": event.completed,
                "track_type": event.track_type,
            }
            for event in season.events
        ]
        return {
            "season": season.season,
            "team_count": len(season.teams),
            "driver_count": len(season.drivers),
            "event_count": len(season.events),
            "teams": teams,
            "events": events,
            "verified_fact_refs": ["2026_f1_roster_11_teams_22_drivers"],
        }

    def track_features(self, event_id: str, knowledge_cutoff: str | None = None) -> dict[str, Any]:
        pipeline = PredictionPipeline(iterations=1)
        season = pipeline.data_source.load()
        event = next((item for item in season.events if item.event_id == event_id), None)
        if event is None:
            return {"error": "event_not_found", "event_id": event_id}
        cutoff_dt = pipeline._normalize_cutoff(parse_dt(knowledge_cutoff)) if knowledge_cutoff else None
        event = pipeline._event_with_cutoff_weather_forecast(event, cutoff_dt)
        event = pipeline._event_with_track_feature_vector(event)
        return track_feature_vector(event).to_dict()

    def openapi(self) -> dict[str, Any]:
        return {
            "openapi": "3.0.3",
            "info": {
                "title": "F1Predict Backend API",
                "version": API_VERSION,
                "description": "Backend-only API for information intake, prediction runs, and matched prediction diffs.",
            },
            "paths": {
                "/api/v2/health": {"get": {"summary": "Backend health and roster counts"}},
                "/api/v2/verified-facts": {"get": {"summary": "Verified real-world facts used by the backend"}},
                "/api/v2/season-state": {"get": {"summary": "Current local season roster and event state"}},
                "/api/v2/track-features": {"get": {"summary": "Source-backed track/environment feature vector"}},
                "/api/v2/information-intake": {
                    "get": {"summary": "Preview structured information available for an event"},
                    "post": {"summary": "Build and persist an information intake artifact"},
                },
                "/api/v2/prediction-runs": {
                    "get": {"summary": "List registered prediction runs"},
                    "post": {"summary": "Build a prediction packet, register a run, and optionally compare to latest"},
                },
                "/api/v2/prediction-runs/latest": {"get": {"summary": "Fetch latest registered run for an event"}},
                "/api/v2/prediction-runs/{run_id}": {"get": {"summary": "Fetch one registered prediction run"}},
                "/api/v2/prediction-packets/latest": {
                    "get": {"summary": "Fetch the prediction packet JSON for the latest registered run"},
                },
                "/api/v2/prediction-runs/{run_id}/packet": {
                    "get": {"summary": "Fetch the prediction packet JSON for a registered run"},
                },
                "/api/v2/prediction-diffs": {
                    "get": {"summary": "List stored prediction diff artifacts"},
                    "post": {"summary": "Build a matched diff between two registered runs"},
                },
                "/api/v2/prediction-diffs/{diff_id}": {"get": {"summary": "Fetch one stored prediction diff"}},
                "/api/v2/prediction-explanations": {
                    "get": {"summary": "Answer a prediction-result question from a registered run"},
                    "post": {"summary": "Answer and optionally persist a prediction explanation artifact"},
                },
                "/api/v2/prediction-impact-traces/latest": {
                    "get": {"summary": "Fetch a cached, paginated full prediction-impact trace sidecar"},
                },
                "/api/v2/prediction-impact-traces/readiness": {
                    "get": {"summary": "Check whether the latest impact-trace sidecar is formal-ready"},
                },
                "/api/v2/prediction-runs/{run_id}/impact-traces": {
                    "get": {"summary": "Fetch cached impact traces for one registered run"},
                },
                "/api/v2/prediction-impact-traces": {
                    "post": {"summary": "Build and optionally persist a full prediction-impact trace sidecar"},
                },
            },
        }

    def _prediction_impact_trace_page(
        self,
        query: dict[str, list[str]],
        *,
        event_id: str = "british_gp",
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self.impact_trace_store.latest_page(
            event_id=event_id,
            run_id=run_id,
            limit=int(_first(query, "limit", "40") or "40"),
            offset=int(_first(query, "offset", "0") or "0"),
            trace_type=_first(query, "trace_type", None),
            impact_status=_first(query, "impact_status", None),
            claim_id=_first(query, "claim_id", None),
        )

    def _build_prediction_impact_trace_sidecar(
        self,
        body: dict[str, Any],
        query: dict[str, list[str]],
    ) -> dict[str, Any]:
        event_id = str(body.get("event_id") or _first(query, "event_id", "british_gp"))
        run_id = body.get("run_id") or _first(query, "run_id", None)
        cutoff = body.get("knowledge_cutoff") or _first(query, "knowledge_cutoff", None)
        iterations_value = body.get("iterations") or _first(query, "iterations", None)
        iterations = int(iterations_value) if iterations_value is not None else None
        isolated_impact_limit = int(body.get("isolated_impact_limit") or _first(query, "isolated_impact_limit", "-1"))
        isolated_impact_offset = int(body.get("isolated_impact_offset") or _first(query, "isolated_impact_offset", "0"))
        isolated_source_group_limit = int(
            body.get("isolated_source_group_limit") or _first(query, "isolated_source_group_limit", "0")
        )
        write = bool(body.get("write", True))
        include_traces = bool(body.get("include_traces", False))
        page_limit = int(body.get("limit") or _first(query, "limit", "40") or "40")
        page_offset = int(body.get("offset") or _first(query, "offset", "0") or "0")
        sidecar = self.impact_trace_store.build(
            event_id=event_id,
            run_id=str(run_id) if run_id else None,
            knowledge_cutoff=str(cutoff) if cutoff else None,
            iterations=iterations,
            isolated_impact_limit=isolated_impact_limit,
            isolated_impact_offset=isolated_impact_offset,
            isolated_source_group_limit=isolated_source_group_limit,
        )
        path = None
        if write:
            path = self.impact_trace_store.write(sidecar)
        if include_traces:
            payload = sidecar
        else:
            payload = self.impact_trace_store.latest_page(
                event_id=event_id,
                run_id=sidecar["source_run"]["run_id"],
                limit=page_limit,
                offset=page_offset,
            ) if write else None
            if payload is None:
                from f1predict.impact_trace_sidecar import page_sidecar

                payload = page_sidecar(sidecar, limit=page_limit, offset=page_offset)
        if path is not None:
            payload["path"] = str(_relative_to_root(path, self.root))
        return payload

    def _list_prediction_diffs(self, event_id: str | None = None) -> dict[str, Any]:
        root = self.root / "reports" / "prediction_diffs"
        rows = []
        if root.exists():
            for path in sorted(root.rglob("*.prediction_diff.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if event_id and payload.get("event_id") != event_id:
                    continue
                rows.append(
                    {
                        "diff_id": payload.get("diff_id"),
                        "event_id": payload.get("event_id"),
                        "generated_at": payload.get("generated_at"),
                        "base_run_id": payload.get("base_run_id"),
                        "candidate_run_id": payload.get("candidate_run_id"),
                        "probability_changed": payload.get("probability_changed"),
                        "evidence_changed": payload.get("evidence_changed"),
                        "summary": payload.get("summary", {}),
                        "path": str(_relative_to_root(path, self.root)),
                    }
                )
        return {"diff_count": len(rows), "diffs": rows}

    def _load_registered_prediction_packet(self, record) -> dict[str, Any] | None:
        if not record.prediction_packet_path:
            return None
        packet_path = Path(record.prediction_packet_path)
        if not packet_path.is_absolute():
            packet_path = self.root / packet_path
        if not packet_path.exists():
            return None
        payload = json.loads(packet_path.read_text(encoding="utf-8"))
        payload["cache_context"] = {
            "source": "registered_prediction_packet",
            "run_id": record.run_id,
            "created_at": record.created_at,
            "packet_path": str(_relative_to_root(packet_path, self.root)),
            "packet_payload_sha256": record.packet_payload_sha256,
            "input_fingerprint": record.input_fingerprint,
            "probability_fingerprint": record.probability_fingerprint,
            "knowledge_cutoff": record.knowledge_cutoff,
        }
        self._refresh_prediction_anomaly_audit(payload, record)
        return payload

    def _refresh_prediction_anomaly_audit(self, payload: dict[str, Any], record) -> None:
        prediction = payload.get("prediction")
        if not isinstance(prediction, dict):
            return
        sidecar = None
        try:
            sidecar = self.impact_trace_store.latest(event_id=record.event_id, run_id=record.run_id)
        except (OSError, ValueError, json.JSONDecodeError):
            sidecar = None
        season = PredictionPipeline(iterations=1).data_source.load()
        payload["prediction_anomaly_audit"] = PredictionAnomalyAuditor().build(
            season,
            prediction,
            impact_trace_sidecar=sidecar,
        )
        cache_context = payload.setdefault("cache_context", {})
        if isinstance(cache_context, dict):
            cache_context["prediction_anomaly_audit_source"] = "api_runtime_recomputed"
            cache_context["prediction_anomaly_audit_sidecar_id"] = (
                sidecar.get("sidecar_id") if isinstance(sidecar, dict) else None
            )
            cache_context["prediction_anomaly_audit_sidecar_comparison_status"] = (
                _as_dict(sidecar.get("trace_generation")).get("comparison_status")
                if isinstance(sidecar, dict)
                else None
            )

    def _load_prediction_diff(self, diff_id: str) -> dict[str, Any] | None:
        root = self.root / "reports" / "prediction_diffs"
        if not root.exists():
            return None
        target_name = f"{safe_name(diff_id)}.prediction_diff.json"
        for path in root.rglob("*.prediction_diff.json"):
            if path.name == target_name:
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["path"] = str(_relative_to_root(path, self.root))
                return payload
        return None


def _first(query: dict[str, list[str]], key: str, default: str | None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[0]


def _bool_query(query: dict[str, list[str]], key: str, default: bool = False) -> bool:
    value = _first(query, key, None)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _relative_to_root(path: Path | str | None, root: Path) -> Path | str | None:
    if path is None:
        return None
    path = Path(path)
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path
