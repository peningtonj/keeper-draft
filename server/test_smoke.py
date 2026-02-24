from __future__ import annotations

import os
import sys
import tempfile
import shutil
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)

import server.app as draft


def test_cache_roundtrip() -> None:
    temp_dir = tempfile.mkdtemp(prefix="keeper-cache-")
    try:
        draft.CACHE_DIR = temp_dir
        draft.CACHE_PATH = os.path.join(temp_dir, "players.json")
        payload = {
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "year": 2024,
            "players": [{"name": "Test Player", "position": "MID", "yearsPlaying": 3}],
            "count": 1,
        }
        draft._save_cache(payload)
        draft.CACHE = {"updatedAt": None, "year": None, "players": []}
        draft._load_cache()
        assert draft.CACHE.get("year") == 2024
        assert len(draft.CACHE.get("players", [])) == 1
        print("Cache roundtrip: OK")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_supercoach_list_load() -> None:
    players, data_year = draft._load_supercoach_players()
    assert players
    sample = players[0]
    assert sample.get("name")
    print(f"Supercoach list: OK ({len(players)} players, year {data_year})")


def test_age_enrichment_sample() -> None:
    index = draft._build_draftguru_index(2025, refresh=True)
    sample = index.get(draft._normalize_player_key("Harry Sheezel"))
    assert sample and sample.get("ageYears") is not None
    print(
        "DraftGuru enrichment: OK "
        f"(years={sample.get('yearsPlaying')}, age={sample.get('ageYears')})"
    )


def main() -> None:
    test_cache_roundtrip()
    test_supercoach_list_load()
    test_age_enrichment_sample()
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()
