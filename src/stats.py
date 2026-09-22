"""Highlight computations for a single week's box scores. See design spec §4.

All functions take espn_api objects (BoxScore, Team) directly rather than
intermediate dataclasses, so they can be unit-tested against small fixture
lists that mimic the real shapes (see tests/test_stats.py).
"""

from __future__ import annotations

from dataclasses import dataclass

BENCH_SLOTS = {"BE", "IR"}

# For notable_injuries(): a bench player counts as "high value" if ESPN projected them for at
# least this many points that week -- a flat cutoff, not position-adjusted, but a cheap proxy for
# "startable" that's good enough for deciding whether an injury is worth the letter's attention.
# Starters clear the bar automatically regardless of this threshold (see notable_injuries).
HIGH_VALUE_PROJECTED_POINTS = 12.0


@dataclass
class TeamStat:
    team_name: str
    value: float
    detail: str = ""
    display: str = ""  # shown in the Value column instead of the formatted number when non-empty


@dataclass
class ScoreBar:
    team_name: str
    score: float
    won: bool
    pct: float  # score as a percentage of the week's highest score (0-100)


@dataclass
class PlayerStat:
    player_name: str
    team_name: str | None
    pro_team: str
    position: str
    points: float
    detail: str = ""


@dataclass
class InjuryNote:
    player_name: str
    team_name: str  # always set -- unrostered injuries are dropped, see notable_injuries()
    pro_team: str
    position: str
    description: str


@dataclass
class SeasonScorer:
    player_name: str
    team_name: str  # the fantasy team that most recently started this player
    pro_team: str
    position: str
    points: float


def season_top_scorers(box_scores_by_week: dict[int, list], limit: int = 3) -> list[SeasonScorer]:
    """Top players by fantasy points across the season so far, counting only points earned while
    in a starting lineup -- the same "starter" rule as Individual MVP and the Top-position
    awards, so a player's total is what actually counted for a team. Summed by ESPN player ID,
    so a player who changes fantasy teams keeps one running total (credited to the team that
    started him most recently). Bench/IR weeks don't count."""
    totals: dict[object, float] = {}
    latest: dict[object, tuple[int, object, str]] = {}  # key -> (week, player, team_name)
    for week in sorted(box_scores_by_week):
        for team_name, player in _iter_lineup_players(box_scores_by_week[week]):
            if player.lineupSlot in BENCH_SLOTS:
                continue
            key = getattr(player, "playerId", None) or player.name
            totals[key] = totals.get(key, 0.0) + player.points
            latest[key] = (week, player, team_name)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:limit]
    return [
        SeasonScorer(latest[key][1].name, latest[key][2], latest[key][1].proTeam, latest[key][1].position, pts)
        for key, pts in ranked
    ]


def team_scores(box_scores: list) -> dict[str, float]:
    scores: dict[str, float] = {}
    for bs in box_scores:
        scores[bs.home_team.team_name] = bs.home_score
        scores[bs.away_team.team_name] = bs.away_score
    return scores


def score_bars(box_scores: list) -> list[ScoreBar]:
    """Every team's score for the week, highest first, for the "Week N at a Glance" bar chart.
    `won` mirrors the scoreboard's winner logic (a tie goes to the home team). `pct` is relative to
    the week's top score so the bars scale to the data."""
    entries = []
    for bs in box_scores:
        home_won = bs.home_score >= bs.away_score
        entries.append((bs.home_team.team_name, bs.home_score, home_won))
        entries.append((bs.away_team.team_name, bs.away_score, not home_won))
    if not entries:
        return []
    top = max(score for _, score, _ in entries)
    bars = [
        ScoreBar(name, score, won, (score / top * 100) if top > 0 else 0.0)
        for name, score, won in entries
    ]
    return sorted(bars, key=lambda b: -b.score)


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
        TeamStat(best_name, scores[best_name], detail="highest score this week"),
        TeamStat(worst_name, scores[worst_name], detail="lowest score this week"),
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
        TeamStat(best_name, deltas[best_name], detail="point increase from last week"),
        TeamStat(worst_name, deltas[worst_name], detail="point decrease from last week"),
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
        TeamStat(closest[1], closest[0], detail=f"margin of victory over {closest[2]}"),
        TeamStat(blowout[1], blowout[0], detail=f"margin of victory over {blowout[2]}"),
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
        TeamStat(longest_win[1], longest_win[0], detail="consecutive wins") if longest_win else None,
        TeamStat(longest_loss[1], longest_loss[0], detail="consecutive losses") if longest_loss else None,
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
        candidate = TeamStat(
            winner.team_name, swing, detail=f"point swing vs. the projection, upset over {loser.team_name}"
        )
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
                worst = TeamStat(team.team_name, diff, detail="points below projection")
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


def _rostered_player_by_espn_id(box_scores: list) -> dict[int, tuple[str, object]]:
    """ESPN player ID -> (fantasy team name, Player), for everyone on a lineup this week -- like
    _rostered_team_by_espn_id but keeps the Player object too, for filters that need lineupSlot or
    projected_points (see notable_injuries)."""
    return {
        p.playerId: (team_name, p)
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


def notable_injuries(box_scores: list, candidates: list) -> list[InjuryNote]:
    """In-game injuries this week (nfl_supplemental.InjuryCandidate, from
    nfl_supplemental.get_game_injuries) narrowed to players who are both (a) rostered on a fantasy
    team here, matched by ESPN player ID, and (b) either started that week or are "high value"
    (projected_points >= HIGH_VALUE_PROJECTED_POINTS) even if benched.

    The play-by-play has no severity or body-part field (see nfl_supplemental's docstring), so
    there's no way to tell a season-ending injury from a routine one-play breather apart from
    whether the player mattered to a fantasy lineup -- restricting to starters/high-value players
    is a stand-in for "was this actually worth a mention" given that blind spot. An unrostered
    injury is dropped rather than shown as unattributed (unlike Rookie Spotlight and Gamecock of
    the Week): this list exists to give the letter's narrative optional material ("your team's X
    got hurt"), and an injury to a player nobody in this league rosters has no house to attach it
    to. Order is not significant -- narrative.py includes all of them and lets Claude pick what's
    worth mentioning, if anything (and is told to stay vague about severity, since none is known)."""
    rostered_by = _rostered_player_by_espn_id(box_scores)
    notes = []
    for c in candidates:
        rostered = rostered_by.get(c.espn_id)
        if rostered is None:
            continue
        team_name, player = rostered
        is_starter = player.lineupSlot not in BENCH_SLOTS
        is_high_value = (player.projected_points or 0) >= HIGH_VALUE_PROJECTED_POINTS
        if not (is_starter or is_high_value):
            continue
        notes.append(InjuryNote(c.name, team_name, c.pro_team, c.position, c.description))
    return notes


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def luckiest_win_unluckiest_loss(box_scores: list) -> tuple[TeamStat | None, TeamStat | None]:
    """All-play luck for the week. A team's all-play record is how many of the other teams' scores
    it beat this week, as if it had played everyone.

    - Luckiest Win: the matchup winner with the fewest all-play wins (won its game while scoring
      near the bottom of the league).
    - Unluckiest Loss: the matchup loser with the most all-play wins (outscored most of the
      league and still lost).

    Each is only returned when its "despite ranking Nth" claim is actually true -- the lucky
    winner has to rank in the bottom half of the field, the unlucky loser in the top half --
    otherwise that row is None and the report leaves it out. Ties in all-play wins go to the
    lower score (lucky) / higher score (unlucky). `value` is the all-play wins; `display` spells
    it out as "Would have beaten N teams"."""
    scores = team_scores(box_scores)
    n = len(scores)
    if n < 2:
        return None, None
    winners, losers = set(), set()
    for bs in box_scores:
        home_won = bs.home_score >= bs.away_score
        winners.add(bs.home_team.team_name if home_won else bs.away_team.team_name)
        losers.add(bs.away_team.team_name if home_won else bs.home_team.team_name)

    def all_play_wins(name: str) -> int:
        return sum(1 for other, s in scores.items() if other != name and s < scores[name])

    def scoring_rank(name: str) -> int:
        return 1 + sum(1 for s in scores.values() if s > scores[name])

    def build(name: str, verb: str) -> TeamStat:
        wins = all_play_wins(name)
        team_word = "team" if wins == 1 else "teams"
        return TeamStat(
            name, float(wins),
            detail=f"{verb} despite ranking {_ordinal(scoring_rank(name))} of {n} in scoring",
            display=f"Would have beaten {wins} {team_word}",
        )

    lucky = min(winners, key=lambda nm: (all_play_wins(nm), scores[nm]), default=None)
    unlucky = max(losers, key=lambda nm: (all_play_wins(nm), scores[nm]), default=None)
    half = (n - 1) / 2
    luckiest = build(lucky, "won") if lucky is not None and all_play_wins(lucky) < half else None
    unluckiest = build(unlucky, "lost") if unlucky is not None and all_play_wins(unlucky) > half else None
    return luckiest, unluckiest
