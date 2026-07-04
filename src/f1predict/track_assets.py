"""Local verified visual track-map assets for frontend display."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TRACK_ASSET_MANIFEST = Path("data/raw/circuit_images/2026_f1_official_track_icons/manifest.json")


@dataclass(frozen=True)
class TrackMapAsset:
    event_id: str
    event_name: str
    source: str
    source_url: str
    web_path: str
    raw_path: str
    captured_at: str | None
    circuit_key: str | None = None
    circuit_short_name: str | None = None
    geometry_overlay: dict[str, Any] | None = None

    def provenance(self) -> dict[str, Any]:
        payload = {
            "source": self.source,
            "source_url": self.source_url,
            "web_path": self.web_path,
            "raw_path": self.raw_path,
            "captured_at": self.captured_at,
            "circuit_key": self.circuit_key,
            "circuit_short_name": self.circuit_short_name,
            "quality": "verified_visual",
            "visual_verified": True,
        }
        if self.geometry_overlay:
            payload["geometry_overlay"] = self.geometry_overlay
        return payload


@dataclass(frozen=True)
class TrackAssetAuditRow:
    event_id: str
    event_name: str
    source: str
    source_url: str
    web_path: str
    raw_path: str
    web_file_exists: bool
    raw_file_exists: bool
    visual_verified: bool
    source_is_circuit_map: bool
    status: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "source": self.source,
            "source_url": self.source_url,
            "web_path": self.web_path,
            "raw_path": self.raw_path,
            "web_file_exists": self.web_file_exists,
            "raw_file_exists": self.raw_file_exists,
            "visual_verified": self.visual_verified,
            "source_is_circuit_map": self.source_is_circuit_map,
            "status": self.status,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TrackAssetAuditReport:
    generated_at: str
    year: int
    event_count: int
    passed_event_count: int
    missing_asset_count: int
    missing_file_count: int
    non_circuit_source_count: int
    unverified_visual_count: int
    status: str
    rows: tuple[TrackAssetAuditRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "year": self.year,
            "event_count": self.event_count,
            "passed_event_count": self.passed_event_count,
            "missing_asset_count": self.missing_asset_count,
            "missing_file_count": self.missing_file_count,
            "non_circuit_source_count": self.non_circuit_source_count,
            "unverified_visual_count": self.unverified_visual_count,
            "status": self.status,
            "rows": [row.to_dict() for row in self.rows],
        }


class TrackMapAssetProvider:
    """Loads archived verified visual track maps by event id."""

    def __init__(self, manifest_path: Path | str = DEFAULT_TRACK_ASSET_MANIFEST) -> None:
        self.manifest_path = Path(manifest_path)
        self._assets: dict[str, TrackMapAsset] | None = None

    def load_for_event_id(self, event_id: str) -> TrackMapAsset | None:
        return self._load_assets().get(event_id)

    def load_for_event_name(self, event_name: str) -> TrackMapAsset | None:
        return self.load_for_event_id(event_id_from_name(event_name))

    def _load_assets(self) -> dict[str, TrackMapAsset]:
        if self._assets is not None:
            return self._assets
        if not self.manifest_path.exists():
            self._assets = {}
            return self._assets
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._assets = {}
            return self._assets
        records = raw.get("records") if isinstance(raw, dict) else raw
        assets: dict[str, TrackMapAsset] = {}
        if isinstance(records, list):
            for row in records:
                if not isinstance(row, dict):
                    continue
                event_id = str(row.get("event_id") or "")
                web_path = str(row.get("web_path") or "")
                source_url = str(row.get("url") or row.get("source_url") or "")
                raw_path = str(row.get("raw_path") or "")
                if not event_id or not web_path or not source_url:
                    continue
                assets[event_id] = TrackMapAsset(
                    event_id=event_id,
                    event_name=str(row.get("event_name") or event_id),
                    source=str(row.get("source") or "f1_official_track_map"),
                    source_url=source_url,
                    web_path=web_path,
                    raw_path=raw_path,
                    captured_at=str(row.get("captured_at") or "") or None,
                    circuit_key=_string(row.get("circuit_key")),
                    circuit_short_name=_string(row.get("circuit_short_name")),
                    geometry_overlay=row.get("geometry_overlay") if isinstance(row.get("geometry_overlay"), dict) else None,
                )
        self._assets = assets
        return assets


class TrackAssetAuditor:
    """Checks that loaded season events point at verified circuit-map assets."""

    VALID_SOURCES = {"f1_official_circuit_map", "madring_official_circuit_map"}

    def __init__(self, project_root: Path | str = Path(".")) -> None:
        self.project_root = Path(project_root)

    def build(self, year: int, events: list[Any]) -> TrackAssetAuditReport:
        from f1predict.domain import utc_now

        rows = tuple(self._row(event) for event in events)
        missing_asset_count = sum(1 for row in rows if row.status == "missing_asset")
        missing_file_count = sum(
            1 for row in rows
            if "web_file_missing" in row.warnings or "raw_file_missing" in row.warnings
        )
        non_circuit_source_count = sum(1 for row in rows if not row.source_is_circuit_map)
        unverified_visual_count = sum(1 for row in rows if not row.visual_verified)
        passed_event_count = sum(1 for row in rows if row.status == "passed")
        status = "passed" if passed_event_count == len(rows) and rows else "inputs_required"
        return TrackAssetAuditReport(
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            year=year,
            event_count=len(rows),
            passed_event_count=passed_event_count,
            missing_asset_count=missing_asset_count,
            missing_file_count=missing_file_count,
            non_circuit_source_count=non_circuit_source_count,
            unverified_visual_count=unverified_visual_count,
            status=status,
            rows=rows,
        )

    def write(
        self,
        year: int,
        events: list[Any],
        output_dir: Path | str = Path("reports/track_assets"),
    ) -> Path:
        report = self.build(year, events)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{year}_track_asset_audit.json"
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _row(self, event: Any) -> TrackAssetAuditRow:
        refs = getattr(event, "feature_refs", {}) or {}
        provenance = refs.get("event_input_provenance") if isinstance(refs, dict) else {}
        asset = refs.get("track_map_asset") if isinstance(refs, dict) else None
        if asset is None and isinstance(provenance, dict):
            asset = provenance.get("track_map_asset")
        event_id = str(getattr(event, "event_id", "") or "")
        event_name = str(getattr(event, "name", "") or event_id)
        if not isinstance(asset, dict):
            return TrackAssetAuditRow(
                event_id=event_id,
                event_name=event_name,
                source="",
                source_url="",
                web_path="",
                raw_path="",
                web_file_exists=False,
                raw_file_exists=False,
                visual_verified=False,
                source_is_circuit_map=False,
                status="missing_asset",
                warnings=("missing_asset",),
            )

        source = str(asset.get("source") or "")
        source_url = str(asset.get("source_url") or "")
        web_path = str(asset.get("web_path") or "")
        raw_path = str(asset.get("raw_path") or "")
        web_file = self._resolve_web_path(web_path)
        raw_file = self._resolve_project_path(raw_path)
        visual_verified = bool(asset.get("visual_verified")) and asset.get("quality") == "verified_visual"
        source_is_circuit_map = (
            source in self.VALID_SOURCES
            and "Track%20icons" not in source_url
            and ("Circuit%20maps" in source_url or source == "madring_official_circuit_map")
        )
        warnings: list[str] = []
        if not web_file.exists():
            warnings.append("web_file_missing")
        if raw_path and not raw_file.exists():
            warnings.append("raw_file_missing")
        if not source_is_circuit_map:
            warnings.append("non_circuit_map_source")
        if not visual_verified:
            warnings.append("visual_not_verified")
        status = "passed" if not warnings else "review_required"
        return TrackAssetAuditRow(
            event_id=event_id,
            event_name=event_name,
            source=source,
            source_url=source_url,
            web_path=web_path,
            raw_path=raw_path,
            web_file_exists=web_file.exists(),
            raw_file_exists=raw_file.exists() if raw_path else False,
            visual_verified=visual_verified,
            source_is_circuit_map=source_is_circuit_map,
            status=status,
            warnings=tuple(warnings),
        )

    def _resolve_web_path(self, web_path: str) -> Path:
        path = web_path.lstrip("/")
        if path.startswith("assets/"):
            return self.project_root / "web" / path
        return self._resolve_project_path(path)

    def _resolve_project_path(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.project_root / candidate


def event_id_from_name(event_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", event_name).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"\bgrand prix\b", "", ascii_name, flags=re.IGNORECASE)
    words = re.findall(r"[A-Za-z0-9]+", name.lower())
    return "_".join(words + ["gp"]) if words else "generated_gp"


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
