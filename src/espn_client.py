"""League connection and raw data fetches. Thin wrapper around espn_api."""

from __future__ import annotations

import os

from espn_api.football import League


def connect(league_id: int | None = None, year: int | None = None,
            espn_s2: str | None = None, swid: str | None = None) -> League:
    league_id = league_id or int(os.environ["LEAGUE_ID"])
    year = year or int(os.environ["SEASON_YEAR"])
    espn_s2 = espn_s2 or os.environ["ESPN_S2"]
    swid = swid or os.environ["SWID"]
    return League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)


def resolve_target_week(league: League, week: int | None = None) -> int:
    """Most recently completed week by default; explicit override for backfills."""
    if week is not None:
        return week
    return max(1, league.current_week - 1)


def is_last_regular_season_week(league: League, week: int) -> bool:
    return week == league.settings.reg_season_count


def get_box_scores(league: League, week: int) -> list:
    return league.box_scores(week=week)


def get_box_scores_through(league: League, week: int) -> dict[int, list]:
    """Box scores for every week 1..week, keyed by week — used for week-over-week deltas."""
    return {w: league.box_scores(week=w) for w in range(1, week + 1)}


def get_standings(league: League) -> list:
    return league.standings()


def get_power_rankings(league: League, week: int) -> list[tuple[str, object]]:
    """List of (score_str, Team), ESPN's algorithmic ranking, best first."""
    return league.power_rankings(week=week)
