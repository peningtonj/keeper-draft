from __future__ import annotations

import csv
import json
import os
import re
from difflib import get_close_matches
from collections import defaultdict
from typing import Any

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
CSV_PATH = os.path.join(ROOT_DIR, "ITDFL LEAGUE - PLAYERS.csv")
YEARS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "years.json")
PLAYERS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "players.json")

TEAM_ABBREV_MAP = {
    "ADE": "Adelaide",
    "BRL": "Brisbane",
    "CAR": "Carlton",
    "COL": "Collingwood",
    "ESS": "Essendon",
    "FRE": "Fremantle",
    "GCS": "Gold Coast",
    "GEE": "Geelong",
    "GWS": "GWS Giants",
    "HAW": "Hawthorn",
    "MEL": "Melbourne",
    "NTH": "North Melbourne",
    "PTA": "Port Adelaide",
    "RIC": "Richmond",
    "STK": "St Kilda",
    "SYD": "Sydney",
    "WBD": "Western Bulldogs",
    "WCE": "West Coast",
}


def _normalize_player_key(name: str) -> str:
    cleaned = (
        name.replace("’", "'")
        .replace(".", " ")
        .replace("-", " ")
        .replace("\xa0", " ")
    )
    normalized = " ".join(cleaned.lower().split()).strip()
    normalized = re.sub(r"\b(jr|junior)\b", "", normalized).strip()
    normalized = " ".join(normalized.split())
    return normalized


def _cache_key(name: str, team: str | None) -> str:
    return f"{_normalize_player_key(name)}|{(team or '').lower()}"


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_name_to_team() -> dict[str, str]:
    if not os.path.exists(PLAYERS_CACHE_PATH):
        return {}
    payload = _load_json(PLAYERS_CACHE_PATH)
    players = payload.get("players", []) if isinstance(payload, dict) else payload
    name_to_team: dict[str, str] = {}
    for player in players:
        name = str(player.get("name", "")).strip()
        team = str(player.get("team", "")).strip()
        if name and team and name.lower() not in name_to_team:
            name_to_team[name.lower()] = team
    return name_to_team


def _build_years_index(years_cache: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, payload in years_cache.items():
        name_key = key.split("|", 1)[0]
        index[name_key].append(payload)
    return index


def _build_name_pool(years_cache: dict[str, dict[str, Any]]) -> list[str]:
    return [key.split("|", 1)[0] for key in years_cache]


def _last_name(name: str) -> str:
    parts = name.split()
    return parts[-1] if parts else ""


def _fuzzy_match_year(
    normalized: str,
    name_pool: list[str],
    years_cache: dict[str, dict[str, Any]],
    team_full: str | None,
) -> int | None:
    if not normalized:
        return None

    last_name = _last_name(normalized)
    if not last_name:
        return None

    candidates = [name for name in name_pool if _last_name(name) == last_name]
    if not candidates:
        candidates = name_pool

    matches = get_close_matches(normalized, candidates, n=3, cutoff=0.92)
    if not matches:
        matches = get_close_matches(normalized, candidates, n=1, cutoff=0.88)

    for match in matches:
        if team_full:
            key = _cache_key(match, team_full)
            payload = years_cache.get(key)
            if payload and payload.get("firstYear") is not None:
                return payload.get("firstYear")
        # Fallback to any team for this name
        for key, payload in years_cache.items():
            name_key = key.split("|", 1)[0]
            if name_key == match and payload.get("firstYear") is not None:
                return payload.get("firstYear")
    return None


def _resolve_payload(
    name: str,
    team_full: str | None,
    years_cache: dict[str, dict[str, Any]],
    years_index: dict[str, list[dict[str, Any]]],
    name_pool: list[str],
) -> dict[str, Any] | None:
    if not name:
        return None

    if team_full:
        key = _cache_key(name, team_full)
        match = years_cache.get(key)
        if match:
            return match

    normalized = _normalize_player_key(name)
    candidates = years_index.get(normalized, [])
    if len(candidates) == 1:
        return candidates[0]

    fuzzy_year = _fuzzy_match_year(normalized, name_pool, years_cache, team_full)
    if fuzzy_year is None:
        return None

    if team_full:
        for key, payload in years_cache.items():
            name_key = key.split("|", 1)[0]
            team_key = key.split("|", 1)[1] if "|" in key else ""
            if name_key == normalized and team_key == team_full.lower():
                return payload

    for key, payload in years_cache.items():
        name_key = key.split("|", 1)[0]
        if name_key == normalized and payload.get("firstYear") == fuzzy_year:
            return payload

    return None


def main() -> None:
    if not os.path.exists(CSV_PATH):
        raise SystemExit(f"CSV file not found: {CSV_PATH}")
    if not os.path.exists(YEARS_CACHE_PATH):
        raise SystemExit(f"Years cache not found: {YEARS_CACHE_PATH}")

    years_cache = _load_json(YEARS_CACHE_PATH)
    name_to_team = _build_name_to_team()
    years_index = _build_years_index(years_cache)
    name_pool = _build_name_pool(years_cache)

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        if "Draft Year" not in fieldnames:
            fieldnames.append("Draft Year")
        if "30+" not in fieldnames:
            fieldnames.append("30+")
        rows = list(reader)

    for row in rows:
        name = (row.get("Player Name") or "").strip()
        team_abbrev = (row.get("Team") or "").strip()
        team_full = name_to_team.get(name.lower()) or TEAM_ABBREV_MAP.get(team_abbrev, "")
        payload = _resolve_payload(name, team_full, years_cache, years_index, name_pool)
        draft_year = payload.get("firstYear") if payload else None
        age_years = payload.get("ageYears") if payload else None

        row["Draft Year"] = "" if draft_year is None else str(draft_year)
        row["30+"] = "Yes" if isinstance(age_years, int) and age_years >= 30 else "No"

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
