"""Helpers for replay report artifact naming and discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from f1predict.domain import parse_dt


DEFAULT_REPLAY_AS_OF = "2026-06-30T00:00:00+00:00"

_REPORT_STEM_RE = re.compile(
    r"^(?P<year>\d{4})_asof_(?P<date>\d{8})T(?P<time>\d{6})(?P<offset>_[0-9]{4})?$"
)


@dataclass(frozen=True)
class ReplayArtifact:
    path: Path
    year: int
    as_of: str
    captured_at: datetime


def stem_time(value: str) -> str:
    return value.replace(":", "").replace("+", "_").replace("-", "")


def replay_stem(year: int, as_of: str) -> str:
    return f"{year}_asof_{stem_time(as_of)}"


def as_of_from_replay_stem(stem: str) -> str | None:
    match = _REPORT_STEM_RE.match(stem)
    if not match:
        return None
    date = match.group("date")
    time = match.group("time")
    offset = match.group("offset") or "_0000"
    return (
        f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        f"T{time[:2]}:{time[2:4]}:{time[4:6]}"
        f"+{offset[1:3]}:{offset[3:5]}"
    )


def latest_replay_artifact(
    directory: Path | str,
    year: int,
    suffix: str = "",
    directories: bool = False,
) -> ReplayArtifact | None:
    root = Path(directory)
    if not root.exists():
        return None
    candidates: list[ReplayArtifact] = []
    for path in root.iterdir():
        if directories and not path.is_dir():
            continue
        if not directories and not path.is_file():
            continue
        name = path.name
        if suffix:
            if not name.endswith(suffix):
                continue
            stem = name[: -len(suffix)]
        else:
            stem = name
        as_of = as_of_from_replay_stem(stem)
        if as_of is None:
            continue
        if not stem.startswith(f"{year}_asof_"):
            continue
        captured_at = parse_dt(as_of)
        if captured_at is None:
            continue
        candidates.append(
            ReplayArtifact(
                path=path,
                year=year,
                as_of=as_of,
                captured_at=captured_at,
            )
        )
    if not candidates:
        return None
    return max(candidates, key=lambda artifact: (artifact.captured_at, artifact.path.name))


def latest_replay_as_of(
    directory: Path | str,
    year: int,
    suffix: str = "",
    directories: bool = False,
) -> str | None:
    artifact = latest_replay_artifact(directory, year, suffix=suffix, directories=directories)
    return artifact.as_of if artifact else None
