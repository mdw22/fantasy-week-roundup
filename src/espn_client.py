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


def get_recent_activity(league: League, since=None, page_size: int = 100) -> list:
    """League transactions, newest first. Pages back until the oldest one fetched is at or before
    `since` (a timezone-aware datetime), or the feed runs out; with `since` None, the first page."""
    activity, offset = [], 0
    while True:
        page = league.recent_activity(size=page_size, offset=offset)
        activity.extend(page)
        if len(page) < page_size or since is None:
            return activity
        if page[-1].date / 1000 <= since.timestamp():
            return activity
        offset += page_size


def get_free_agents(league: League, week: int, position: str, size: int = 50) -> list:
    """Free agents at `position` with `week`'s projections. ESPN orders these by % rostered, not
    projection -- callers sort."""
    return league.free_agents(week=week, size=size, position=position)


def get_player_info(league: League, player_ids: list[int]) -> list:
    """Player cards (with per-week stats) for the given ESPN IDs, in one request."""
    if not player_ids:
        return []
    found = league.player_info(playerId=list(player_ids))
    if found is None:
        return []
    return found if isinstance(found, list) else [found]
