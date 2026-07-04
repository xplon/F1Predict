"""Seed-data loader for the first MVP."""

from __future__ import annotations

import json
from pathlib import Path

from f1predict.domain import Driver, MarketSnapshot, RaceEvent, SeasonState, Team


DEFAULT_SEED_PATH = Path("data/seed/demo_season.json")


class SeedDataSource:
    """Loads deterministic seed data for local development and smoke tests."""

    def __init__(self, path: Path | str = DEFAULT_SEED_PATH) -> None:
        self.path = Path(path)

    def load(self) -> SeasonState:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        teams = {item["team_id"]: Team(**item) for item in raw["teams"]}
        drivers = {item["driver_id"]: Driver(**item) for item in raw["drivers"]}
        events = [RaceEvent(**item) for item in raw["events"]]
        markets = [MarketSnapshot(**item) for item in raw["markets"]]
        return SeasonState(
            season=int(raw["season"]),
            teams=teams,
            drivers=drivers,
            events=events,
            markets=markets,
        )
