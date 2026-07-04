"""Shared market outcome identifiers used by simulators and normalizers."""

from __future__ import annotations


WINNER = "winner"
CONSTRUCTOR_DOUBLE_PODIUM = "constructor_double_podium"
DRIVER_H2H = "driver_h2h"

SUPPORTED_MARKET_TYPES = (WINNER, CONSTRUCTOR_DOUBLE_PODIUM, DRIVER_H2H)


def driver_h2h_outcome_id(driver_id: str, opponent_id: str) -> str:
    """Return the canonical outcome id for driver_id finishing ahead of opponent_id."""

    return f"{driver_id}_ahead_of_{opponent_id}"


def parse_driver_h2h_outcome_id(outcome_id: str) -> tuple[str, str] | None:
    marker = "_ahead_of_"
    if marker not in outcome_id:
        return None
    driver_id, opponent_id = outcome_id.split(marker, maxsplit=1)
    if not driver_id or not opponent_id or driver_id == opponent_id:
        return None
    return driver_id, opponent_id
