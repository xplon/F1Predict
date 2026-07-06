"""Guard against entity-specific prediction patches.

This is a lightweight contract test for the project principle that user
examples are bug reports, not labels. Prediction-update code may use sourced
features, standings, timing data, and archived source-backed evidence, but it
must not contain driver/team-specific branches that force a desired ranking.
Seed records may exist as plumbing fixtures, but they must be flagged as
diagnostic and must not be treated as production evidence.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.domain import EvidenceClaim  # noqa: E402
from f1predict.intelligence.evidence_quality import EvidenceQualityScorer  # noqa: E402
from f1predict.run_tracking import PredictionRunRegistry  # noqa: E402


PREDICTION_UPDATE_FILES = (
    ROOT / "src" / "f1predict" / "belief_state.py",
    ROOT / "src" / "f1predict" / "models" / "pace.py",
    ROOT / "src" / "f1predict" / "pipeline.py",
    ROOT / "src" / "f1predict" / "models" / "simulator.py",
    ROOT / "src" / "f1predict" / "prediction_anomaly.py",
)

ENTITY_TOKENS = (
    "aston_martin",
    "cadillac",
    "ferrari",
    "mercedes",
    "red_bull",
    "racing_bulls",
    "audi",
    "mclaren",
    "williams",
    "sauber",
    "haas",
    "alpine",
    "leclerc",
    "hamilton",
    "alonso",
    "russell",
    "verstappen",
    "hadjar",
    "antonelli",
    "norris",
    "piastri",
)


def _packet(*, generated_at: str, update_fingerprint: str, win: float, expected_points: float) -> dict:
    return {
        "event_id": "contract_gp",
        "event_name": "Contract GP",
        "generated_at": generated_at,
        "knowledge_cutoff": "2026-07-01T00:00:00+00:00",
        "iterations": 1200,
        "status": "diagnostic_only",
        "formal_edge_ready": False,
        "blocker_codes": ["probability_calibration_diagnostic_only"],
        "warning_codes": [],
        "event_input_audit": {"risk_codes": []},
        "market_context": {"usable_snapshot_count": 1, "after_cutoff_snapshot_count": 0},
        "model_context": {"simulator_config": {"config_id": "contract"}},
        "codex_context": {"evidence_count": 1, "weak_evidence_quality_count": 0, "review_required_count": 0},
        "probability_summary": {
            "top_win_probabilities": [
                {
                    "driver_id": "driver_a",
                    "win": win,
                    "podium": 0.5,
                    "expected_points": expected_points,
                    "average_finish": 5.0,
                }
            ]
        },
        "top_market_edges": [],
        "prediction": {
            "event": {"event_id": "contract_gp", "name": "Contract GP"},
            "evidence": [
                {
                    "claim_id": "contract-source-001",
                    "source": "contract source",
                    "source_url": "https://example.com/contract-source",
                    "event_id": "contract_gp",
                    "target_type": "team",
                    "target_id": "team_a",
                    "claim_type": "race_pace",
                    "metric": "race_pace",
                    "direction": "positive",
                    "magnitude": 0.02,
                    "confidence": 0.7,
                    "uncertainty": 0.2,
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "observed_at": "2026-06-30T00:00:00+00:00",
                    "evidence_text": "Contract source-backed evidence.",
                    "reasoning": "Used only for registration gate smoke testing.",
                    "review_required": False,
                }
            ],
            "feature_adjustments": [
                {
                    "feature_id": "contract-feature-001",
                    "source": "contract structured timing source",
                    "observed_at": "2026-06-30T00:00:00+00:00",
                    "target_type": "driver",
                    "target_id": "driver_a",
                    "metric": "race_pace",
                    "value": 0.02,
                    "explanation": "First structured feature row from the same raw source.",
                },
                {
                    "feature_id": "contract-feature-002",
                    "source": "contract structured timing source",
                    "observed_at": "2026-06-30T00:00:00+00:00",
                    "target_type": "driver",
                    "target_id": "driver_a",
                    "metric": "reliability",
                    "value": 0.01,
                    "explanation": "Second structured feature row from the same raw source.",
                },
            ],
            "belief_state": {
                "state_id": f"contract_state_{update_fingerprint}",
                "update_fingerprint": update_fingerprint,
            },
            "state_update_ledger": [
                {
                    "claim_id": "contract-source-001",
                    "source_id": "contract-source",
                    "target_type": "team",
                    "target_id": "team_a",
                    "factor": "race_pace",
                    "direction": "positive",
                    "magnitude_bucket": "small",
                }
            ],
            "race_probabilities": [
                {
                    "driver_id": "driver_a",
                    "win": win,
                    "podium": 0.5,
                    "points": 0.9,
                    "expected_points": expected_points,
                    "average_finish": 5.0,
                }
            ],
            "market_edges": [],
            "prediction_impact_trace": [],
        },
    }


def _write_packet(path: Path, packet: dict) -> None:
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")


def _assert_registration_gate_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        registry = PredictionRunRegistry(root / "prediction_runs")
        base = _packet(generated_at="2026-07-01T00:00:00+00:00", update_fingerprint="update-a", win=0.2, expected_points=6.0)
        base_path = root / "base.prediction_packet.json"
        _write_packet(base_path, base)
        base_record = registry.register_packet(base_path)

        model_only = deepcopy(base)
        model_only["generated_at"] = "2026-07-01T01:00:00+00:00"
        model_only["probability_summary"]["top_win_probabilities"][0]["win"] = 0.5
        model_only["probability_summary"]["top_win_probabilities"][0]["expected_points"] = 10.0
        model_only["prediction"]["race_probabilities"][0]["win"] = 0.5
        model_only["prediction"]["race_probabilities"][0]["expected_points"] = 10.0
        blocked = registry.assess_registration_gate(model_only, base_record=base_record)
        if blocked.allow_registration or "non_source_driven_prediction_change" not in blocked.blocker_codes:
            raise AssertionError("Model-only race prediction changes must be blocked from latest registration")

        source_state = deepcopy(model_only)
        source_state["prediction"]["belief_state"]["state_id"] = "contract_state_update-b"
        source_state["prediction"]["belief_state"]["update_fingerprint"] = "update-b"
        state_only_blocked = registry.assess_registration_gate(source_state, base_record=base_record)
        if (
            state_only_blocked.allow_registration
            or "state_mapping_revision_proof_required" not in state_only_blocked.blocker_codes
        ):
            raise AssertionError("State-mapping changes without new source identity must require model-revision proof")

        feature_multiplicity_change = deepcopy(base)
        feature_multiplicity_change["generated_at"] = "2026-07-01T01:30:00+00:00"
        feature_multiplicity_change["probability_summary"]["top_win_probabilities"][0]["win"] = 0.42
        feature_multiplicity_change["probability_summary"]["top_win_probabilities"][0]["expected_points"] = 9.0
        feature_multiplicity_change["prediction"]["race_probabilities"][0]["win"] = 0.42
        feature_multiplicity_change["prediction"]["race_probabilities"][0]["expected_points"] = 9.0
        feature_multiplicity_change["prediction"]["belief_state"]["state_id"] = "contract_state_update-c"
        feature_multiplicity_change["prediction"]["belief_state"]["update_fingerprint"] = "update-c"
        feature_multiplicity_change["prediction"]["feature_adjustments"] = feature_multiplicity_change["prediction"][
            "feature_adjustments"
        ][:1]
        multiplicity_blocked = registry.assess_registration_gate(feature_multiplicity_change, base_record=base_record)
        if (
            multiplicity_blocked.allow_registration
            or multiplicity_blocked.source_identity_changed
            or "state_mapping_revision_proof_required" not in multiplicity_blocked.blocker_codes
        ):
            raise AssertionError(
                "Changing feature-row multiplicity from the same raw source must require model-revision proof"
            )

        new_source_state = deepcopy(source_state)
        new_source_state["prediction"]["evidence"][0]["claim_id"] = "contract-source-002"
        new_source_state["prediction"]["evidence"][0]["source_url"] = "https://example.com/contract-source-2"
        new_source_state["prediction"]["evidence"][0]["observed_at"] = "2026-07-01T00:30:00+00:00"
        allowed = registry.assess_registration_gate(new_source_state, base_record=base_record)
        if not allowed.allow_registration or allowed.status != "source_identity_driven_prediction_change":
            raise AssertionError("New source identity should remain registrable as source-driven")

        proof = root / "model_revision_proof.md"
        proof.write_text("diagnostic replay proof placeholder", encoding="utf-8")
        proof_allowed = registry.assess_registration_gate(
            source_state,
            base_record=base_record,
            allow_model_revision_registration=True,
            model_revision_proof_path=proof,
        )
        if not proof_allowed.allow_registration or proof_allowed.status != "model_revision_proof_allowed":
            raise AssertionError("Explicit model-revision proof should allow a diagnostic model-revision registration")


def _assert_user_feedback_cannot_update_predictions() -> None:
    claim = EvidenceClaim(
        claim_id="contract-user-feedback-001",
        event_id="contract_gp",
        source="User feedback from project chat",
        source_url="user-feedback://project-chat/leclerc-hamilton-example",
        published_at="2026-06-30T00:00:00+00:00",
        observed_at="2026-06-30T00:00:00+00:00",
        target_type="driver",
        target_id="driver_a",
        claim_type="race_pace",
        metric="race_pace",
        direction="positive",
        magnitude=0.10,
        confidence=0.99,
        uncertainty=0.01,
        evidence_text="A user says the current prediction looks wrong.",
        reasoning="This must trigger source/reasoning audit only, not a model update.",
        review_required=True,
    )
    [quality] = EvidenceQualityScorer(research_root=Path("__missing_research_root__")).score_event(
        "contract_gp",
        [claim],
        [],
    )
    if "user_feedback_source" not in quality.risk_flags:
        raise AssertionError("User feedback claims must be explicitly flagged as non-evidence")
    if quality.model_input_weight != 0.0:
        raise AssertionError("User feedback must have zero model input weight")


def main() -> None:
    violations: list[str] = []
    for path in PREDICTION_UPDATE_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for token in ENTITY_TOKENS:
            pattern = rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])"
            if re.search(pattern, text):
                violations.append(f"{path.relative_to(ROOT)} contains entity token {token!r}")
    if violations:
        details = "\n".join(f"- {item}" for item in violations)
        raise AssertionError(
            "Prediction-update code must be source-driven, not entity-specific.\n"
            "Move entity facts into sourced data/evidence, or justify and narrow the scanner.\n"
            f"{details}"
        )
    _assert_registration_gate_contract()
    _assert_user_feedback_cannot_update_predictions()
    print("source-driven contract ok")


if __name__ == "__main__":
    main()
