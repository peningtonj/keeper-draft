from __future__ import annotations

import json
import os
from typing import Any

import re
import requests

CACHE_PATH = os.path.join(os.path.dirname(__file__), "cache", "players.json")
TOP_N = 400
REFRESH = True


def _load_cache() -> dict[str, Any]:
    if not os.path.exists(CACHE_PATH):
        raise FileNotFoundError(f"Cache not found: {CACHE_PATH}")
    with open(CACHE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_cache(payload: dict[str, Any]) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


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


def _load_years_cache() -> dict[str, dict[str, int | None]]:
    path = os.path.join(os.path.dirname(__file__), "cache", "years.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _fetch_statspack(player_id: int, refresh: bool) -> dict[str, Any]:
    url = (
        "https://www.supercoach.com.au/2026/api/afl/classic/v1/completeStatspack"
        f"?player_id={player_id}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.supercoach.com.au/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}

    stats = payload.get("playerStats") or []
    season_totals: dict[int, dict[str, int]] = {}
    for entry in stats:
        season_raw = entry.get("season")
        if not season_raw:
            continue
        try:
            season = int(season_raw)
        except (TypeError, ValueError):
            continue
        played = entry.get("played")
        points = entry.get("points")
        if played not in (1, True):
            continue
        if points is None:
            continue
        season_data = season_totals.setdefault(season, {"games": 0, "points": 0})
        season_data["games"] += 1
        season_data["points"] += int(points)

    seasons_sorted = sorted(season_totals.keys(), reverse=True)
    last_five = []
    total_games = 0
    total_points = 0
    for season in seasons_sorted[:5]:
        games = season_totals[season]["games"]
        points = season_totals[season]["points"]
        avg = round(points / games, 1) if games else None
        last_five.append({"season": season, "games": games, "average": avg})
        total_games += games
        total_points += points

    return {
        "lastFiveSeasons": last_five,
        "lastFiveGames": total_games,
        "lastFiveAverage": round(total_points / total_games, 1) if total_games else None,
    }


def main() -> None:
    payload = _load_cache()
    players: list[dict[str, Any]] = payload.get("players") or []
    years_cache = _load_years_cache()
    priced = [p for p in players if isinstance(p.get("price"), (int, float))]
    priced.sort(key=lambda p: p.get("price") or 0, reverse=True)
    target = priced[:TOP_N]
    target_ids = {p.get("id") for p in target if isinstance(p.get("id"), int)}

    updated = 0
    for player in players:
        key = _cache_key(player.get("name", ""), player.get("team"))
        cached_years = years_cache.get(key)
        if cached_years:
            player.update(
                {
                    "yearsPlaying": cached_years.get("yearsPlaying"),
                    "firstYear": cached_years.get("firstYear"),
                    "ageYears": cached_years.get("ageYears"),
                }
            )

        player_id = player.get("id")
        if player_id not in target_ids:
            continue
        statspack = _fetch_statspack(player_id, refresh=REFRESH)
        if statspack:
            player.update(statspack)
            updated += 1

    payload["players"] = players
    _save_cache(payload)
    print(f"Updated {updated} players with last five seasons stats.")


if __name__ == "__main__":
    main()
