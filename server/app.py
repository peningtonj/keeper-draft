from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
CACHE_PATH = os.path.join(CACHE_DIR, "players.json")
PLAYERS_PATH = os.path.join(os.path.dirname(__file__), "players.json")
YEARS_CACHE_PATH = os.path.join(CACHE_DIR, "years.json")
CACHE_LOCK = threading.Lock()
CACHE: dict[str, Any] = {"updatedAt": None, "year": None, "players": []}
YEARS_CACHE_LOCK = threading.Lock()
YEARS_CACHE: dict[str, dict[str, int | None]] = {}
DRAFTGURU_LOCK = threading.Lock()
DRAFTGURU_CACHE: dict[str, Any] = {"year": None, "data": {}}
STATSPACK_LOCK = threading.Lock()
STATSPACK_CACHE: dict[int, dict[str, Any]] = {}

app = FastAPI(title="Keeper League Draft API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_cache() -> None:
    if not os.path.exists(CACHE_PATH):
        return
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return
    with CACHE_LOCK:
        CACHE.update(payload)


def _save_cache(payload: dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _load_years_cache() -> None:
    if not os.path.exists(YEARS_CACHE_PATH):
        return
    try:
        with open(YEARS_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(payload, dict):
        with YEARS_CACHE_LOCK:
            YEARS_CACHE.update(payload)


def _save_years_cache(payload: dict[str, dict[str, int | None]]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(YEARS_CACHE_PATH, "w", encoding="utf-8") as handle:
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


def _get_years_playing(stats: Any) -> tuple[int | None, int | None, int | None]:
    if not stats or getattr(stats, "season_stats_total", None) is None:
        return None, None, None
    df = stats.season_stats_total
    if "Year" not in df.columns:
        return None, None, None
    years = [int(y) for y in df["Year"].dropna().unique().tolist() if str(y).isdigit()]
    if not years:
        return None, None, None
    return len(years), min(years), max(years)


def _fetch_draftguru_team_links(year: int) -> list[str]:
    url = f"https://www.draftguru.com.au/lists/{year}"
    html = requests.get(url, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    links = {
        link.get("href")
        for link in soup.find_all("a")
        if link.get("href", "").startswith(f"/lists/{year}/")
    }
    return sorted([f"https://www.draftguru.com.au{link}" for link in links])


def _parse_draftguru_team(url: str, season_year: int) -> dict[str, dict[str, int | None]]:
    html = requests.get(url, timeout=30).text
    frames = pd.read_html(html)
    if not frames:
        return {}
    df = frames[0]
    if "Player" not in df.columns or "Age" not in df.columns or "Drafted" not in df.columns:
        return {}

    results: dict[str, dict[str, int | None]] = {}
    for _, row in df.iterrows():
        name = str(row.get("Player", "")).strip()
        if not name or name == "nan":
            continue
        age_raw = str(row.get("Age", "")).strip()
        draft_raw = str(row.get("Drafted", "")).strip()
        games_total = row.get("Games Total")

        age_match = re.search(r"(\d+)", age_raw)
        age_years = int(age_match.group(1)) if age_match else None

        draft_match = re.search(r"(19\d{2}|20\d{2})", draft_raw)
        draft_year = int(draft_match.group(1)) if draft_match else None

        try:
            games_total_val = int(float(games_total)) if games_total is not None else None
        except (ValueError, TypeError):
            games_total_val = None

        if draft_year:
            years_playing = season_year - draft_year + 1
            first_year = draft_year
        else:
            years_playing = None
            first_year = None

        results[_normalize_player_key(name)] = {
            "yearsPlaying": years_playing,
            "firstYear": first_year,
            "ageYears": age_years,
        }
    return results


def _build_draftguru_index(season_year: int, refresh: bool) -> dict[str, dict[str, int | None]]:
    with DRAFTGURU_LOCK:
        if DRAFTGURU_CACHE.get("year") == season_year and DRAFTGURU_CACHE.get("data") and not refresh:
            return DRAFTGURU_CACHE["data"]

    data: dict[str, dict[str, int | None]] = {}
    for url in _fetch_draftguru_team_links(season_year):
        team_data = _parse_draftguru_team(url, season_year)
        data.update(team_data)

    with DRAFTGURU_LOCK:
        DRAFTGURU_CACHE["year"] = season_year
        DRAFTGURU_CACHE["data"] = data
    return data


def _load_supercoach_players() -> tuple[list[dict[str, Any]], int]:
    if not os.path.exists(PLAYERS_PATH):
        return [], datetime.now(timezone.utc).year
    with open(PLAYERS_PATH, "r", encoding="utf-8") as handle:
        raw_players = json.load(handle)

    players: list[dict[str, Any]] = []
    data_year = datetime.now(timezone.utc).year
    for raw in raw_players:
        if raw.get("player_stats"):
            updated_at = raw["player_stats"][0].get("updated_at")
            if updated_at:
                try:
                    data_year = datetime.fromisoformat(updated_at).year
                except ValueError:
                    pass
        first = str(raw.get("first_name", "")).strip()
        last = str(raw.get("last_name", "")).strip()
        name = f"{first} {last}".strip()
        team = (raw.get("team") or {}).get("name")
        positions_raw = raw.get("positions") or []
        positions = [pos.get("position") for pos in positions_raw if pos.get("position")]
        player_stats = raw.get("player_stats") or []
        latest_stats = player_stats[0] if player_stats else {}
        players.append(
            {
                "id": raw.get("id"),
                "name": name,
                "team": team,
                "positions": positions,
                "previousGames": raw.get("previous_games"),
                "previousAverage": raw.get("previous_average"),
                "previousTotal": raw.get("previous_total"),
                "price": latest_stats.get("price"),
                "status": raw.get("injury_suspension_status") or latest_stats.get("status"),
                "statusText": raw.get("injury_suspension_status_text"),
                "locked": raw.get("locked"),
                "active": raw.get("active"),
                "yearsPlaying": None,
                "firstYear": None,
                "ageYears": None,
            }
        )

    players.sort(key=lambda item: item.get("name") or "")
    return players, data_year


def _fetch_statspack(player_id: int, refresh: bool) -> dict[str, Any]:
    with STATSPACK_LOCK:
        cached = STATSPACK_CACHE.get(player_id)
        if cached and not refresh:
            return cached

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

    result = {
        "lastFiveSeasons": last_five,
        "lastFiveGames": total_games,
        "lastFiveAverage": round(total_points / total_games, 1) if total_games else None,
    }

    with STATSPACK_LOCK:
        STATSPACK_CACHE[player_id] = result
    return result


def _enrich_players_statspack(
    players: list[dict[str, Any]],
    refresh: bool,
    target_player_id: int | None = None,
) -> None:
    for player in players:
        player_id = player.get("id")
        if target_player_id is not None and player_id != target_player_id:
            continue
        if not isinstance(player_id, int):
            player.update({"lastFiveSeasons": [], "lastFiveGames": None, "lastFiveAverage": None})
            continue
        statspack = _fetch_statspack(player_id, refresh=refresh)
        if statspack:
            player.update(statspack)
        else:
            player.update({"lastFiveSeasons": [], "lastFiveGames": None, "lastFiveAverage": None})


def _enrich_players_years(players: list[dict[str, Any]], refresh: bool, season_year: int) -> None:
    draftguru_data = _build_draftguru_index(season_year, refresh=refresh)
    fallback_index: dict[str, list[dict[str, int | None]]] = {}
    for name_key, data in draftguru_data.items():
        parts = name_key.split()
        if not parts:
            continue
        last_name = parts[-1]
        first_initial = parts[0][0] if parts[0] else ""
        if not first_initial:
            continue
        fallback_key = f"{last_name}|{first_initial}"
        fallback_index.setdefault(fallback_key, []).append(data)

    updates: dict[str, dict[str, int | None]] = {}
    with YEARS_CACHE_LOCK:
        for player in players:
            key = _cache_key(player.get("name", ""), player.get("team"))
            cached = YEARS_CACHE.get(key)
            if cached and not refresh:
                has_value = any(
                    cached.get(field) is not None
                    for field in ("yearsPlaying", "firstYear", "ageYears")
                )
                if has_value:
                    player.update(
                        {
                            "yearsPlaying": cached.get("yearsPlaying"),
                            "firstYear": cached.get("firstYear"),
                            "ageYears": cached.get("ageYears"),
                        }
                    )
                    continue

            lookup_key = _normalize_player_key(player.get("name", ""))
            match = draftguru_data.get(lookup_key)
            if not match and lookup_key:
                parts = lookup_key.split()
                if parts:
                    last_name = parts[-1]
                    first_initial = parts[0][0] if parts[0] else ""
                    fallback_key = f"{last_name}|{first_initial}"
                    candidates = fallback_index.get(fallback_key, [])
                    if len(candidates) == 1:
                        match = candidates[0]
            if match:
                player.update(match)
                updates[key] = match
            else:
                player.update({"yearsPlaying": None, "firstYear": None, "ageYears": None})
                updates[key] = {"yearsPlaying": None, "firstYear": None, "ageYears": None}

        if updates:
            YEARS_CACHE.update(updates)
            _save_years_cache(YEARS_CACHE)


@app.on_event("startup")
def startup_event() -> None:
    _load_cache()
    _load_years_cache()


@app.get("/api/players")
def get_players(
    refresh: bool = Query(default=False),
    year: int | None = Query(default=None),
    enrich_years: bool = Query(default=False),
    enrich_stats: bool = Query(default=False),
    player_id: int | None = Query(default=None),
) -> dict[str, Any]:
    with CACHE_LOCK:
        cache_ready = CACHE["players"]
        if cache_ready and not refresh and not enrich_years:
            return CACHE

    players, target_year = _load_supercoach_players()
    if enrich_years:
        _enrich_players_years(players, refresh=refresh, season_year=target_year)
    if enrich_stats:
        _enrich_players_statspack(players, refresh=refresh, target_player_id=player_id)
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "year": target_year,
        "players": players,
        "count": len(players),
    }
    with CACHE_LOCK:
        CACHE.update(payload)
    _save_cache(payload)
    return payload
