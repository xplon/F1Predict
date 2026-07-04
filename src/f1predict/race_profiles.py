"""F1 official race profile loading for scheduled event inputs."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.results import normalize_event_name


@dataclass(frozen=True)
class RaceProfile:
    event_key: str | None
    slug: str | None
    title: str | None
    planned_laps: int | None
    source_url: str | None
    source_path: str
    captured_at: str | None

    def laps_provenance(self) -> dict[str, Any]:
        return {
            "source": "f1_official_race_profile",
            "source_url": self.source_url,
            "path": self.source_path,
            "captured_at": self.captured_at,
            "slug": self.slug,
            "title": self.title,
            "quality": "verified",
        }


class F1OfficialRaceProfileProvider:
    """Reads stored Formula1.com race profile snapshots."""

    def __init__(self, raw_root: Path | str = Path("data/raw")) -> None:
        self.raw_root = Path(raw_root)
        self._profiles: list[RaceProfile] | None = None

    def load_for_calendar_item(self, item: dict[str, Any]) -> RaceProfile | None:
        profiles = self._load_profiles()
        primary_lookups = self._lookups(item, ("event_name", "official_name"))
        match = self._first_profile_match(profiles, primary_lookups)
        if match:
            return match

        place_lookups = self._lookups(item, ("circuit_short_name", "location"))
        match = self._first_profile_match(profiles, place_lookups)
        if match:
            return match

        country_matches = self._matching_profiles(profiles, self._lookups(item, ("country_name",)))
        if len(country_matches) == 1:
            return country_matches[0]
        return None

    @staticmethod
    def _lookups(item: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
        values = [normalize_event_name(str(item.get(field) or "")) for field in fields]
        return [value for value in values if value]

    @classmethod
    def _first_profile_match(cls, profiles: list[RaceProfile], lookups: list[str]) -> RaceProfile | None:
        matches = cls._matching_profiles(profiles, lookups)
        return matches[0] if matches else None

    @classmethod
    def _matching_profiles(cls, profiles: list[RaceProfile], lookups: list[str]) -> list[RaceProfile]:
        scored_matches = []
        for index, profile in enumerate(profiles):
            keys = cls._profile_keys(profile)
            score = max(
                (cls._match_score(lookup, key) for lookup in lookups for key in keys),
                default=0,
            )
            if score:
                scored_matches.append((score, index, profile))
        return [profile for _, _, profile in sorted(scored_matches, key=lambda item: (-item[0], item[1]))]

    def _load_profiles(self) -> list[RaceProfile]:
        if self._profiles is not None:
            return self._profiles
        root = self.raw_root / "f1_official_race_profiles"
        files = []
        if root.exists():
            files = [path for path in root.rglob("*.json") if not path.name.endswith(".meta.json")]
        profiles = []
        for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
            profile = self._load_file(path)
            if profile is not None and profile.planned_laps is not None:
                profiles.append(profile)
        self._profiles = profiles
        return profiles

    def _load_file(self, path: Path) -> RaceProfile | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        page_html = str(raw.get("html") or "")
        title = self._title(page_html)
        event_key = self._event_key(title)
        planned_laps = self._planned_laps(page_html)
        meta = self._meta(path)
        params = meta.get("params", {}) if isinstance(meta.get("params"), dict) else {}
        return RaceProfile(
            event_key=event_key,
            slug=self._string_value(raw.get("slug") or params.get("slug")),
            title=title,
            planned_laps=planned_laps,
            source_url=self._string_value(raw.get("url") or params.get("url")),
            source_path=str(path),
            captured_at=self._string_value(meta.get("captured_at")),
        )

    @staticmethod
    def _profile_keys(profile: RaceProfile) -> set[str]:
        keys = {
            profile.event_key,
            normalize_event_name(str(profile.slug or "")),
            normalize_event_name(str(profile.title or "")),
        }
        if profile.slug:
            keys.update(normalize_event_name(part) for part in profile.slug.split("-"))
        return {key for key in keys if key}

    @staticmethod
    def _matches(lookup: str, key: str) -> bool:
        return F1OfficialRaceProfileProvider._match_score(lookup, key) > 0

    @staticmethod
    def _match_score(lookup: str, key: str) -> int:
        if lookup == key:
            return 100
        if len(lookup) >= 5 and lookup in key:
            return 80 if key.startswith(lookup) else 60
        if len(key) >= 5 and lookup.startswith(key):
            return 70
        return 0

    @staticmethod
    def _planned_laps(page_html: str) -> int | None:
        patterns = [
            r"Number of Laps</dt><dd[^>]*>(\d+)</dd>",
            r'Number of Laps\\"}.*?\\"children\\":\\"(\d+)\\"',
        ]
        for pattern in patterns:
            match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _title(page_html: str) -> str | None:
        match = re.search(r"<title>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())

    @staticmethod
    def _event_key(title: str | None) -> str | None:
        if not title:
            return None
        cleaned = re.sub(r"\b20\d{2}\b.*$", "", title)
        cleaned = cleaned.replace("- F1 Race", "")
        return normalize_event_name(cleaned)

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
