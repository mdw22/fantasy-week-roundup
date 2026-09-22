"""Supplemental NFL data via nflreadpy — facts ESPN's fantasy API doesn't expose:
rookie status and weekly PPR points (for Rookie Spotlight, league-wide), college affiliation + weekly stat lines
(for Gamecock of the Week, scoped to University of South Carolina alumni per the
design spec), and in-game injuries parsed from play-by-play text (for optional
mentions in the Commissioner's Letter).

Kept isolated from src/stats.py on purpose, the same way src/espn_client.py is:
this module is the only place that talks to nflreadpy and knows its column
names, so the rest of the app depends only on plain dict/set/dataclass return
types and stays easy to unit-test against fixtures (see tests/test_stats.py and
tests/test_nfl_supplemental.py) without a live network call.

Column names below were checked against nflreadpy 0.1.5's real 2026 data
(load_rosters / load_player_stats). Loaders raise a RuntimeError naming the actual
columns if a required one disappears (e.g. after an nflreadpy upgrade), and
report_data's _safe_* wrappers turn that into a printed warning rather than a crash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import nflreadpy as nfl

GAMECOCK_COLLEGE = "South Carolina"

# Rookie Spotlight only considers positions where nflverse's `fantasy_points_ppr` is exactly this
# league's scoring (verified against ESPN: 192/192 rostered QB/RB/WR/TE player-weeks matched).
# K has no nflverse fantasy points and D/ST has no player rows, so neither is eligible.
ROOKIE_POSITIONS = {"QB", "RB", "WR", "TE"}

# nflverse team codes that differ from ESPN's, so pro-team labels read the same as everywhere else
# in the report.
_ESPN_TEAM_ABBR = {"LA": "LAR", "WAS": "WSH"}


def espn_team_abbr(nflverse_team: str | None) -> str:
    return _ESPN_TEAM_ABBR.get(nflverse_team or "", nflverse_team or "")

# (key, nflreadpy weekly-stats columns summed for this stat, short label for the
# detail string, weight toward the notability score). Every listed column must
# exist in load_player_stats' output (checked at load time). Order only affects
# the detail string, which lists non-zero DETAIL_WORTHY stats most notable first.
# Tackles are solo + assists (nflverse has no combined column); blocked kicks are
# the *defensive* blocks -- `fg_blocked` is a kicker stat (his own kick got
# blocked), which would credit the wrong player.
STAT_SPECS: list[tuple[str, list[str], str, float]] = [
    ("def_tds", ["def_tds"], "def TD", 6.0),
    ("special_teams_tds", ["special_teams_tds"], "ST TD", 6.0),
    ("blocked_kicks", ["def_fg_blocks", "def_pat_blocks", "def_punt_blocks"], "blocked kick", 4.0),
    ("interceptions", ["def_interceptions"], "INT", 6.0),
    ("forced_fumbles", ["def_fumbles_forced"], "FF", 3.0),
    ("fumble_recoveries", ["fumble_recovery_opp"], "FR", 2.0),
    ("sacks", ["def_sacks"], "sack", 2.0),
    ("tackles", ["def_tackles_solo", "def_tackle_assists"], "tkl", 1.0),
    ("rush_tds", ["rushing_tds"], "rush TD", 6.0),
    ("rec_tds", ["receiving_tds"], "rec TD", 6.0),
    ("pass_tds", ["passing_tds"], "pass TD", 4.0),
    ("receptions", ["receptions"], "rec", 0.5),
    ("rush_yards", ["rushing_yards"], "rush yds", 0.1),
    ("rec_yards", ["receiving_yards"], "rec yds", 0.1),
    ("pass_yards", ["passing_yards"], "pass yds", 0.04),
]

# Stats worth naming in the detail string even though they don't move the
# score much (or at all) -- mainly the two counting stats that read best as
# "N tkl" / "N rec" rather than the yardage they're paired with.
DETAIL_WORTHY = {
    "def_tds", "special_teams_tds", "blocked_kicks", "interceptions",
    "forced_fumbles", "fumble_recoveries", "sacks", "tackles",
    "rush_tds", "rec_tds", "pass_tds", "receptions",
}


@dataclass
class RookieCandidate:
    espn_id: int
    name: str
    position: str
    pro_team: str
    points: float


@dataclass
class GamecockCandidate:
    espn_id: int | None
    name: str
    position: str
    pro_team: str
    score: float
    detail: str


@dataclass
class InjuryCandidate:
    espn_id: int | None
    name: str
    position: str
    pro_team: str
    description: str


def score_and_describe(row: dict) -> tuple[float, str]:
    """Pure scoring/formatting helper, independent of nflreadpy's actual column
    names — takes a plain {column_name: value} dict (as produced by
    polars.DataFrame.to_dicts()) and returns (notability_score, detail_string).

    No fantasy-points column is required or used: this is meant to surface a
    fun, "was this South Carolina alum's week worth bragging about" stat line
    for any position, not to reproduce standard fantasy scoring.
    """
    score = 0.0
    detail_parts = []
    for key, columns, label, weight in STAT_SPECS:
        value = sum(row.get(c) or 0 for c in columns)
        if not value:
            continue
        score += weight * value
        if key in DETAIL_WORTHY:
            count = int(value) if float(value).is_integer() else value  # half-sacks exist
            detail_parts.append(f"{count} {label}" if count != 1 else label[0].upper() + label[1:])
    detail = ", ".join(detail_parts) if detail_parts else "no notable stat line"
    return score, detail


def _is_gamecock(college: str | None) -> bool:
    """nflverse's `college` is a semicolon-delimited list of every school attended
    (e.g. "Oregon; South Carolina"), so match a whole entry -- not the raw string
    (misses transfers) and not a substring ("South Carolina State" isn't a Gamecock)."""
    return bool(college) and GAMECOCK_COLLEGE in (c.strip() for c in college.split(";"))


def _first_matching_column(columns, candidates: list[str]) -> str | None:
    return next((c for c in candidates if c in columns), None)


def _require_column(columns, candidates: list[str], logical_name: str, loader_name: str) -> str:
    match = _first_matching_column(columns, candidates)
    if match is None:
        raise RuntimeError(
            f"{loader_name}: none of {candidates} found for '{logical_name}'. "
            f"Actual columns: {sorted(columns)}"
        )
    return match


def get_rookie_candidates(season: int, week: int) -> list[RookieCandidate]:
    """Every rookie QB/RB/WR/TE with a stat line this week, league-wide (rostered by a fantasy team
    or not -- see src/stats.rookie_spotlight for how team credit is attached), scored with
    nflverse's `fantasy_points_ppr`.

    Rookies with no ESPN ID in nflverse's roster data (mostly undrafted / practice-squad players)
    are left out: without an ID we can't tell whether a fantasy team rosters them, and the report
    treats "unidentifiable" the same as "no rookie" rather than guessing."""
    rosters = nfl.load_rosters(seasons=[season])
    r_columns = rosters.columns
    espn_col = _require_column(r_columns, ["espn_id"], "espn_id", "load_rosters")
    gsis_col = _require_column(r_columns, ["gsis_id"], "gsis_id", "load_rosters")
    name_col = _require_column(r_columns, ["full_name", "player_name"], "name", "load_rosters")
    exp_col = _first_matching_column(r_columns, ["years_exp"])
    rookie_year_col = _first_matching_column(r_columns, ["rookie_year", "entry_year"])
    if exp_col is not None:
        rookies = rosters.filter(rosters[exp_col] == 0)
    elif rookie_year_col is not None:
        rookies = rosters.filter(rosters[rookie_year_col] == season)
    else:
        raise RuntimeError(
            "load_rosters: none of ['years_exp', 'rookie_year', 'entry_year'] found "
            f"to determine rookie status. Actual columns: {sorted(r_columns)}"
        )
    # load_rosters is one row per player per week; later weeks overwrite earlier ones here.
    rookie_by_gsis = {
        row[gsis_col]: row
        for row in rookies.to_dicts()
        if row.get(gsis_col) is not None and row.get(espn_col) is not None
    }
    if not rookie_by_gsis:
        return []

    stats = nfl.load_player_stats(seasons=[season])
    s_columns = stats.columns
    stat_gsis_col = _require_column(s_columns, ["player_id"], "gsis_id", "load_player_stats")
    week_col = _require_column(s_columns, ["week"], "week", "load_player_stats")
    position_col = _require_column(s_columns, ["position"], "position", "load_player_stats")
    team_col = _require_column(s_columns, ["team"], "team", "load_player_stats")
    ppr_col = _require_column(s_columns, ["fantasy_points_ppr"], "fantasy_points_ppr", "load_player_stats")

    candidates = []
    for row in stats.filter(stats[week_col] == week).to_dicts():
        roster_row = rookie_by_gsis.get(row.get(stat_gsis_col))
        if roster_row is None or row.get(position_col) not in ROOKIE_POSITIONS:
            continue
        candidates.append(
            RookieCandidate(
                espn_id=int(roster_row[espn_col]),
                name=roster_row[name_col],
                position=row[position_col],
                pro_team=espn_team_abbr(row.get(team_col) or roster_row.get("team")),
                points=float(row.get(ppr_col) or 0.0),
            )
        )
    return candidates


def get_gamecock_candidates(season: int, week: int) -> list[GamecockCandidate]:
    """Every South Carolina alum's scored, described performance for this week,
    league-wide (not scoped to this fantasy league's rosters — see
    src/stats.gamecock_of_the_week for how team credit is attached
    afterward). Empty list if nothing notable turns up, which is expected most
    weeks — most of a 14-team league's alumni pool won't be active NFL players."""
    rosters = nfl.load_rosters(seasons=[season])
    r_columns = rosters.columns
    college_col = _require_column(r_columns, ["college"], "college", "load_rosters")
    gsis_col = _require_column(r_columns, ["gsis_id"], "gsis_id", "load_rosters")
    espn_col = _require_column(r_columns, ["espn_id"], "espn_id", "load_rosters")
    name_col = _require_column(r_columns, ["full_name", "player_name"], "name", "load_rosters")
    position_col = _require_column(r_columns, ["position"], "position", "load_rosters")

    # load_rosters is one row per player per week, so later weeks overwrite earlier ones here.
    alumni_by_gsis = {
        row[gsis_col]: row
        for row in rosters.to_dicts()
        if row.get(gsis_col) is not None and _is_gamecock(row.get(college_col))
    }
    if not alumni_by_gsis:
        return []

    stats = nfl.load_player_stats(seasons=[season])
    s_columns = stats.columns
    stat_gsis_col = _require_column(s_columns, ["player_id"], "gsis_id", "load_player_stats")
    week_col = _require_column(s_columns, ["week"], "week", "load_player_stats")
    team_col = _require_column(s_columns, ["team"], "team", "load_player_stats")
    missing = sorted({c for _, cols, _, _ in STAT_SPECS for c in cols} - set(s_columns))
    if missing:
        raise RuntimeError(
            f"load_player_stats: expected stat columns missing {missing}. "
            f"Actual columns: {sorted(s_columns)}"
        )

    week_rows = stats.filter(stats[week_col] == week)

    candidates = []
    for row in week_rows.to_dicts():
        gsis_id = row.get(stat_gsis_col)
        roster_row = alumni_by_gsis.get(gsis_id)
        if roster_row is None:
            continue
        score, detail = score_and_describe(row)
        candidates.append(
            GamecockCandidate(
                espn_id=(int(roster_row[espn_col]) if roster_row.get(espn_col) is not None else None),
                name=roster_row[name_col],
                position=roster_row[position_col],
                pro_team=espn_team_abbr(row.get(team_col) or roster_row.get("team")),
                score=score,
                detail=detail,
            )
        )
    return candidates


# Play-by-play descriptions carry two fixed phrasings for in-game injuries -- there's no
# structured injury-event column in nflverse's pbp, so this is the only signal available. Group
# is (team, jersey_number); the player's own abbreviated name in the text ("Aj.Terrell") is not
# used for matching, since it doesn't reliably match a roster's full_name -- team + jersey against
# that week's roster does.
_INJURED_RE = re.compile(r"([A-Z]{2,3})-(\d+)-[A-Za-z.\-']+ was injured during the play")
_RETURNED_RE = re.compile(r"([A-Z]{2,3})-(\d+)-[A-Za-z.\-']+ has returned to the game")


def _players_who_did_not_return(plays: list[dict]) -> dict[tuple[str, str, str], object]:
    """`plays`: one week's plays, in play order, as {"game_id", "qtr", "desc"} dicts (any extra
    keys are ignored). Returns {(game_id, team, jersey): last_qtr_seen} for every player whose
    most recent in-game injury this week has no later "has returned to the game" line for the
    same (game_id, team, jersey).

    This is a noisy proxy for "major," not an official designation: nflverse's play-by-play has no
    severity or body-part field, and a player hurt on a game's final snap looks identical here to
    one who couldn't return for a serious reason -- there's no way to tell "game just ended" from
    "carted off" with this data source alone."""
    state: dict[tuple[str, str, str], dict] = {}
    for play in plays:
        desc = play.get("desc") or ""
        hurt = _INJURED_RE.search(desc)
        returned = _RETURNED_RE.search(desc)
        if hurt:
            key = (play.get("game_id"), hurt.group(1), hurt.group(2))
            state[key] = {"qtr": play.get("qtr"), "returned": False}
        if returned:
            key = (play.get("game_id"), returned.group(1), returned.group(2))
            if key in state:
                state[key]["returned"] = True
    return {key: info["qtr"] for key, info in state.items() if not info["returned"]}


def get_game_injuries(season: int, week: int) -> list[InjuryCandidate]:
    """Every in-game injury this week, league-wide, where the player didn't return to that game
    (see _players_who_did_not_return for what that does and doesn't mean). report_data scopes
    these down to players actually rostered in this fantasy league -- an injury to someone nobody
    here rosters has no house to attach it to in the letter -- before handing them to narrative.py
    as optional context; Claude decides whether any are worth mentioning, nothing is forced in."""
    pbp = nfl.load_pbp(seasons=[season])
    p_columns = pbp.columns
    week_col = _require_column(p_columns, ["week"], "week", "load_pbp")
    game_col = _require_column(p_columns, ["game_id"], "game_id", "load_pbp")
    play_col = _require_column(p_columns, ["play_id"], "play_id", "load_pbp")
    qtr_col = _require_column(p_columns, ["qtr"], "qtr", "load_pbp")
    desc_col = _require_column(p_columns, ["desc"], "desc", "load_pbp")

    plays = (
        pbp.filter(pbp[week_col] == week)
        .select([game_col, play_col, qtr_col, desc_col])
        .sort(play_col)
        .rename({game_col: "game_id", qtr_col: "qtr", desc_col: "desc"})
        .to_dicts()
    )
    did_not_return = _players_who_did_not_return(plays)
    if not did_not_return:
        return []

    rosters = nfl.load_rosters(seasons=[season])
    r_columns = rosters.columns
    jersey_col = _require_column(r_columns, ["jersey_number"], "jersey_number", "load_rosters")
    team_col = _require_column(r_columns, ["team"], "team", "load_rosters")
    name_col = _require_column(r_columns, ["full_name", "player_name"], "name", "load_rosters")
    position_col = _require_column(r_columns, ["position"], "position", "load_rosters")
    espn_col = _require_column(r_columns, ["espn_id"], "espn_id", "load_rosters")
    by_team_jersey = {
        (row[team_col], str(int(row[jersey_col]))): row
        for row in rosters.to_dicts()
        if row.get(jersey_col) is not None and row.get(team_col) is not None
    }

    injuries = []
    seen = set()
    for (game_id, team, jersey), qtr in did_not_return.items():
        roster_row = by_team_jersey.get((team, jersey))
        if roster_row is None:
            continue
        dedupe_key = (roster_row[name_col], game_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        espn_id = roster_row.get(espn_col)
        description = (
            f"Left the game in Q{int(qtr)} and did not return" if qtr is not None
            else "Left the game and did not return"
        )
        injuries.append(
            InjuryCandidate(
                espn_id=int(espn_id) if espn_id is not None else None,
                name=roster_row[name_col],
                position=roster_row[position_col],
                pro_team=espn_team_abbr(team),
                description=description,
            )
        )
    return injuries
