"""Highlight computations for a single week's box scores. See design spec §4.

All functions take espn_api objects (BoxScore, Team) directly rather than
intermediate dataclasses, so they can be unit-tested against small fixture
lists that mimic the real shapes (see tests/test_stats.py).
"""

from __future__ import annotations

from dataclasses import dataclass

BENCH_SLOTS = {"BE", "IR"}


@dataclass
class TeamStat:
    team_name: str
    value: float
    detail: str = ""


@dataclass
class PlayerStat:
    player_name: str
    team_name: str | None
    pro_team: str
    position: str
    points: float
    detail: str = ""


def team_scores(box_scores: list) -> dict[str, float]:
    scores: dict[str, float] = {}
    for bs in box_scores:
        scores[bs.home_team.team_name] = bs.home_score
        scores[bs.away_team.team_name] = bs.away_score
    return scores


def team_projected(box_scores: list) -> dict[str, float]:
    projected: dict[str, float] = {}
    for bs in box_scores:
        projected[bs.home_team.team_name] = bs.home_projected
        projected[bs.away_team.team_name] = bs.away_projected
    return projected


def best_worst_team(box_scores: list) -> tuple[TeamStat, TeamStat]:
    scores = team_scores(box_scores)
    best_name = max(scores, key=scores.get)
    worst_name = min(scores, key=scores.get)
    return (
        TeamStat(best_name, scores[best_name]),
        TeamStat(worst_name, scores[worst_name]),
    )


def most_improved_biggest_dropoff(
    current_scores: dict[str, float], prior_scores: dict[str, float]
) -> tuple[TeamStat | None, TeamStat | None]:
    """None for either side when there's no prior week to compare against (week 1)."""
    deltas = {
        name: current_scores[name] - prior_scores[name]
        for name in current_scores
        if name in prior_scores
    }
    if not deltas:
        return None, None
    best_name = max(deltas, key=deltas.get)
    worst_name = min(deltas, key=deltas.get)
    return (
        TeamStat(best_name, deltas[best_name]),
        TeamStat(worst_name, deltas[worst_name]),
    )


def closest_win_biggest_blowout(box_scores: list) -> tuple[TeamStat, TeamStat]:
    matchups = []
    for bs in box_scores:
        margin = abs(bs.home_score - bs.away_score)
        winner = bs.home_team if bs.home_score >= bs.away_score else bs.away_team
        loser = bs.away_team if winner is bs.home_team else bs.home_team
        matchups.append((margin, winner.team_name, loser.team_name))
    closest = min(matchups, key=lambda m: m[0])
    blowout = max(matchups, key=lambda m: m[0])
    return (
        TeamStat(closest[1], closest[0], detail=f"over {closest[2]}"),
        TeamStat(blowout[1], blowout[0], detail=f"over {blowout[2]}"),
    )


def streak_ending_at(outcomes: list[str], week: int) -> tuple[str, int]:
    """Longest run of the same result (W/L/T) in outcomes[:week], ending at `week`.

    espn_api's Team.outcomes is indexed by week (0-based) for the whole season,
    with 'U' for weeks not yet played — using this instead of Team.streak_length
    means streaks are computed correctly even when backfilling an old week,
    rather than reflecting the league's *current* live state.
    """
    relevant = outcomes[:week]
    if not relevant or relevant[-1] == "U":
        return ("", 0)
    last = relevant[-1]
    count = 0
    for result in reversed(relevant):
        if result == last:
            count += 1
        else:
            break
    return (last, count)


def longest_streaks(teams: list, week: int) -> tuple[TeamStat | None, TeamStat | None]:
    win_streaks = []
    loss_streaks = []
    for team in teams:
        result, length = streak_ending_at(team.outcomes, week)
        if result == "W":
            win_streaks.append((length, team.team_name))
        elif result == "L":
            loss_streaks.append((length, team.team_name))
    longest_win = max(win_streaks, default=None, key=lambda x: x[0])
    longest_loss = max(loss_streaks, default=None, key=lambda x: x[0])
    return (
        TeamStat(longest_win[1], longest_win[0]) if longest_win else None,
        TeamStat(longest_loss[1], longest_loss[0]) if longest_loss else None,
    )


def biggest_upset(box_scores: list) -> TeamStat | None:
    """Largest swing between projected margin and actual margin where the
    projected underdog won outright."""
    best = None
    for bs in box_scores:
        proj_margin_home = bs.home_projected - bs.away_projected
        actual_margin_home = bs.home_score - bs.away_score
        home_was_favored = proj_margin_home > 0
        home_won = actual_margin_home > 0
        upset_happened = home_was_favored != home_won and actual_margin_home != 0
        if not upset_happened:
            continue
        swing = abs(actual_margin_home - proj_margin_home)
        winner = bs.home_team if home_won else bs.away_team
        loser = bs.away_team if home_won else bs.home_team
        candidate = TeamStat(winner.team_name, swing, detail=f"upset over {loser.team_name}")
        if best is None or swing > best.value:
            best = candidate
    return best


def biggest_underachiever(box_scores: list) -> TeamStat | None:
    worst = None
    for bs in box_scores:
        for team, score, projected in (
            (bs.home_team, bs.home_score, bs.home_projected),
            (bs.away_team, bs.away_score, bs.away_projected),
        ):
            diff = score - projected
            if worst is None or diff < worst.value:
                worst = TeamStat(team.team_name, diff)
    return worst


def _iter_lineup_players(box_scores: list):
    """Yield (fantasy_team_name, player) for every rostered player across all box scores."""
    for bs in box_scores:
        for player in bs.home_lineup:
            yield bs.home_team.team_name, player
        for player in bs.away_lineup:
            yield bs.away_team.team_name, player


def individual_mvp(box_scores: list) -> PlayerStat | None:
    starters = [
        (team_name, p)
        for team_name, p in _iter_lineup_players(box_scores)
        if p.lineupSlot not in BENCH_SLOTS
    ]
    if not starters:
        return None
    team_name, player = max(starters, key=lambda tp: tp[1].points)
    return PlayerStat(player.name, team_name, player.proTeam, player.position, player.points)


def top_scorer_by_position(box_scores: list) -> dict[str, PlayerStat]:
    """Max starter points at each position that had at least one starter."""
    best_by_position: dict[str, PlayerStat] = {}
    for team_name, player in _iter_lineup_players(box_scores):
        if player.lineupSlot in BENCH_SLOTS:
            continue
        current = best_by_position.get(player.position)
        if current is None or player.points > current.points:
            best_by_position[player.position] = PlayerStat(
                player.name, team_name, player.proTeam, player.position, player.points
            )
    return best_by_position


def bench_mvp(box_scores: list) -> PlayerStat | None:
    bench = [
        (team_name, p)
        for team_name, p in _iter_lineup_players(box_scores)
        if p.lineupSlot == "BE"
    ]
    if not bench:
        return None
    team_name, player = max(bench, key=lambda tp: tp[1].points)
    return PlayerStat(player.name, team_name, player.proTeam, player.position, player.points)


def _rostered_team_by_espn_id(box_scores: list) -> dict[int, str]:
    """ESPN player ID -> fantasy team name, for everyone on a lineup (starter or bench) this week."""
    return {
        p.playerId: team_name
        for team_name, p in _iter_lineup_players(box_scores)
        if getattr(p, "playerId", None) is not None
    }


def rookie_spotlight(box_scores: list, candidates: list) -> PlayerStat | None:
    """Best NFL performance this week by a rookie QB/RB/WR/TE, league-wide -- rostered by a fantasy
    team (starter or bench) or not. `candidates` is the list of
    nfl_supplemental.RookieCandidate for this week, scored with nflverse PPR points (exactly this
    league's skill scoring). Credits the fantasy team if that rookie happens to be rostered here
    (matched by ESPN player ID); otherwise the team is left blank and the template shows the
    "Free agent" pill, same as Gamecock of the Week."""
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c.points)
    return PlayerStat(
        best.name,
        _rostered_team_by_espn_id(box_scores).get(best.espn_id),
        best.pro_team,
        best.position,
        best.points,
    )


def gamecock_of_the_week(box_scores: list, candidates: list) -> PlayerStat | None:
    """Best NFL performance this week, any position, by a University of South
    Carolina alum -- league-wide, not limited to this fantasy league's rosters.
    `candidates` is the list of nfl_supplemental.GamecockCandidate already scored
    and described for this week (see nfl_supplemental.get_gamecock_candidates).
    Credits the fantasy team if that player happens to be rostered here (matched
    by ESPN player ID); otherwise the team is left blank, same as the sample
    report's convention for a non-rostered spotlight."""
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c.score)
    rostered_by = _rostered_team_by_espn_id(box_scores)
    team_name = rostered_by.get(best.espn_id)
    return PlayerStat(
        best.name, team_name, best.pro_team, best.position, best.score, detail=best.detail
    )
