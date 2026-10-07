"""Casualty Report: which fantasy teams' starters have missed the most games to injury this season.

A record of what happened, not a forecast -- shown under the Waiver Report in both report modes,
and deliberately kept out of the letter's narrative data (narrative.py uses the separate
`WeekReport.injuries` list for its optional injury mentions).

Per completed week, a regular starter (see `is_regular_starter`) is **hurt** that week if he
either:
- **missed the game hurt**: didn't play, and was on that week's injury report (Out / Doubtful /
  Questionable), on NFL injured reserve, or parked in the fantasy IR slot -- or, for the latest
  week only, is listed Out / IR by ESPN today; or
- **got hurt in the game**: left and didn't return (play-by-play), confirmed by him still being
  hurt afterwards -- on the next week's injury report / reserve list or missing that game, or for
  the latest week, a non-healthy ESPN status today. That filters out one-play breathers.
Byes never count.

The page ranks teams by **starters hurt** (distinct players) and shows **weeks affected** (weeks
with at least one starter hurt, so never more than the weeks played). The total of player-games
missed is kept only as the first tiebreak, then draft position (internal, never printed), then
standings order.

Pure functions over espn_api box-score players; report_data does the fetching. Draft position is
an internal tiebreak only -- the page never shows a score for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .stats import BENCH_SLOTS, _ordinal

# ESPN's per-week "games played" stat code (it has no name in espn_api's stat map). Every player
# who appeared in his game -- even for a handful of snaps -- has it; one who sat out doesn't.
GAMES_PLAYED_STAT = "210"
# nflverse injury-report statuses that count as "hurt" for a game he then missed.
MISSED_GAME_DESIGNATIONS = {"Out", "Doubtful", "Questionable"}
# ESPN statuses (today) that count as hurt for the latest week's missed game.
OUT_NOW_STATUSES = {"OUT", "INJURY_RESERVE"}
# ESPN statuses (today) that confirm a latest-week in-game injury wasn't a one-play breather.
STILL_HURT_STATUSES = {"OUT", "INJURY_RESERVE", "DOUBTFUL", "QUESTIONABLE"}
# Plain words shown after a player who is still out today: "Barkley (out)", "Brown (IR)".
STATUS_WORDS = {"OUT": "out", "INJURY_RESERVE": "IR"}
# Each table row costs one line per name in its "Hurt in Week N" cell (at least one) plus this
# much padding, in line-heights, toward the rendered table's height budget (see visible_rows).
ROW_OVERHEAD_LINES = 0.6
# A player drafted this early counts as a regular starter for the team that drafted him even
# before he has started a game for it (e.g. hurt in Week 1).
REGULAR_STARTER_DRAFT_ROUNDS = 4


@dataclass
class PlayerToll:
    player_id: int
    name: str
    position: str
    draft_round: int | None  # None for undrafted / later pickups
    weeks: set[int] = field(default_factory=set)  # weeks he was hurt (missed or left a game)
    this_week: bool = False  # hurt in the latest week
    status_word: str | None = None  # "out" / "IR" if still out today

    @property
    def games_missed(self) -> int:
        return len(self.weeks)

    @property
    def draft_label(self) -> str:
        """Plain words for draft position: "1st-round pick" or "undrafted"."""
        return f"{_ordinal(self.draft_round)}-round pick" if self.draft_round else "undrafted"

    @property
    def surname(self) -> str:
        parts = self.name.split()
        if len(parts) > 2 and parts[-1].rstrip(".") in {"Jr", "Sr", "II", "III", "IV"}:
            return parts[-2]
        return parts[-1] if parts else self.name


@dataclass
class TeamToll:
    team_name: str
    players: list[PlayerToll] = field(default_factory=list)  # biggest loss first

    @property
    def games_missed(self) -> int:
        """Player-games missed (internal tiebreak only -- can exceed weeks played)."""
        return sum(p.games_missed for p in self.players)

    @property
    def starters_hurt(self) -> int:
        return len(self.players)

    @property
    def weeks_affected(self) -> int:
        """Weeks with at least one starter hurt -- never more than the weeks played."""
        return len(set().union(*(p.weeks for p in self.players)))

    @property
    def biggest_loss(self) -> PlayerToll:
        return self.players[0]

    @property
    def this_week(self) -> list[PlayerToll]:
        return [p for p in self.players if p.this_week]


@dataclass
class CasualtyReport:
    rows: list[TeamToll]  # teams with at least one starter hurt, worst first
    unaffected_teams: int  # teams with no starter hurt
    week: int  # the latest completed week
    weeks_played: int

    def visible_rows(self, max_rows: int, max_lines: float) -> list[TeamToll]:
        """The leading rows that fit both caps, so the rendered table stays on its page; always
        at least the first row."""
        shown, used = [], 0.0
        for row in self.rows[:max_rows]:
            cost = max(1, len(row.this_week)) + ROW_OVERHEAD_LINES
            if shown and used + cost > max_lines:
                break
            shown.append(row)
            used += cost
        return shown


def draft_weight(draft_round: int | None, total_rounds: int) -> int:
    """Internal tiebreak weight: earlier picks weigh more; undrafted players weigh nothing."""
    if not draft_round:
        return 0
    return max(0, total_rounds + 1 - draft_round)


def played(player, week: int) -> bool:
    """Whether the player appeared in his game that week, from ESPN's games-played stat."""
    breakdown = (getattr(player, "stats", {}) or {}).get(week, {}).get("breakdown") or {}
    return (breakdown.get(GAMES_PLAYED_STAT) or 0) > 0


def _status(player) -> str:
    # espn_api gives D/ST an empty list rather than a status string.
    return player.injuryStatus if isinstance(player.injuryStatus, str) else ""


def is_regular_starter(player_id: int, team_name: str, started: set[int], drafted_by: dict[int, tuple[str, int]]) -> bool:
    """Started for this team in this or an earlier week, or was one of its top draft picks. Being
    benched or moved to the IR slot while hurt doesn't make a regular starter stop counting."""
    if player_id in started:
        return True
    team, rnd = drafted_by.get(player_id, (None, None))
    return team == team_name and rnd is not None and rnd <= REGULAR_STARTER_DRAFT_ROUNDS


def casualty_report(
    box_scores_by_week: dict[int, list],
    designations: dict[int, dict[int, str]],
    reserve: dict[int, set[int]],
    left_game: dict[int, set[int]],
    drafted_by: dict[int, tuple[str, int]],
    total_rounds: int,
    team_order: list[str],
) -> CasualtyReport:
    """Season-to-date games missed per team, through the latest week in `box_scores_by_week`.

    Per week: `designations` (ESPN ID -> nflverse injury-report status), `reserve` (ESPN IDs on
    NFL injured reserve), `left_game` (ESPN IDs who left their game and didn't return).
    `drafted_by`: ESPN ID -> (fantasy team that drafted him, round)."""
    weeks = sorted(box_scores_by_week)
    latest = weeks[-1]

    # playerId -> (played, on bye) per week, from any lineup (he may have changed teams).
    appearance: dict[int, dict[int, tuple[bool, bool]]] = {}
    for w in weeks:
        appearance[w] = {
            p.playerId: (played(p, w), bool(getattr(p, "on_bye_week", False)))
            for bs in box_scores_by_week[w] for p in bs.home_lineup + bs.away_lineup
        }

    def still_hurt_after(pid: int, w: int, status_now: str) -> bool:
        if w == latest:
            return status_now in STILL_HURT_STATUSES
        nxt = w + 1
        if pid in designations.get(nxt, {}) or pid in reserve.get(nxt, set()):
            return True
        was_played, on_bye = appearance.get(nxt, {}).get(pid, (True, False))
        return not was_played and not on_bye

    tolls: dict[str, dict[int, PlayerToll]] = {}
    started: dict[str, set[int]] = {}
    all_teams: set[str] = set()
    for w in weeks:
        for bs in box_scores_by_week[w]:
            for team, lineup in ((bs.home_team, bs.home_lineup), (bs.away_team, bs.away_lineup)):
                name = team.team_name
                all_teams.add(name)
                team_started = started.setdefault(name, set())
                team_started.update(p.playerId for p in lineup if p.lineupSlot not in BENCH_SLOTS)
                for p in lineup:
                    if getattr(p, "on_bye_week", False):
                        continue
                    if not is_regular_starter(p.playerId, name, team_started, drafted_by):
                        continue
                    status_now = _status(p)
                    if not played(p, w):
                        hurt = (
                            designations.get(w, {}).get(p.playerId) in MISSED_GAME_DESIGNATIONS
                            or p.playerId in reserve.get(w, set())
                            or p.lineupSlot == "IR"
                            or (w == latest and status_now in OUT_NOW_STATUSES)
                        )
                    else:
                        hurt = p.playerId in left_game.get(w, set()) and still_hurt_after(p.playerId, w, status_now)
                    if not hurt:
                        continue
                    toll = tolls.setdefault(name, {}).setdefault(p.playerId, PlayerToll(
                        p.playerId, p.name, p.position, drafted_by.get(p.playerId, (None, None))[1],
                    ))
                    toll.weeks.add(w)
                    toll.this_week = toll.this_week or w == latest
                    # espn_api's injuryStatus is today's status in every week's box score.
                    toll.status_word = STATUS_WORDS.get(status_now)

    rows = []
    for name, players in tolls.items():
        ordered = sorted(
            players.values(), key=lambda t: (t.draft_round or total_rounds + 1, -t.games_missed, t.name),
        )
        rows.append(TeamToll(name, ordered))
    order = {name: i for i, name in enumerate(team_order)}
    rows.sort(key=lambda r: (
        -r.starters_hurt,
        -r.games_missed,
        -sum(draft_weight(p.draft_round, total_rounds) for p in r.players),
        order.get(r.team_name, len(order)),
        r.team_name,
    ))
    return CasualtyReport(rows, len(all_teams) - len(rows), latest, len(weeks))
