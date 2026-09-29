"""Waiver Report Card (moves made during the week just played, graded by how those players scored)
and Suggested Pickups (the best free agents for next week).

Pure functions over espn_api objects; report_data does the fetching. The report runs Tuesday,
before waivers clear Wednesday morning, so:

- The report card's window is "after week N-1's last game, through week N's last game". Moves
  made Monday night / Tuesday land in next week's window instead, so every move is graded exactly
  once, against the first week the player could have played for his new team.
- Suggested pickups are only meaningful as of right now, so report_data only builds them for the
  current report (not a backfill of an older week).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .stats import BENCH_SLOTS

# Grades for an added player's points in the window's week: first threshold met wins; anything
# above zero that misses them all is a D, and zero or less is an F.
GRADE_THRESHOLDS = [(20.0, "A"), (12.0, "B"), (6.0, "C")]
# A dropped player who scores at least this much for someone else (or nobody) the same week.
DROP_REGRET_POINTS = 15.0

ADD_ACTIONS = {"WAIVER ADDED", "FA ADDED", "TRADE_RECEIVED"}
DROP_ACTION = "DROPPED"

PICKUP_POSITIONS = ["QB", "RB", "WR", "TE", "D/ST", "K"]
PICKUPS_PER_POSITION = 2
# Statuses that make a free agent useless for next week regardless of projection.
UNAVAILABLE_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION"}


@dataclass
class GradedAdd:
    team_name: str
    player_name: str
    position: str
    pro_team: str
    points: float | None  # None if the player's week couldn't be looked up
    started: bool | None  # None when he wasn't on the team's lineup at week's end (flipped again)
    grade: str
    # Where the player is as of the report: "rostered" (still on the team that added him),
    # "dropped" (on no team -- back on waivers or free agency) or "elsewhere" (on `current_team`).
    status: str = "rostered"
    current_team: str | None = None


@dataclass
class RegretDrop:
    team_name: str
    player_name: str
    position: str
    pro_team: str
    points: float


@dataclass
class WaiverReportCard:
    adds: list[GradedAdd]
    regrets: list[RegretDrop]
    drops: int  # total drops in the window, for context


@dataclass
class Pickup:
    player_id: int
    player_name: str
    position: str
    pro_team: str
    projected: float
    percent_owned: float
    last_week_points: float | None  # filled in by report_data (not in the free-agent payload)


def grade(points: float | None) -> str:
    if points is None:
        return "—"
    for threshold, letter in GRADE_THRESHOLDS:
        if points >= threshold:
            return letter
    return "D" if points > 0 else "F"


def activity_time(activity) -> datetime:
    """espn_api Activity.date is epoch milliseconds."""
    return datetime.fromtimestamp(activity.date / 1000, tz=timezone.utc)


def in_window(activity, start: datetime | None, end: datetime) -> bool:
    when = activity_time(activity)
    return (start is None or when > start) and when <= end


def _lineups(box_scores: list) -> dict[int, tuple[str, object]]:
    """playerId -> (fantasy team name, BoxPlayer) for every player on any lineup this week."""
    found = {}
    for bs in box_scores:
        for team, lineup in ((bs.home_team, bs.home_lineup), (bs.away_team, bs.away_lineup)):
            for p in lineup:
                found[p.playerId] = (team.team_name, p)
    return found


def waiver_report_card(
    activity: list,
    box_scores: list,
    start: datetime | None,
    end: datetime,
    point_lookup: Callable[[int], float | None],
    current_rosters: dict[int, str],
) -> WaiverReportCard:
    """Grade every add (waiver, free agent, trade) in the window by the player's points that week,
    noting whether the new team started him and where he is now (`current_rosters`: playerId ->
    fantasy team rostering him today); flag drops who scored DROP_REGRET_POINTS+ anyway. Points
    come from the week's box scores when the player is on any lineup, else `point_lookup` (players
    nobody rosters at week's end)."""
    lineups = _lineups(box_scores)

    def points_for(player) -> float | None:
        on_lineup = lineups.get(player.playerId)
        return on_lineup[1].points if on_lineup else point_lookup(player.playerId)

    adds, regrets, drops = [], [], 0
    for act in activity:
        if not in_window(act, start, end):
            continue
        for team, action, player, *_ in act.actions:
            if action in ADD_ACTIONS:
                on_lineup = lineups.get(player.playerId)
                started = None
                if on_lineup and on_lineup[0] == team.team_name:
                    started = on_lineup[1].lineupSlot not in BENCH_SLOTS
                pts = points_for(player)
                now = current_rosters.get(player.playerId)
                status = "dropped" if now is None else ("rostered" if now == team.team_name else "elsewhere")
                adds.append(GradedAdd(
                    team.team_name, player.name, player.position, player.proTeam,
                    pts, started, grade(pts), status, now,
                ))
            elif action == DROP_ACTION:
                drops += 1
                pts = points_for(player)
                if pts is not None and pts >= DROP_REGRET_POINTS:
                    regrets.append(RegretDrop(team.team_name, player.name, player.position, player.proTeam, pts))
    adds.sort(key=lambda a: -(a.points if a.points is not None else float("-inf")))
    regrets.sort(key=lambda r: -r.points)
    return WaiverReportCard(adds, regrets, drops)


def suggested_pickups(
    free_agents_by_position: dict[str, list],
    per_position: int = PICKUPS_PER_POSITION,
) -> list[Pickup]:
    """Top `per_position` free agents at each position by next week's projection, skipping anyone
    OUT / on IR / suspended or projected for nothing."""
    def available(p) -> bool:
        # espn_api gives D/ST an empty list rather than a status string.
        status = p.injuryStatus if isinstance(p.injuryStatus, str) else ""
        return (p.projected_points or 0) > 0 and status not in UNAVAILABLE_STATUSES

    pickups = []
    for position in PICKUP_POSITIONS:
        candidates = [p for p in free_agents_by_position.get(position, []) if available(p)]
        candidates.sort(key=lambda p: -p.projected_points)
        for p in candidates[:per_position]:
            pickups.append(Pickup(
                p.playerId, p.name, position, p.proTeam, p.projected_points, p.percent_owned or 0.0, None,
            ))
    return pickups
