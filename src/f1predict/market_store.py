"""Append-only storage for normalized market snapshots."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from f1predict.domain import MarketSnapshot, parse_dt, utc_now
from f1predict.storage import safe_name


DEFAULT_MARKET_SNAPSHOT_ROOT = Path("data/market_snapshots")


class MarketSnapshotValidationError(ValueError):
    """Raised when a market snapshot packet is malformed."""


class MarketSnapshotStore:
    """Archives standardized market snapshots used by replay and edge analysis.

    Raw exchange responses stay in `data/raw`. This store contains the normalized
    point-in-time boundary consumed by the prediction pipeline.
    """

    def __init__(self, root: Path | str = DEFAULT_MARKET_SNAPSHOT_ROOT) -> None:
        self.root = Path(root)

    def write_event_snapshots(
        self,
        event_id: str,
        snapshots: list[MarketSnapshot],
        params: dict[str, Any] | None = None,
    ) -> Path:
        snapshots = _dedupe_snapshots(snapshots)
        if not snapshots:
            raise MarketSnapshotValidationError(f"No market snapshots to archive for event_id={event_id}")
        wrong_event = [snapshot.market_id for snapshot in snapshots if snapshot.event_id != event_id]
        if wrong_event:
            raise MarketSnapshotValidationError(
                f"Cannot archive snapshots for a different event_id: {', '.join(wrong_event)}"
            )
        for index, snapshot in enumerate(snapshots, start=1):
            self._validate_snapshot(snapshot, Path("<memory>"), index)

        archived_at = utc_now().isoformat()
        directory = self.root / safe_name(event_id) / "snapshots" / archived_at[:10]
        directory.mkdir(parents=True, exist_ok=True)
        data_path, meta_path = _unique_snapshot_paths(directory, safe_name(f"{event_id}_{archived_at}"))
        lines = [json.dumps(snapshot.__dict__, ensure_ascii=False, sort_keys=True) for snapshot in snapshots]
        data_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        meta = {
            "source": "market_snapshot",
            "event_id": event_id,
            "archived_at": archived_at,
            "snapshot_count": len(snapshots),
            "data_path": str(data_path),
            "params": params or {},
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return data_path

    def event_snapshot_paths(self, event_id: str) -> list[Path]:
        directory = self.root / safe_name(event_id)
        if not directory.exists():
            return []
        paths = [
            path
            for path in directory.rglob("*.jsonl")
            if not path.name.endswith(".meta.json")
        ]
        return sorted(paths, key=lambda path: (path.stat().st_mtime, str(path)))

    def all_snapshot_paths(self) -> list[Path]:
        if not self.root.exists():
            return []
        paths = [
            path
            for path in self.root.rglob("*.jsonl")
            if not path.name.endswith(".meta.json")
        ]
        return sorted(paths, key=lambda path: (path.stat().st_mtime, str(path)))

    def load_event(self, event_id: str) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for path in self.event_snapshot_paths(event_id):
            snapshots.extend(self.load_file(path))
        return _dedupe_snapshots([snapshot for snapshot in snapshots if snapshot.event_id == event_id])

    def load_all(self) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for path in self.all_snapshot_paths():
            snapshots.extend(self.load_file(path))
        return _dedupe_snapshots(snapshots)

    def load_file(self, path: Path | str) -> list[MarketSnapshot]:
        file_path = Path(path)
        if not file_path.exists():
            raise MarketSnapshotValidationError(f"{file_path}: file does not exist")
        if file_path.suffix.lower() == ".jsonl":
            return self._load_jsonl(file_path)
        return self._load_json(file_path)

    def validate_event_file(self, event_id: str, path: Path | str) -> list[MarketSnapshot]:
        snapshots = self.load_file(path)
        wrong_event = [snapshot.market_id for snapshot in snapshots if snapshot.event_id != event_id]
        if wrong_event:
            raise MarketSnapshotValidationError(
                f"{path}: snapshots for a different event_id: {', '.join(wrong_event)}"
            )
        return snapshots

    def _load_jsonl(self, file_path: Path) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for line_no, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                snapshot = MarketSnapshot(**json.loads(stripped))
            except Exception as exc:  # noqa: BLE001 - include line context.
                raise MarketSnapshotValidationError(f"{file_path}:{line_no}: {exc}") from exc
            self._validate_snapshot(snapshot, file_path, line_no)
            snapshots.append(snapshot)
        return snapshots

    def _load_json(self, file_path: Path) -> list[MarketSnapshot]:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - include path context.
            raise MarketSnapshotValidationError(f"{file_path}: {exc}") from exc
        if isinstance(payload, dict) and isinstance(payload.get("snapshots"), list):
            rows = payload["snapshots"]
        elif isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = [payload]
        else:
            raise MarketSnapshotValidationError(f"{file_path}: expected object, list, or snapshots list")

        snapshots: list[MarketSnapshot] = []
        for index, row in enumerate(rows, start=1):
            try:
                snapshot = MarketSnapshot(**row)
            except Exception as exc:  # noqa: BLE001 - include item context.
                raise MarketSnapshotValidationError(f"{file_path}:{index}: {exc}") from exc
            self._validate_snapshot(snapshot, file_path, index)
            snapshots.append(snapshot)
        return snapshots

    @staticmethod
    def _validate_snapshot(snapshot: MarketSnapshot, path: Path, line_no: int) -> None:
        prefix = f"{path}:{line_no}"
        if not snapshot.market_id:
            raise MarketSnapshotValidationError(f"{prefix}: market_id is required")
        if not snapshot.event_id:
            raise MarketSnapshotValidationError(f"{prefix}: event_id is required")
        if not snapshot.market_type:
            raise MarketSnapshotValidationError(f"{prefix}: market_type is required")
        if parse_dt(snapshot.captured_at) is None:
            raise MarketSnapshotValidationError(f"{prefix}: captured_at must be an ISO datetime")
        if not snapshot.prices:
            raise MarketSnapshotValidationError(f"{prefix}: prices are required")
        for outcome_id, price in snapshot.prices.items():
            if not outcome_id:
                raise MarketSnapshotValidationError(f"{prefix}: outcome id is required")
            if not isinstance(price, (int, float)) or not math.isfinite(float(price)):
                raise MarketSnapshotValidationError(f"{prefix}: price for {outcome_id} must be finite")
            if not (0.0 <= float(price) <= 1.0):
                raise MarketSnapshotValidationError(f"{prefix}: price for {outcome_id} must be 0..1")
        if snapshot.liquidity < 0.0:
            raise MarketSnapshotValidationError(f"{prefix}: liquidity must be non-negative")
        if snapshot.spread_estimate < 0.0:
            raise MarketSnapshotValidationError(f"{prefix}: spread_estimate must be non-negative")


def _dedupe_snapshots(snapshots: list[MarketSnapshot]) -> list[MarketSnapshot]:
    by_key: dict[tuple[str, str, str, str, tuple[tuple[str, float], ...]], MarketSnapshot] = {}
    for snapshot in snapshots:
        price_key = tuple(sorted((outcome_id, round(float(price), 8)) for outcome_id, price in snapshot.prices.items()))
        by_key[
            (
                snapshot.market_id,
                snapshot.event_id,
                snapshot.market_type,
                snapshot.captured_at,
                price_key,
            )
        ] = snapshot
    return list(by_key.values())


def _unique_snapshot_paths(directory: Path, stem: str) -> tuple[Path, Path]:
    data_path = directory / f"{stem}.jsonl"
    meta_path = directory / f"{stem}.meta.json"
    suffix = 1
    while data_path.exists() or meta_path.exists():
        data_path = directory / f"{stem}_{suffix}.jsonl"
        meta_path = directory / f"{stem}_{suffix}.meta.json"
        suffix += 1
    return data_path, meta_path
