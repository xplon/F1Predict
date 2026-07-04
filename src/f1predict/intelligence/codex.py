"""Normalized Codex evidence provider.

Codex is expected to use tools outside this package to research live sources,
then write JSONL evidence packets that satisfy the schema in `domain.py`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from f1predict.domain import EvidenceClaim, utc_now
from f1predict.storage import safe_name


DEFAULT_EVIDENCE_DIR = Path("data/seed/evidence")
DEFAULT_PACKET_ROOT = Path("data/evidence")


class EvidenceValidationError(ValueError):
    """Raised when a Codex evidence packet is malformed."""


class EvidencePacketStore:
    """Append-only storage for Codex-generated evidence packets."""

    def __init__(self, root: Path | str = DEFAULT_PACKET_ROOT) -> None:
        self.root = Path(root)

    def write_event_packet(
        self,
        event_id: str,
        claims: list[EvidenceClaim],
        source_log_path: Path | str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Path:
        if not claims:
            raise EvidenceValidationError(f"No claims to archive for event_id={event_id}")
        wrong_event = [claim.claim_id for claim in claims if claim.event_id != event_id]
        if wrong_event:
            raise EvidenceValidationError(
                f"Cannot archive claims for a different event_id: {', '.join(wrong_event)}"
            )
        captured_at = utc_now().replace(microsecond=0).isoformat()
        date_part = captured_at[:10]
        directory = self.root / safe_name(event_id) / "packets" / date_part
        directory.mkdir(parents=True, exist_ok=True)
        stem = safe_name(f"{event_id}_{captured_at}")
        data_path = directory / f"{stem}.jsonl"
        meta_path = directory / f"{stem}.meta.json"
        lines = [json.dumps(claim.__dict__, ensure_ascii=False, sort_keys=True) for claim in claims]
        data_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        meta = {
            "source": "codex_evidence",
            "event_id": event_id,
            "captured_at": captured_at,
            "claim_count": len(claims),
            "data_path": str(data_path),
            "source_log_path": str(source_log_path) if source_log_path else None,
            "params": params or {},
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return data_path

    def event_packet_paths(self, event_id: str) -> list[Path]:
        directory = self.root / safe_name(event_id)
        if not directory.exists():
            return []
        files = [path for path in directory.rglob("*.jsonl") if not path.name.endswith(".meta.json")]
        return sorted(files, key=lambda path: (path.stat().st_mtime, str(path)))


class CodexEvidenceProvider:
    """Reads and validates Codex-generated structured evidence."""

    def __init__(
        self,
        evidence_dir: Path | str = DEFAULT_EVIDENCE_DIR,
        packet_root: Path | str = DEFAULT_PACKET_ROOT,
    ) -> None:
        self.evidence_dir = Path(evidence_dir)
        self.packet_store = EvidencePacketStore(packet_root)

    def load_event_evidence(
        self,
        event_id: str,
        knowledge_cutoff: datetime | None = None,
    ) -> list[EvidenceClaim]:
        claims_by_id: dict[str, EvidenceClaim] = {}
        for path in self._event_paths(event_id):
            for claim in self.load_file(path):
                if claim.event_id == event_id and claim.is_available(knowledge_cutoff):
                    claims_by_id[claim.claim_id] = claim
        return list(claims_by_id.values())

    def load_file(self, path: Path | str) -> list[EvidenceClaim]:
        file_path = Path(path)
        if not file_path.exists():
            raise EvidenceValidationError(f"{file_path}: file does not exist")
        claims: list[EvidenceClaim] = []
        for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                claim = EvidenceClaim.from_dict(json.loads(stripped))
            except Exception as exc:  # noqa: BLE001 - include line context.
                raise EvidenceValidationError(f"{file_path}:{line_no}: {exc}") from exc
            self._validate_claim(claim, file_path, line_no)
            claims.append(claim)
        return claims

    def validate_event_file(self, event_id: str, path: Path | str) -> list[EvidenceClaim]:
        claims = self.load_file(path)
        wrong_event = [claim.claim_id for claim in claims if claim.event_id != event_id]
        if wrong_event:
            raise EvidenceValidationError(
                f"{path}: claims for a different event_id: {', '.join(wrong_event)}"
            )
        return claims

    def _event_paths(self, event_id: str) -> list[Path]:
        paths = []
        legacy = self.evidence_dir / f"{event_id}.jsonl"
        if legacy.exists():
            paths.append(legacy)
        paths.extend(self.packet_store.event_packet_paths(event_id))
        return paths

    @staticmethod
    def _validate_claim(claim: EvidenceClaim, path: Path, line_no: int) -> None:
        if not (0.0 <= claim.confidence <= 1.0):
            raise EvidenceValidationError(f"{path}:{line_no}: confidence must be 0..1")
        if not (0.0 <= claim.uncertainty <= 1.0):
            raise EvidenceValidationError(f"{path}:{line_no}: uncertainty must be 0..1")
        if claim.magnitude < 0.0:
            raise EvidenceValidationError(f"{path}:{line_no}: magnitude must be non-negative")
        if not claim.source_url:
            raise EvidenceValidationError(f"{path}:{line_no}: source_url is required")
