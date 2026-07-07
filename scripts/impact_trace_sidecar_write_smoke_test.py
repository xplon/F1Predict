"""Smoke test for Windows-safe prediction impact sidecar artifact names."""

from __future__ import annotations

from tempfile import TemporaryDirectory

from f1predict.impact_trace_sidecar import PredictionImpactTraceSidecarStore


def main() -> None:
    sidecar = {
        "sidecar_id": (
            "british_gp_british_gp_20260705T000000_0000_2026_a5f145fbb3a0_"
            "20260707T115527_0000_bb41906fe9"
        ),
        "event_id": "british_gp",
        "generated_at": "2026-07-07T11:55:27+00:00",
        "trace_fingerprint": "bb41906fe9975b4fd00cfdc9787a128d06aa5c3d839a00651688ea05b42dcb5b",
        "source_run": {
            "run_id": "british_gp_20260705T000000_0000_20260707T104824_0000_48a450406e"
        },
    }
    with TemporaryDirectory() as tmp:
        path = PredictionImpactTraceSidecarStore().write(sidecar, output_root=tmp)
        assert path.exists()
        assert len(path.name) < 96
        assert "bb41906fe9" in path.name


if __name__ == "__main__":
    main()
