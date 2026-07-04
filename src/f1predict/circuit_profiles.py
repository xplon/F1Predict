"""Source-backed circuit profile loading for event inputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.results import normalize_event_name


@dataclass(frozen=True)
class CircuitProfile:
    event_key: str | None
    meeting_key: str | None
    circuit_key: str | None
    circuit_name: str | None
    source: str
    source_url: str | None
    source_path: str
    captured_at: str | None
    track_map: list[tuple[float, float]]
    source_point_count: int
    corner_count: int
    geometry_metrics: dict[str, float]

    def provenance(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_url": self.source_url,
            "path": self.source_path,
            "captured_at": self.captured_at,
            "circuit_key": self.circuit_key,
            "meeting_key": self.meeting_key,
            "source_point_count": self.source_point_count,
            "corner_count": self.corner_count,
            "geometry_metrics": self.geometry_metrics,
            "quality": "verified",
        }

    def track_type_cluster(self, circuit_type: str | None = None) -> tuple[str, dict[str, Any]]:
        """Derive the model track cluster from stored circuit geometry."""

        circuit_type_text = str(circuit_type or "").lower()
        corners = int(self.geometry_metrics.get("corner_count", self.corner_count))
        avg_abs_angle = float(self.geometry_metrics.get("avg_abs_corner_angle", 0.0))
        total_abs_angle = float(self.geometry_metrics.get("total_abs_corner_angle", 0.0))
        high_angle_corners = int(self.geometry_metrics.get("high_angle_corner_count", 0))

        if "street" in circuit_type_text:
            cluster = "street"
        elif "road" in circuit_type_text and corners >= 17:
            cluster = "high_speed"
        elif corners <= 11 and avg_abs_angle < 110:
            cluster = "high_speed"
        elif total_abs_angle >= 2200 or high_angle_corners >= 9:
            cluster = "technical"
        elif corners >= 18 and avg_abs_angle <= 105:
            cluster = "high_speed"
        else:
            cluster = "power"

        return cluster, {
            "source": "circuit_geometry_cluster",
            "path": self.source_path,
            "source_url": self.source_url,
            "captured_at": self.captured_at,
            "circuit_key": self.circuit_key,
            "meeting_key": self.meeting_key,
            "circuit_type": circuit_type,
            "classifier": "v1:street_or_geometry_complexity",
            "geometry_metrics": self.geometry_metrics,
            "quality": "derived",
        }


class CircuitProfileProvider:
    """Loads latest stored circuit profile snapshots.

    Profiles are intentionally read from the append-only raw store. Prediction
    should not fetch live geometry during replay because that would break the
    point-in-time data boundary.
    """

    def __init__(self, raw_root: Path | str = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)
        self._profiles: list[CircuitProfile] | None = None

    def load_for_calendar_item(self, item: dict[str, Any]) -> CircuitProfile | None:
        profiles = self._load_profiles()
        lookups = [
            str(item.get("circuit_key") or ""),
            str(item.get("meeting_key") or ""),
            normalize_event_name(str(item.get("event_name") or "")),
            normalize_event_name(str(item.get("circuit_short_name") or "")),
            normalize_event_name(str(item.get("location") or "")),
        ]
        for lookup in [value for value in lookups if value]:
            for profile in profiles:
                if lookup in self._profile_keys(profile):
                    return profile
        return None

    def _load_profiles(self) -> list[CircuitProfile]:
        if self._profiles is not None:
            return self._profiles
        root = self.raw_root / "circuit_profiles"
        files = []
        if root.exists():
            files = [path for path in root.rglob("*.json") if not path.name.endswith(".meta.json")]
        profiles = []
        for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
            profile = self._load_file(path)
            if profile is not None:
                profiles.append(profile)
        self._profiles = profiles
        return profiles

    def _load_file(self, path: Path) -> CircuitProfile | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        track_map, source_point_count = self._track_map(raw)
        if not track_map:
            return None
        meta = self._meta(path)
        params = meta.get("params", {}) if isinstance(meta.get("params"), dict) else {}
        meeting_name = str(params.get("event_name") or raw.get("meetingName") or "")
        return CircuitProfile(
            event_key=normalize_event_name(meeting_name) if meeting_name else None,
            meeting_key=self._string_value(params.get("meeting_key") or raw.get("meetingKey")),
            circuit_key=self._string_value(params.get("circuit_key") or raw.get("circuitKey")),
            circuit_name=self._string_value(raw.get("circuitName") or raw.get("location")),
            source=self._string_value(params.get("source")) or "multiviewer_circuit_profile",
            source_url=self._string_value(params.get("circuit_info_url")),
            source_path=str(path),
            captured_at=self._string_value(meta.get("captured_at")),
            track_map=track_map,
            source_point_count=source_point_count,
            corner_count=len(raw.get("corners") or []),
            geometry_metrics=self._geometry_metrics(raw),
        )

    @staticmethod
    def _profile_keys(profile: CircuitProfile) -> set[str]:
        values = {
            profile.event_key,
            profile.meeting_key,
            profile.circuit_key,
            normalize_event_name(profile.circuit_name or ""),
        }
        return {value for value in values if value}

    @classmethod
    def _track_map(cls, raw: dict[str, Any], max_points: int = 96) -> tuple[list[tuple[float, float]], int]:
        points = cls._xy_points(raw)
        if len(points) < 4:
            points = cls._corner_points(raw)
        if len(points) < 4:
            return [], 0
        sampled = cls._sample(points, max_points)
        normalized = cls._normalize(sampled)
        if normalized and normalized[0] != normalized[-1]:
            normalized.append(normalized[0])
        return normalized, len(points)

    @staticmethod
    def _xy_points(raw: dict[str, Any]) -> list[tuple[float, float]]:
        xs = raw.get("x")
        ys = raw.get("y")
        if not isinstance(xs, list) or not isinstance(ys, list):
            return []
        points = []
        for x, y in zip(xs, ys):
            try:
                points.append((float(x), float(y)))
            except (TypeError, ValueError):
                continue
        return points

    @staticmethod
    def _corner_points(raw: dict[str, Any]) -> list[tuple[float, float]]:
        corners = raw.get("corners")
        if not isinstance(corners, list):
            return []
        points = []
        for corner in corners:
            if not isinstance(corner, dict):
                continue
            position = corner.get("trackPosition")
            if not isinstance(position, dict):
                continue
            try:
                points.append((float(position["x"]), float(position["y"])))
            except (KeyError, TypeError, ValueError):
                continue
        return points

    @staticmethod
    def _geometry_metrics(raw: dict[str, Any]) -> dict[str, float]:
        corners = raw.get("corners")
        angles = []
        if isinstance(corners, list):
            for corner in corners:
                if not isinstance(corner, dict):
                    continue
                try:
                    angles.append(abs(float(corner.get("angle", 0.0))))
                except (TypeError, ValueError):
                    continue
        total_abs_angle = sum(angles)
        return {
            "corner_count": float(len(angles)),
            "avg_abs_corner_angle": round(total_abs_angle / len(angles), 4) if angles else 0.0,
            "total_abs_corner_angle": round(total_abs_angle, 4),
            "high_angle_corner_count": float(sum(1 for angle in angles if angle >= 120.0)),
            "low_angle_corner_count": float(sum(1 for angle in angles if angle <= 45.0)),
        }

    @staticmethod
    def _sample(points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]:
        if len(points) <= max_points:
            return points
        step = max(1, len(points) // max_points)
        sampled = points[::step]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled[:max_points]

    @staticmethod
    def _normalize(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        scale = 0.84 / max(width, height)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        normalized = []
        for x, y in points:
            normalized.append(
                (
                    round(0.5 + (x - center_x) * scale, 4),
                    round(0.5 - (y - center_y) * scale, 4),
                )
            )
        return normalized

    @staticmethod
    def _meta(path: Path) -> dict[str, Any]:
        meta_path = path.with_name(f"{path.stem}.meta.json")
        if not meta_path.exists():
            return {}
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None
