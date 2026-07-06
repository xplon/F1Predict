"""Guard against entity-specific prediction patches.

This is a lightweight contract test for the project principle that user
examples are bug reports, not labels. Prediction-update code may use sourced
features, standings, timing data, and archived source-backed evidence, but it
must not contain driver/team-specific branches that force a desired ranking.
Seed records may exist as plumbing fixtures, but they must be flagged as
diagnostic and must not be treated as production evidence.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PREDICTION_UPDATE_FILES = (
    ROOT / "src" / "f1predict" / "belief_state.py",
    ROOT / "src" / "f1predict" / "models" / "pace.py",
    ROOT / "src" / "f1predict" / "pipeline.py",
    ROOT / "src" / "f1predict" / "models" / "simulator.py",
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


def main() -> None:
    violations: list[str] = []
    for path in PREDICTION_UPDATE_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for token in ENTITY_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(ROOT)} contains entity token {token!r}")
    if violations:
        details = "\n".join(f"- {item}" for item in violations)
        raise AssertionError(
            "Prediction-update code must be source-driven, not entity-specific.\n"
            "Move entity facts into sourced data/evidence, or justify and narrow the scanner.\n"
            f"{details}"
        )
    print("source-driven contract ok")


if __name__ == "__main__":
    main()
