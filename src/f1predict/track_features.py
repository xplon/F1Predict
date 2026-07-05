"""Source-backed track feature vectors for race simulation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from f1predict.domain import RaceEvent


@dataclass(frozen=True)
class TrackFeatureVector:
    """Compact numeric description of circuit and environment demands.

    Values are derived from stored event inputs. Geometry-heavy fields are
    proxies because current circuit profiles expose corner angle and progress,
    not FIA-grade speed/radius/DRS zone definitions.
    """

    event_id: str
    track_type: str
    source_status: str
    source_paths: dict[str, str]
    warning_codes: tuple[str, ...]
    corner_count: int
    low_speed_corner_count: int
    medium_speed_corner_count: int
    high_speed_corner_count: int
    right_angle_corner_count: int
    long_straight_count: int
    max_straight_proxy: float
    straightness_index: float
    braking_energy_index: float
    traction_index: float
    aero_efficiency_index: float
    mechanical_grip_index: float
    overtaking_index: float
    track_position_value: float
    pit_loss_seconds: float
    safety_car_probability: float
    red_flag_probability: float
    tyre_degradation_index: float
    wet_probability: float
    precipitation_p90_mm: float | None
    altitude_m: float | None
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "track_type": self.track_type,
            "source_status": self.source_status,
            "source_paths": self.source_paths,
            "warning_codes": list(self.warning_codes),
            "corner_count": self.corner_count,
            "low_speed_corner_count": self.low_speed_corner_count,
            "medium_speed_corner_count": self.medium_speed_corner_count,
            "high_speed_corner_count": self.high_speed_corner_count,
            "right_angle_corner_count": self.right_angle_corner_count,
            "long_straight_count": self.long_straight_count,
            "max_straight_proxy": self.max_straight_proxy,
            "straightness_index": self.straightness_index,
            "braking_energy_index": self.braking_energy_index,
            "traction_index": self.traction_index,
            "aero_efficiency_index": self.aero_efficiency_index,
            "mechanical_grip_index": self.mechanical_grip_index,
            "overtaking_index": self.overtaking_index,
            "track_position_value": self.track_position_value,
            "pit_loss_seconds": self.pit_loss_seconds,
            "safety_car_probability": self.safety_car_probability,
            "red_flag_probability": self.red_flag_probability,
            "tyre_degradation_index": self.tyre_degradation_index,
            "wet_probability": self.wet_probability,
            "precipitation_p90_mm": self.precipitation_p90_mm,
            "altitude_m": self.altitude_m,
            "provenance": self.provenance,
        }


def track_feature_vector(event: RaceEvent, root: Path | str = Path(".")) -> TrackFeatureVector:
    """Build a track/environment vector for an event using local artifacts."""

    root_path = Path(root)
    refs = event.feature_refs if isinstance(event.feature_refs, dict) else {}
    circuit_ref = _first_mapping(
        refs.get("circuit_profile"),
        _nested_mapping(refs, ("event_input_provenance", "circuit_geometry")),
        _nested_mapping(refs, ("event_input_provenance", "track_map")),
    )
    weather_ref = _first_mapping(
        refs.get("weather_forecast"),
        refs.get("weather_profile"),
        _nested_mapping(refs, ("event_input_provenance", "weather_prior")),
    )

    circuit_path = _resolve_path(_string_value(circuit_ref.get("path")) if circuit_ref else None, root_path)
    raw_circuit = _read_json(circuit_path) if circuit_path else {}
    corners = _corner_rows(raw_circuit)
    angles = [abs(angle) for angle in (_float_value(row.get("angle")) for row in corners) if angle is not None]
    progress = [
        value
        for value in (_float_value(row.get("length")) for row in corners)
        if value is not None and value >= 0.0
    ]
    segment_lengths = _segment_lengths(progress)
    max_straight_proxy = max(segment_lengths, default=0.0)
    long_straight_count = _long_segment_count(segment_lengths)
    corner_count = len(angles) or int(_float_value(_nested_value(circuit_ref or {}, ("geometry_metrics", "corner_count"))) or 0)
    low_speed_corners = sum(1 for angle in angles if angle >= 115.0)
    medium_speed_corners = sum(1 for angle in angles if 65.0 <= angle < 115.0)
    high_speed_corners = sum(1 for angle in angles if angle < 65.0)
    right_angle_corners = sum(1 for angle in angles if 75.0 <= angle <= 115.0)

    denominator = max(1, corner_count)
    low_ratio = low_speed_corners / denominator
    medium_ratio = medium_speed_corners / denominator
    high_ratio = high_speed_corners / denominator
    long_ratio = long_straight_count / denominator
    avg_angle = mean(angles) if angles else _float_value(
        _nested_value(circuit_ref or {}, ("geometry_metrics", "avg_abs_corner_angle"))
    ) or 90.0
    total_angle = sum(angles) if angles else _float_value(
        _nested_value(circuit_ref or {}, ("geometry_metrics", "total_abs_corner_angle"))
    ) or avg_angle * corner_count
    complexity = _clamp((total_angle / max(1.0, corner_count) - 70.0) / 125.0, 0.0, 1.0)
    corner_density = _clamp((corner_count - 10.0) / 12.0, 0.0, 1.0)
    straightness = _clamp(high_ratio * 0.45 + long_ratio * 0.35 + (1.0 - min(avg_angle, 180.0) / 180.0) * 0.20, 0.0, 1.0)

    base_demands = _base_track_demands(event.track_type)
    braking = _clamp(base_demands["braking"] * 0.45 + low_ratio * 0.28 + medium_ratio * 0.12 + long_ratio * 0.15, 0.0, 1.0)
    traction = _clamp(base_demands["traction"] * 0.42 + low_ratio * 0.38 + corner_density * 0.20, 0.0, 1.0)
    aero = _clamp(base_demands["aero"] * 0.40 + straightness * 0.38 + high_ratio * 0.22, 0.0, 1.0)
    mechanical = _clamp(base_demands["mechanical"] * 0.42 + low_ratio * 0.28 + complexity * 0.18 + corner_density * 0.12, 0.0, 1.0)
    overtaking = _clamp(base_demands["overtaking"] * 0.50 + long_ratio * 0.26 + braking * 0.18 - base_demands["street_penalty"] * 0.22, 0.02, 0.95)
    track_position = _clamp(
        base_demands["track_position"] * 0.62
        + (1.0 - overtaking) * 0.30
        + base_demands["street_penalty"] * 0.12,
        0.05,
        0.95,
    )

    wet_probability = _clamp(float(event.weather_prior.get("wet_probability", 0.0)), 0.0, 1.0)
    precipitation_p90 = _float_value(_nested_value(weather_ref or {}, ("precipitation_p90_mm",)))
    raw_altitude = _float_value(
        _nested_value(weather_ref or {}, ("elevation_m",))
        if weather_ref
        else None
    )
    altitude_m, altitude_warning = _quality_checked_altitude(raw_altitude)
    warning_codes = []
    if not circuit_path or not raw_circuit:
        warning_codes.append("track_feature_missing_circuit_geometry")
    if not weather_ref:
        warning_codes.append("track_feature_missing_weather_profile")
    if altitude_warning:
        warning_codes.append(altitude_warning)

    tyre_deg = _clamp(
        base_demands["tyre_deg"] * 0.48
        + aero * 0.23
        + mechanical * 0.16
        + max(0.0, (precipitation_p90 or 0.0) - 6.0) * 0.012
        - wet_probability * 0.06,
        0.12,
        0.95,
    )
    safety_car = _clamp(
        float(event.weather_prior.get("safety_car_probability", base_demands["safety_car"]))
        + track_position * 0.055
        + wet_probability * 0.045
        + base_demands["street_penalty"] * 0.035,
        0.08,
        0.78,
    )
    red_flag = _clamp(0.015 + safety_car * 0.11 + wet_probability * 0.035 + base_demands["street_penalty"] * 0.025, 0.01, 0.18)
    pit_loss = _clamp(base_demands["pit_loss"] + track_position * 1.4 - overtaking * 0.45, 17.5, 24.5)

    if circuit_path and raw_circuit and weather_ref:
        source_status = "source_backed_derived_proxy"
    elif circuit_path and raw_circuit:
        source_status = "geometry_backed_derived_proxy"
    else:
        source_status = "track_type_fallback"

    source_paths = {}
    if circuit_path:
        source_paths["circuit_profile"] = str(circuit_path)
    weather_path = _string_value((weather_ref or {}).get("path"))
    if weather_path:
        source_paths["weather_profile"] = weather_path

    return TrackFeatureVector(
        event_id=event.event_id,
        track_type=event.track_type,
        source_status=source_status,
        source_paths=source_paths,
        warning_codes=tuple(warning_codes),
        corner_count=corner_count,
        low_speed_corner_count=low_speed_corners,
        medium_speed_corner_count=medium_speed_corners,
        high_speed_corner_count=high_speed_corners,
        right_angle_corner_count=right_angle_corners,
        long_straight_count=long_straight_count,
        max_straight_proxy=round(max_straight_proxy, 4),
        straightness_index=round(straightness, 4),
        braking_energy_index=round(braking, 4),
        traction_index=round(traction, 4),
        aero_efficiency_index=round(aero, 4),
        mechanical_grip_index=round(mechanical, 4),
        overtaking_index=round(overtaking, 4),
        track_position_value=round(track_position, 4),
        pit_loss_seconds=round(pit_loss, 3),
        safety_car_probability=round(safety_car, 4),
        red_flag_probability=round(red_flag, 4),
        tyre_degradation_index=round(tyre_deg, 4),
        wet_probability=round(wet_probability, 4),
        precipitation_p90_mm=round(precipitation_p90, 4) if precipitation_p90 is not None else None,
        altitude_m=round(altitude_m, 2) if altitude_m is not None else None,
        provenance={
            "circuit_source": (circuit_ref or {}).get("source"),
            "circuit_source_url": (circuit_ref or {}).get("source_url"),
            "weather_source": (weather_ref or {}).get("source") if weather_ref else None,
            "method": "v1:circuit_corner_angle_progress_weather_prior_proxy",
            "geometry_proxy_note": (
                "Corner speed classes and straight counts are derived from stored corner angle/progress fields; "
                "not official speed or DRS/deployment-zone data."
            ),
        },
    )


def _base_track_demands(track_type: str) -> dict[str, float]:
    return {
        "street": {
            "braking": 0.78,
            "traction": 0.78,
            "aero": 0.30,
            "mechanical": 0.76,
            "overtaking": 0.25,
            "track_position": 0.87,
            "street_penalty": 1.0,
            "tyre_deg": 0.42,
            "safety_car": 0.62,
            "pit_loss": 21.5,
        },
        "street_low_speed": {
            "braking": 0.82,
            "traction": 0.84,
            "aero": 0.26,
            "mechanical": 0.82,
            "overtaking": 0.20,
            "track_position": 0.90,
            "street_penalty": 1.0,
            "tyre_deg": 0.38,
            "safety_car": 0.65,
            "pit_loss": 22.8,
        },
        "low_speed": {
            "braking": 0.68,
            "traction": 0.72,
            "aero": 0.32,
            "mechanical": 0.70,
            "overtaking": 0.36,
            "track_position": 0.68,
            "street_penalty": 0.25,
            "tyre_deg": 0.48,
            "safety_car": 0.30,
            "pit_loss": 20.5,
        },
        "technical": {
            "braking": 0.66,
            "traction": 0.60,
            "aero": 0.58,
            "mechanical": 0.66,
            "overtaking": 0.40,
            "track_position": 0.60,
            "street_penalty": 0.10,
            "tyre_deg": 0.66,
            "safety_car": 0.44,
            "pit_loss": 20.6,
        },
        "power": {
            "braking": 0.52,
            "traction": 0.42,
            "aero": 0.62,
            "mechanical": 0.42,
            "overtaking": 0.58,
            "track_position": 0.38,
            "street_penalty": 0.0,
            "tyre_deg": 0.58,
            "safety_car": 0.40,
            "pit_loss": 20.1,
        },
        "high_speed": {
            "braking": 0.56,
            "traction": 0.36,
            "aero": 0.78,
            "mechanical": 0.46,
            "overtaking": 0.54,
            "track_position": 0.34,
            "street_penalty": 0.0,
            "tyre_deg": 0.72,
            "safety_car": 0.38,
            "pit_loss": 19.2,
        },
        "balanced": {
            "braking": 0.56,
            "traction": 0.50,
            "aero": 0.56,
            "mechanical": 0.54,
            "overtaking": 0.48,
            "track_position": 0.48,
            "street_penalty": 0.0,
            "tyre_deg": 0.56,
            "safety_car": 0.36,
            "pit_loss": 20.0,
        },
    }.get(
        track_type,
        {
            "braking": 0.55,
            "traction": 0.52,
            "aero": 0.54,
            "mechanical": 0.54,
            "overtaking": 0.45,
            "track_position": 0.50,
            "street_penalty": 0.0,
            "tyre_deg": 0.55,
            "safety_car": 0.40,
            "pit_loss": 20.0,
        },
    )


def _corner_rows(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    corners = raw.get("corners")
    if not isinstance(corners, list):
        return []
    return [row for row in corners if isinstance(row, Mapping)]


def _segment_lengths(progress: list[float]) -> list[float]:
    ordered = sorted(progress)
    if len(ordered) < 2:
        return []
    return [max(0.0, later - earlier) for earlier, later in zip(ordered, ordered[1:])]


def _long_segment_count(lengths: list[float]) -> int:
    if not lengths:
        return 0
    sorted_lengths = sorted(lengths)
    q75 = sorted_lengths[int((len(sorted_lengths) - 1) * 0.75)]
    avg = mean(sorted_lengths)
    threshold = max(q75, avg * 1.15)
    return sum(1 for length in lengths if length >= threshold)


def _quality_checked_altitude(value: float | None) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if value < -500.0 or value > 3000.0:
        return None, "weather_profile_altitude_out_of_model_bounds"
    return value, None


def _resolve_path(value: str | None, root: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return path
    if not path.is_absolute():
        candidate = root / path
        if candidate.exists():
            return candidate
    return path if path.exists() else None


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_mapping(*values: Any) -> Mapping[str, Any] | None:
    for value in values:
        if isinstance(value, Mapping):
            return value
    return None


def _nested_mapping(root: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any] | None:
    value = _nested_value(root, path)
    return value if isinstance(value, Mapping) else None


def _nested_value(root: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = root
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))
