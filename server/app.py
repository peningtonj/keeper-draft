from __future__ import annotations

import csv
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

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
CACHE_PATH = os.path.join(CACHE_DIR, "players.json")
PLAYERS_DATA_PATH = os.path.join(CACHE_DIR, "players_data.json")
PLAYERS_PATH = os.path.join(ROOT_DIR, "players.json")
YEARS_CACHE_PATH = os.path.join(CACHE_DIR, "years.json")
DRAFT_PATH = os.path.join(CACHE_DIR, "DRAFT.csv")
MSD_PATH = os.path.join(CACHE_DIR, "MSD.csv")
CSV_CANDIDATES = [
    os.path.join(ROOT_DIR, "ITDFL LEAGUE - PLAYERS (1).csv"),
    os.path.join(ROOT_DIR, "ITDFL LEAGUE - PLAYERS.csv"),
]
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


def _load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _load_raw_supercoach_source() -> list[dict[str, Any]]:
    for path in (PLAYERS_DATA_PATH, PLAYERS_PATH, CACHE_PATH):
        if not os.path.exists(path):
            continue
        try:
            payload = _load_json_file(path)
        except (OSError, json.JSONDecodeError):
            continue

        raw_players: list[dict[str, Any]] | None = None
        if isinstance(payload, list):
            raw_players = payload
        elif isinstance(payload, dict) and isinstance(payload.get("players"), list):
            candidate_players = payload["players"]
            if candidate_players and isinstance(candidate_players[0], dict):
                sample = candidate_players[0]
                if "first_name" in sample or "last_name" in sample:
                    raw_players = candidate_players

        if raw_players is not None:
            return raw_players

    return []


def _find_keeper_csv_path() -> str | None:
    for path in CSV_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _build_draft_csv_lookup() -> tuple[dict[str, dict[str, str]], list[str]]:
    if not os.path.exists(DRAFT_PATH):
        return {}, []

    drafted_lookup: dict[str, dict[str, str]] = {}
    team_names: list[str] = []
    seen_teams: set[str] = set()

    with open(DRAFT_PATH, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            team_name = str(row.get("TEAM") or "").strip()
            player_name = str(row.get("PLAYER") or "").strip()
            pick = str(row.get("PICK") or "").strip()
            if not team_name or not player_name:
                continue

            if team_name not in seen_teams:
                seen_teams.add(team_name)
                team_names.append(team_name)

            drafted_lookup[_normalize_player_key(player_name)] = {
                "team": team_name,
                "pick": pick,
            }

    return drafted_lookup, team_names


def _build_drafted_lookup_from_csv() -> dict[str, str]:
    csv_path = _find_keeper_csv_path()
    if not csv_path:
        return {}

    drafted_lookup: dict[str, str] = {}
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            pick = str(row.get("Pick") or "").strip()
            if not pick:
                continue

            name = str(row.get("Player Name") or "").strip()
            team_abbrev = str(row.get("Team") or "").strip().upper()
            team_name = TEAM_ABBREV_MAP.get(team_abbrev)
            if not name or not team_name:
                continue

            drafted_lookup[_cache_key(name, team_name)] = pick

    return drafted_lookup


def _apply_csv_draft_status(players: list[dict[str, Any]]) -> None:
    drafted_lookup = _build_drafted_lookup_from_csv()
    for player in players:
        pick = drafted_lookup.get(_cache_key(player.get("name", ""), player.get("team")))
        player["draftStatus"] = "unavailable" if pick else None
        player["draftPick"] = pick if pick else None


def _apply_draft_csv_assignments(players: list[dict[str, Any]]) -> list[str]:
    drafted_lookup, team_names = _build_draft_csv_lookup()
    for player in players:
        draft_entry = drafted_lookup.get(_normalize_player_key(player.get("name", "")))
        player["draftedByTeam"] = draft_entry.get("team") if draft_entry else None
        player["draftedByPick"] = draft_entry.get("pick") if draft_entry else None
    return team_names


def _apply_msd_csv_changes(players: list[dict[str, Any]], team_names: list[str]) -> list[str]:
    if not os.path.exists(MSD_PATH):
        return team_names

    player_lookup = {
        _normalize_player_key(str(player.get("name", ""))): player
        for player in players
        if player.get("name")
    }
    next_team_names = list(team_names)

    with open(MSD_PATH, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            team_name = str(row.get("Team") or "").strip()
            dropped_name = str(row.get("Player Dropped") or "").strip()
            drafted_name = str(row.get("Player Drafted") or "").strip()
            pick = str(row.get("Pick") or "").strip()

            if team_name and team_name not in next_team_names:
                next_team_names.append(team_name)

            dropped_player = player_lookup.get(_normalize_player_key(dropped_name))
            if dropped_player is not None:
                dropped_player["draftStatus"] = None
                dropped_player["draftPick"] = None
                dropped_player["draftedByTeam"] = None
                dropped_player["draftedByPick"] = None

            drafted_player = player_lookup.get(_normalize_player_key(drafted_name))
            if drafted_player is not None:
                drafted_player["draftStatus"] = "unavailable"
                drafted_player["draftPick"] = f"MSD {pick}" if pick else "MSD"
                drafted_player["draftedByTeam"] = team_name or None
                drafted_player["draftedByPick"] = pick or None

    return next_team_names


def _load_supercoach_players() -> tuple[list[dict[str, Any]], int, list[str]]:
    raw_players = _load_raw_supercoach_source()
    if not raw_players:
        return [], datetime.now(timezone.utc).year, []

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
                "currentGames": latest_stats.get("total_games"),
                "currentAverage": latest_stats.get("avg"),
                "currentTotal": latest_stats.get("total_points"),
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
                "draftStatus": None,
                "draftPick": None,
                "draftedByTeam": None,
                "draftedByPick": None,
            }
        )

    _apply_csv_draft_status(players)
    draft_teams = _apply_draft_csv_assignments(players)
    draft_teams = _apply_msd_csv_changes(players, draft_teams)
    players.sort(key=lambda item: item.get("name") or "")
    return players, data_year, draft_teams


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

    players, target_year, draft_teams = _load_supercoach_players()
    if enrich_years:
        _enrich_players_years(players, refresh=refresh, season_year=target_year)
    if enrich_stats:
        _enrich_players_statspack(players, refresh=refresh, target_player_id=player_id)
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "year": target_year,
        "players": players,
        "draftTeams": draft_teams,
        "count": len(players),
    }
    with CACHE_LOCK:
        CACHE.update(payload)
    _save_cache(payload)
    return payload
