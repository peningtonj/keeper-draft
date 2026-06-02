from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from difflib import get_close_matches
from typing import Any

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DEFAULT_CSV_CANDIDATES = [
    os.path.join(ROOT_DIR, "ITDFL LEAGUE - PLAYERS (1).csv"),
    os.path.join(ROOT_DIR, "ITDFL LEAGUE - PLAYERS.csv"),
]
PLAYERS_PATH = os.path.join(ROOT_DIR, "players.json")

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

NEW_COLUMNS = [
    "2026 Total Games",
    "2026 Points",
    "2026 Last 3 Games",
    "2026 Average",
]


def _normalize_player_key(name: str) -> str:
    cleaned = (
        name.replace("’", "'")
        .replace(".", " ")
        .replace("-", " ")
        .replace("\xa0", " ")
    )
    normalized = " ".join(cleaned.lower().split()).strip()
    normalized = re.sub(r"\b(jr|junior)\b", "", normalized).strip()
    return " ".join(normalized.split())


def _loose_player_key(name: str) -> str:
    parts = _normalize_player_key(name).split()
    if len(parts) <= 2:
        return " ".join(parts)
    filtered = [parts[0], *[part for part in parts[1:-1] if len(part) > 1], parts[-1]]
    return " ".join(filtered)


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _format_price(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return str(int(round(value)))


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return str(value)


def _default_csv_path() -> str:
    for path in DEFAULT_CSV_CANDIDATES:
        if os.path.exists(path):
            return path
    return DEFAULT_CSV_CANDIDATES[0]


def _build_player_indexes(raw_players: list[dict[str, Any]]) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    by_name_team: dict[tuple[str, str], dict[str, Any]] = {}
    by_loose_team: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_loose: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for player in raw_players:
        first = str(player.get("first_name", "")).strip()
        last = str(player.get("last_name", "")).strip()
        name = f"{first} {last}".strip()
        if not name:
            continue

        team = player.get("team") or {}
        team_abbrev = str(team.get("abbrev", "")).upper().strip()
        normalized = _normalize_player_key(name)
        loose = _loose_player_key(name)

        record = {
            "name": name,
            "normalized": normalized,
            "loose": loose,
            "teamAbbrev": team_abbrev,
            "teamName": str(team.get("name", "")).strip(),
            "positions": [
                pos.get("position") for pos in (player.get("positions") or []) if pos.get("position")
            ],
            "latestStats": (player.get("player_stats") or [{}])[0],
        }

        by_name_team[(normalized, team_abbrev)] = record
        by_loose_team[(loose, team_abbrev)] = record
        by_name[normalized].append(record)
        by_loose[loose].append(record)

    return by_name_team, by_loose_team, by_name, by_loose


def _resolve_player(
    name: str,
    team_abbrev: str,
    by_name_team: dict[tuple[str, str], dict[str, Any]],
    by_loose_team: dict[tuple[str, str], dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
    by_loose: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    normalized = _normalize_player_key(name)
    loose = _loose_player_key(name)
    team_abbrev = team_abbrev.upper().strip()

    for key in ((normalized, team_abbrev), (loose, team_abbrev)):
        match = by_name_team.get(key) if key[0] == normalized else by_loose_team.get(key)
        if match:
            return match

    exact_candidates = by_name.get(normalized, [])
    if len(exact_candidates) == 1:
        return exact_candidates[0]

    loose_candidates = by_loose.get(loose, [])
    if len(loose_candidates) == 1:
        return loose_candidates[0]

    team_name = TEAM_ABBREV_MAP.get(team_abbrev, "")
    if team_name:
        for candidate in exact_candidates or loose_candidates:
            if candidate.get("teamName") == team_name:
                return candidate

    candidate_pool = list({candidate["normalized"]: candidate for candidate in exact_candidates + loose_candidates}.values())
    if not candidate_pool:
        return None

    normalized_pool = [candidate["normalized"] for candidate in candidate_pool]
    matches = get_close_matches(normalized, normalized_pool, n=3, cutoff=0.92)
    if not matches:
        matches = get_close_matches(loose, normalized_pool, n=1, cutoff=0.88)

    for match_name in matches:
        for candidate in candidate_pool:
            if candidate["normalized"] != match_name:
                continue
            if not team_name or candidate.get("teamName") == team_name:
                return candidate

    return None


def _insert_new_columns(fieldnames: list[str]) -> list[str]:
    remaining = [name for name in fieldnames if name not in NEW_COLUMNS]
    if "Price" not in remaining:
        return remaining + NEW_COLUMNS

    insert_at = remaining.index("Price") + 1
    return remaining[:insert_at] + NEW_COLUMNS + remaining[insert_at:]


def update_csv(csv_path: str, players_path: str) -> tuple[int, list[str]]:
    raw_players = _load_json(players_path)
    indexes = _build_player_indexes(raw_players)

    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = _insert_new_columns(list(reader.fieldnames or []))
        rows = list(reader)

    updated = 0
    unmatched: list[str] = []

    for row in rows:
        name = (row.get("Player Name") or "").strip()
        team_abbrev = (row.get("Team") or "").strip()
        match = _resolve_player(name, team_abbrev, *indexes)
        if not match:
            unmatched.append(f"{name} [{team_abbrev}]")
            continue

        latest_stats = match.get("latestStats") or {}
        positions = [position for position in match.get("positions") or [] if position]
        current_dpp = (row.get("DPP OPTIONS") or "").strip().upper()
        position_text = "/".join(positions)

        if positions:
            row["Position"] = position_text
            row["DPP OPTIONS"] = current_dpp if current_dpp in positions else positions[0]

        price = latest_stats.get("price")
        if price is not None:
            row["Price"] = _format_price(price)

        row["2026 Total Games"] = _format_value(latest_stats.get("total_games"))
        row["2026 Points"] = _format_value(latest_stats.get("total_points"))
        row["2026 Last 3 Games"] = _format_value(latest_stats.get("avg3"))
        row["2026 Average"] = _format_value(latest_stats.get("avg"))
        updated += 1

    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return updated, unmatched


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update the keeper CSV with live 2026 stats, positions, DPP, and price from players.json."
    )
    parser.add_argument("csv_path", nargs="?", default=_default_csv_path())
    parser.add_argument("--players", dest="players_path", default=PLAYERS_PATH)
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        raise SystemExit(f"CSV file not found: {args.csv_path}")
    if not os.path.exists(args.players_path):
        raise SystemExit(f"Players JSON not found: {args.players_path}")

    updated, unmatched = update_csv(args.csv_path, args.players_path)
    print(f"Updated {updated} rows in {args.csv_path}")
    if unmatched:
        print(f"Unmatched rows left unchanged: {len(unmatched)}")
        for entry in unmatched:
            print(f" - {entry}")


if __name__ == "__main__":
    main()