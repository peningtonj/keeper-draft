from __future__ import annotations

from app import _load_years_cache, get_players


def main() -> None:
    _load_years_cache()
    get_players(refresh=True, enrich_years=True)


if __name__ == "__main__":
    main()
