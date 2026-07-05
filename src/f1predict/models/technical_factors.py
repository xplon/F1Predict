"""Technical mechanism profiles used by simulator-facing Codex factors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TrackDemandProfile:
    track_type: str
    power_demand: float
    ers_demand: float
    drag_demand: float
    traction_demand: float
    mass_sensitivity: float
    launch_importance: float
    braking_energy_demand: float
    altitude_power_derate: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "track_type": self.track_type,
            "power_demand": self.power_demand,
            "ers_demand": self.ers_demand,
            "drag_demand": self.drag_demand,
            "traction_demand": self.traction_demand,
            "mass_sensitivity": self.mass_sensitivity,
            "launch_importance": self.launch_importance,
            "braking_energy_demand": self.braking_energy_demand,
            "altitude_power_derate": self.altitude_power_derate,
            "notes": list(self.notes),
        }

    def component_value(self, component: str | None) -> float | None:
        if not component:
            return None
        value = getattr(self, component, None)
        return float(value) if isinstance(value, (float, int)) else None


@dataclass(frozen=True)
class TechnicalFactorProfile:
    metric: str
    base_multiplier: float
    track_sensitivity: dict[str, float]
    default_track_sensitivity: float
    qualifying_multiplier: float
    mechanism: str
    demand_component: str | None = None

    def context_multiplier(
        self,
        track_type: str,
        mode: str = "race",
        feature_refs: Mapping[str, Any] | None = None,
    ) -> float:
        multiplier = self.base_multiplier + self.track_demand_value(track_type, feature_refs)
        if mode == "qualifying":
            multiplier *= self.qualifying_multiplier
        return multiplier

    def context_reason(
        self,
        track_type: str,
        mode: str = "race",
        feature_refs: Mapping[str, Any] | None = None,
    ) -> str:
        sensitivity = self.track_demand_value(track_type, feature_refs)
        multiplier = self.context_multiplier(track_type, mode, feature_refs)
        demand_profile = track_demand_profile(track_type, feature_refs)
        component = self.demand_component or "legacy_track_sensitivity"
        component_reason = (
            f", demand_component={component}, demand_value={sensitivity:.2f}, "
            f"launch_importance={demand_profile.launch_importance:.2f}, "
            f"altitude_power_derate={demand_profile.altitude_power_derate:.2f}"
        )
        source_note = f", profile_notes={' | '.join(demand_profile.notes[-3:])}" if demand_profile.notes else ""
        return (
            f"{self.metric} uses {self.mechanism}; track_type={track_type}, "
            f"base={self.base_multiplier:.2f}, track_sensitivity={sensitivity:.2f}, "
            f"mode={mode}, context_multiplier={multiplier:.3f}{component_reason}{source_note}"
        )

    def track_demand_value(
        self,
        track_type: str,
        feature_refs: Mapping[str, Any] | None = None,
    ) -> float:
        demand_profile = track_demand_profile(track_type, feature_refs)
        demand_value = demand_profile.component_value(self.demand_component)
        if demand_value is not None:
            return demand_value
        return self.track_sensitivity.get(track_type, self.default_track_sensitivity)


POWER_TRACK_SENSITIVITY = {
    "power": 0.58,
    "high_speed": 0.50,
    "balanced": 0.28,
    "technical": 0.18,
    "street": 0.12,
    "street_low_speed": 0.08,
    "low_speed": 0.08,
}

ENERGY_RECOVERY_SENSITIVITY = {
    "power": 0.36,
    "high_speed": 0.34,
    "technical": 0.24,
    "balanced": 0.22,
    "street": 0.18,
    "street_low_speed": 0.16,
    "low_speed": 0.16,
}

DRAG_SENSITIVITY = {
    "power": 0.40,
    "high_speed": 0.42,
    "balanced": 0.25,
    "technical": 0.18,
    "street": 0.12,
    "street_low_speed": 0.10,
    "low_speed": 0.10,
}

LOW_SPEED_SENSITIVITY = {
    "street_low_speed": 0.45,
    "low_speed": 0.40,
    "street": 0.34,
    "technical": 0.22,
    "balanced": 0.16,
    "high_speed": 0.10,
    "power": 0.08,
}

WEIGHT_SENSITIVITY = {
    "high_speed": 0.32,
    "technical": 0.28,
    "balanced": 0.26,
    "street": 0.23,
    "street_low_speed": 0.22,
    "low_speed": 0.22,
    "power": 0.20,
}

TRACK_DEMAND_PROFILES: dict[str, TrackDemandProfile] = {
    "power": TrackDemandProfile(
        track_type="power",
        power_demand=POWER_TRACK_SENSITIVITY["power"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["power"],
        drag_demand=DRAG_SENSITIVITY["power"],
        traction_demand=LOW_SPEED_SENSITIVITY["power"],
        mass_sensitivity=WEIGHT_SENSITIVITY["power"],
        launch_importance=0.20,
        braking_energy_demand=0.30,
        altitude_power_derate=0.02,
        notes=("Long full-throttle sections dominate; straight-line and drag claims receive the strongest context.",),
    ),
    "high_speed": TrackDemandProfile(
        track_type="high_speed",
        power_demand=POWER_TRACK_SENSITIVITY["high_speed"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["high_speed"],
        drag_demand=DRAG_SENSITIVITY["high_speed"],
        traction_demand=LOW_SPEED_SENSITIVITY["high_speed"],
        mass_sensitivity=WEIGHT_SENSITIVITY["high_speed"],
        launch_importance=0.24,
        braking_energy_demand=0.34,
        altitude_power_derate=0.00,
        notes=("Sustained high-speed load and repeated deployment make clipping, drag, and mass visible.",),
    ),
    "balanced": TrackDemandProfile(
        track_type="balanced",
        power_demand=POWER_TRACK_SENSITIVITY["balanced"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["balanced"],
        drag_demand=DRAG_SENSITIVITY["balanced"],
        traction_demand=LOW_SPEED_SENSITIVITY["balanced"],
        mass_sensitivity=WEIGHT_SENSITIVITY["balanced"],
        launch_importance=0.28,
        braking_energy_demand=0.28,
        altitude_power_derate=0.00,
        notes=("Mixed layouts split value across power, aero efficiency, traction, and mass.",),
    ),
    "technical": TrackDemandProfile(
        track_type="technical",
        power_demand=POWER_TRACK_SENSITIVITY["technical"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["technical"],
        drag_demand=DRAG_SENSITIVITY["technical"],
        traction_demand=LOW_SPEED_SENSITIVITY["technical"],
        mass_sensitivity=WEIGHT_SENSITIVITY["technical"],
        launch_importance=0.32,
        braking_energy_demand=0.36,
        altitude_power_derate=0.00,
        notes=("Corner density raises the value of braking, deployment recovery, traction, and mass control.",),
    ),
    "street": TrackDemandProfile(
        track_type="street",
        power_demand=POWER_TRACK_SENSITIVITY["street"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["street"],
        drag_demand=DRAG_SENSITIVITY["street"],
        traction_demand=LOW_SPEED_SENSITIVITY["street"],
        mass_sensitivity=WEIGHT_SENSITIVITY["street"],
        launch_importance=0.42,
        braking_energy_demand=0.40,
        altitude_power_derate=0.00,
        notes=("Traction, launch phase, braking recovery, and safety-car-sensitive execution matter more than pure power.",),
    ),
    "street_low_speed": TrackDemandProfile(
        track_type="street_low_speed",
        power_demand=POWER_TRACK_SENSITIVITY["street_low_speed"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["street_low_speed"],
        drag_demand=DRAG_SENSITIVITY["street_low_speed"],
        traction_demand=LOW_SPEED_SENSITIVITY["street_low_speed"],
        mass_sensitivity=WEIGHT_SENSITIVITY["street_low_speed"],
        launch_importance=0.48,
        braking_energy_demand=0.42,
        altitude_power_derate=0.00,
        notes=("Low-speed street layouts amplify launch, traction, braking, and mass more than straight-line power.",),
    ),
    "low_speed": TrackDemandProfile(
        track_type="low_speed",
        power_demand=POWER_TRACK_SENSITIVITY["low_speed"],
        ers_demand=ENERGY_RECOVERY_SENSITIVITY["low_speed"],
        drag_demand=DRAG_SENSITIVITY["low_speed"],
        traction_demand=LOW_SPEED_SENSITIVITY["low_speed"],
        mass_sensitivity=WEIGHT_SENSITIVITY["low_speed"],
        launch_importance=0.46,
        braking_energy_demand=0.38,
        altitude_power_derate=0.00,
        notes=("Slow-corner traction and launch sensitivity dominate over straight-line power.",),
    ),
    "high_altitude": TrackDemandProfile(
        track_type="high_altitude",
        power_demand=0.46,
        ers_demand=0.34,
        drag_demand=0.30,
        traction_demand=0.16,
        mass_sensitivity=0.24,
        launch_importance=0.34,
        braking_energy_demand=0.34,
        altitude_power_derate=0.18,
        notes=("Thin air derates combustion and aero load; turbo and cooling claims need explicit source support.",),
    ),
}

TECHNICAL_FACTOR_PROFILES: dict[str, TechnicalFactorProfile] = {
    "power_unit": TechnicalFactorProfile(
        metric="power_unit",
        base_multiplier=0.18,
        track_sensitivity=POWER_TRACK_SENSITIVITY,
        default_track_sensitivity=0.22,
        qualifying_multiplier=1.15,
        mechanism="engine output and deployment-limited acceleration",
        demand_component="power_demand",
    ),
    "energy_recovery": TechnicalFactorProfile(
        metric="energy_recovery",
        base_multiplier=0.16,
        track_sensitivity=ENERGY_RECOVERY_SENSITIVITY,
        default_track_sensitivity=0.20,
        qualifying_multiplier=1.05,
        mechanism="ERS deployment, recovery efficiency, and clipping exposure",
        demand_component="ers_demand",
    ),
    "straight_line_speed": TechnicalFactorProfile(
        metric="straight_line_speed",
        base_multiplier=0.15,
        track_sensitivity=POWER_TRACK_SENSITIVITY,
        default_track_sensitivity=0.22,
        qualifying_multiplier=1.15,
        mechanism="long-straight speed and drag-limited acceleration",
        demand_component="power_demand",
    ),
    "drag_efficiency": TechnicalFactorProfile(
        metric="drag_efficiency",
        base_multiplier=0.14,
        track_sensitivity=DRAG_SENSITIVITY,
        default_track_sensitivity=0.20,
        qualifying_multiplier=1.05,
        mechanism="aero efficiency on high-speed and power-sensitive layouts",
        demand_component="drag_demand",
    ),
    "low_speed_traction": TechnicalFactorProfile(
        metric="low_speed_traction",
        base_multiplier=0.12,
        track_sensitivity=LOW_SPEED_SENSITIVITY,
        default_track_sensitivity=0.18,
        qualifying_multiplier=1.15,
        mechanism="launch, traction zones, and slow-corner exit performance",
        demand_component="traction_demand",
    ),
    "launch_performance": TechnicalFactorProfile(
        metric="launch_performance",
        base_multiplier=0.10,
        track_sensitivity={},
        default_track_sensitivity=0.28,
        qualifying_multiplier=0.55,
        mechanism="launch phase, clutch bite, initial deployment, and first-corner track position",
        demand_component="launch_importance",
    ),
    "weight": TechnicalFactorProfile(
        metric="weight",
        base_multiplier=0.16,
        track_sensitivity=WEIGHT_SENSITIVITY,
        default_track_sensitivity=0.24,
        qualifying_multiplier=1.05,
        mechanism="mass sensitivity through acceleration, braking, and tyre load",
        demand_component="mass_sensitivity",
    ),
    "upgrade_effect": TechnicalFactorProfile(
        metric="upgrade_effect",
        base_multiplier=0.55,
        track_sensitivity={},
        default_track_sensitivity=0.0,
        qualifying_multiplier=0.90,
        mechanism="broad validated package delta across race and qualifying pace",
        demand_component=None,
    ),
}


def track_demand_profile(
    track_type: str,
    feature_refs: Mapping[str, Any] | None = None,
) -> TrackDemandProfile:
    base = TRACK_DEMAND_PROFILES.get(
        track_type,
        TrackDemandProfile(
            track_type=track_type or "unknown",
            power_demand=0.22,
            ers_demand=0.20,
            drag_demand=0.20,
            traction_demand=0.18,
            mass_sensitivity=0.24,
            launch_importance=0.30,
            braking_energy_demand=0.30,
            altitude_power_derate=0.00,
            notes=("Unknown layout uses conservative default technical demand values.",),
        ),
    )
    if not feature_refs:
        return base
    return _event_adjusted_track_demand_profile(base, feature_refs)


def technical_factor_profile(metric: str) -> TechnicalFactorProfile | None:
    return TECHNICAL_FACTOR_PROFILES.get(metric)


def technical_context_multiplier(
    metric: str,
    track_type: str,
    mode: str = "race",
    feature_refs: Mapping[str, Any] | None = None,
) -> float:
    profile = technical_factor_profile(metric)
    if profile is None:
        return 1.0
    return profile.context_multiplier(track_type, mode, feature_refs)


def technical_context_reason(
    metric: str,
    track_type: str,
    mode: str = "race",
    feature_refs: Mapping[str, Any] | None = None,
) -> str | None:
    profile = technical_factor_profile(metric)
    if profile is None:
        return None
    return profile.context_reason(track_type, mode, feature_refs)


def technical_context_breakdown(
    metric: str,
    track_type: str,
    mode: str = "race",
    feature_refs: Mapping[str, Any] | None = None,
) -> dict[str, object] | None:
    profile = technical_factor_profile(metric)
    if profile is None:
        return None
    demand_profile = track_demand_profile(track_type, feature_refs)
    demand_value = profile.track_demand_value(track_type, feature_refs)
    return {
        "metric": metric,
        "track_type": track_type,
        "mode": mode,
        "base_multiplier": profile.base_multiplier,
        "demand_component": profile.demand_component,
        "demand_value": round(demand_value, 4),
        "qualifying_multiplier": profile.qualifying_multiplier,
        "context_multiplier": round(profile.context_multiplier(track_type, mode, feature_refs), 4),
        "mechanism": profile.mechanism,
        "track_demand_profile": demand_profile.to_dict(),
    }


def _event_adjusted_track_demand_profile(
    base: TrackDemandProfile,
    feature_refs: Mapping[str, Any],
) -> TrackDemandProfile:
    power_demand = base.power_demand
    ers_demand = base.ers_demand
    drag_demand = base.drag_demand
    traction_demand = base.traction_demand
    mass_sensitivity = base.mass_sensitivity
    launch_importance = base.launch_importance
    braking_energy_demand = base.braking_energy_demand
    altitude_power_derate = base.altitude_power_derate
    notes = list(base.notes)

    geometry_metrics = _geometry_metrics(feature_refs)
    if geometry_metrics:
        corners = _float_value(geometry_metrics.get("corner_count")) or 0.0
        high_angle_corners = _float_value(geometry_metrics.get("high_angle_corner_count")) or 0.0
        low_angle_corners = _float_value(geometry_metrics.get("low_angle_corner_count")) or 0.0
        avg_abs_angle = _float_value(geometry_metrics.get("avg_abs_corner_angle")) or 0.0
        total_abs_angle = _float_value(geometry_metrics.get("total_abs_corner_angle")) or 0.0
        corner_denominator = max(1.0, corners)
        high_angle_ratio = high_angle_corners / corner_denominator
        low_angle_ratio = low_angle_corners / corner_denominator
        high_angle_load = _clamp((high_angle_ratio - 0.22) * 0.18, -0.02, 0.07)
        low_angle_flow = _clamp((low_angle_ratio - 0.18) * 0.24, -0.03, 0.07)
        corner_density = _clamp((corners - 14.0) * 0.006, -0.02, 0.06)
        complexity = _clamp((total_abs_angle - 1500.0) / 12000.0, -0.03, 0.06)

        power_demand = _clamp(power_demand + low_angle_flow - max(0.0, complexity) * 0.20, 0.04, 0.68)
        ers_demand = _clamp(
            ers_demand + low_angle_flow * 0.35 + high_angle_load * 0.45 + max(0.0, complexity) * 0.20,
            0.04,
            0.56,
        )
        drag_demand = _clamp(drag_demand + low_angle_flow, 0.04, 0.58)
        traction_demand = _clamp(traction_demand + high_angle_load + corner_density, 0.04, 0.58)
        mass_sensitivity = _clamp(mass_sensitivity + corner_density + high_angle_load * 0.55, 0.08, 0.48)
        launch_importance = _clamp(launch_importance + max(0.0, high_angle_load) * 0.25 + corner_density * 0.30, 0.08, 0.62)
        braking_energy_demand = _clamp(braking_energy_demand + high_angle_load + max(0.0, complexity), 0.08, 0.58)
        notes.append(
            "event_geometry_adjusted=true "
            f"corners={corners:.0f} high_angle_ratio={high_angle_ratio:.2f} "
            f"low_angle_ratio={low_angle_ratio:.2f} avg_abs_angle={avg_abs_angle:.1f}"
        )

    elevation_m = _elevation_m(feature_refs)
    if elevation_m is not None:
        if elevation_m >= 650.0:
            altitude_delta = _clamp((elevation_m - 650.0) / 9000.0, 0.0, 0.20)
            altitude_power_derate = max(altitude_power_derate, altitude_delta)
            power_demand = _clamp(power_demand + altitude_delta * 0.25, 0.04, 0.68)
            ers_demand = _clamp(ers_demand + altitude_delta * 0.10, 0.04, 0.56)
            drag_demand = _clamp(drag_demand - altitude_delta * 0.08, 0.04, 0.58)
            notes.append(f"event_altitude_adjusted=true elevation_m={elevation_m:.0f}")
        elif elevation_m <= 250.0 and base.track_type in {"power", "high_speed"}:
            power_demand = _clamp(power_demand + 0.01, 0.04, 0.68)
            drag_demand = _clamp(drag_demand + 0.01, 0.04, 0.58)
            notes.append(f"low_altitude_air_density_adjusted=true elevation_m={elevation_m:.0f}")

    return TrackDemandProfile(
        track_type=base.track_type,
        power_demand=round(power_demand, 4),
        ers_demand=round(ers_demand, 4),
        drag_demand=round(drag_demand, 4),
        traction_demand=round(traction_demand, 4),
        mass_sensitivity=round(mass_sensitivity, 4),
        launch_importance=round(launch_importance, 4),
        braking_energy_demand=round(braking_energy_demand, 4),
        altitude_power_derate=round(altitude_power_derate, 4),
        notes=tuple(notes),
    )


def _geometry_metrics(feature_refs: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for candidate in (
        _nested_dict(feature_refs, ("circuit_profile", "geometry_metrics")),
        _nested_dict(feature_refs, ("event_input_provenance", "circuit_geometry", "geometry_metrics")),
        _nested_dict(feature_refs, ("event_input_provenance", "track_type", "geometry_metrics")),
    ):
        if candidate:
            return candidate
    return None


def _elevation_m(feature_refs: Mapping[str, Any]) -> float | None:
    candidates = (
        _nested_value(feature_refs, ("weather_profile", "elevation_m")),
        _nested_value(feature_refs, ("weather_profile", "elevation")),
        _nested_value(feature_refs, ("weather_profile", "geocoding_result", "elevation")),
        _nested_value(feature_refs, ("event_input_provenance", "weather_prior", "elevation_m")),
        _nested_value(feature_refs, ("event_input_provenance", "weather_prior", "elevation")),
    )
    for candidate in candidates:
        value = _float_value(candidate)
        if value is not None:
            if value < -500.0 or value > 3000.0:
                continue
            return value
    return None


def _nested_dict(root: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any] | None:
    value = _nested_value(root, path)
    return value if isinstance(value, Mapping) else None


def _nested_value(root: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = root
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))
