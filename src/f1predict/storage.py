"""Point-in-time raw snapshot storage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "snapshot"


@dataclass(frozen=True)
class SnapshotRecord:
    source: str
    dataset: str
    captured_at: str
    path: Path
    item_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "dataset": self.dataset,
            "captured_at": self.captured_at,
            "path": str(self.path),
            "item_count": self.item_count,
        }


class RawSnapshotStore:
    """Append-only JSON snapshot store.

    Files are grouped by source, dataset, and UTC capture date. A sidecar meta
    file records capture metadata so replay code can later enforce point-in-time
    access.
    """

    def __init__(self, root: Path | str = Path("data/raw")) -> None:
        self.root = Path(root)

    def write_json(
        self,
        source: str,
        dataset: str,
        payload: Any,
        params: dict[str, Any] | None = None,
    ) -> SnapshotRecord:
        captured_at = utc_now().replace(microsecond=0).isoformat()
        date_part = captured_at[:10]
        stem = safe_name(f"{dataset}_{captured_at}")
        directory = self.root / safe_name(source) / safe_name(dataset) / date_part
        directory.mkdir(parents=True, exist_ok=True)
        data_path = directory / f"{stem}.json"
        meta_path = directory / f"{stem}.meta.json"
        data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        item_count = len(payload) if isinstance(payload, list) else 1
        meta = {
            "source": source,
            "dataset": dataset,
            "captured_at": captured_at,
            "params": params or {},
            "item_count": item_count,
            "data_path": str(data_path),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return SnapshotRecord(source, dataset, captured_at, data_path, item_count)
