"""Assembles a single WeekReport object from espn_client + stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from . import espn_client, nfl_supplemental, stats


@dataclass
class StandingsRow:
    team_name: str
    division_name: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    streak: str
    playoff_pct: float | None
    power_rank: int | None
    commissioner_rank: int | None


@dataclass
class MatchupResult:
    home_team_name: str
    away_team_name: str
    home_score: float
    away_score: float
    home_projected: float
    away_projected: float
    winner_name: str


@dataclass
class WeekReport:
    week: int
    season_year: int
    league_name: str
    report_date: date
    is_season_finale: bool
    matchups: list[MatchupResult]
    standings: list[StandingsRow]
    team_highlights: dict[str, stats.TeamStat]
    individual_highlights: dict[str, stats.PlayerStat]
    commissioners_letter: str | None = None
    season_extras: dict = field(default_factory=dict)


def load_power_rankings_override(path: str | Path | None, week: int) -> dict[str, int]:
    if not path or not Path(path).exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get(f"week_{week}", {})


# Display order for the per-position "Top X" awards in Individual Highlights. Any position not
# listed (shouldn't happen in standard ESPN leagues) is appended alphabetically after these.
POSITION_ORDER = ["QB", "RB", "WR", "TE", "D/ST", "K"]


def ordered_individual_highlights(
    mvp,
    top_by_position: dict,
    bench,
    rookie,
    gamecock,
) -> dict:
    """Individual Highlights in display order: MVP, then the position winners (QB, RB, WR, TE,
    D/ST, K), then Bench MVP, then the two spotlight awards (Rookie, Gamecock). Missing awards
    (None) are dropped."""
    ordered = {"Individual MVP": mvp}
    known = [pos for pos in POSITION_ORDER if pos in top_by_position]
    extras = sorted(pos for pos in top_by_position if pos not in POSITION_ORDER)
    for position in known + extras:
        ordered[f"Top {position}"] = top_by_position[position]
    ordered["Bench MVP"] = bench
    ordered["Rookie Spotlight"] = rookie
    ordered["Gamecock of the Week"] = gamecock
    return {k: v for k, v in ordered.items() if v is not None}


def _safe_rookie_candidates(season: int, week: int) -> list:
    try:
        return nfl_supplemental.get_rookie_candidates(season, week)
    except Exception as exc:  # noqa: BLE001 - a supplemental lookup failing
        print(f"warning: Rookie Spotlight lookup failed ({exc}); skipping for this week.")
        return []


def _safe_gamecock_candidates(season: int, week: int) -> list:
    try:
        return nfl_supplemental.get_gamecock_candidates(season, week)
    except Exception as exc:  # noqa: BLE001 - should never take down the whole report
        print(f"warning: Gamecock of the Week lookup failed ({exc}); skipping for this week.")
        return []


def build_week_report(
    league,
    week: int | None = None,
    power_rankings_override_path: str | Path | None = None,
) -> WeekReport:
    week = espn_client.resolve_target_week(league, week)
    box_scores = espn_client.get_box_scores(league, week)
    current_scores = stats.team_scores(box_scores)

    prior_scores: dict[str, float] = {}
    if week > 1:
        prior_box_scores = espn_client.get_box_scores(league, week - 1)
        prior_scores = stats.team_scores(prior_box_scores)

    matchups = [
        MatchupResult(
            home_team_name=bs.home_team.team_name,
            away_team_name=bs.away_team.team_name,
            home_score=bs.home_score,
            away_score=bs.away_score,
            home_projected=bs.home_projected,
            away_projected=bs.away_projected,
            winner_name=(
                bs.home_team.team_name if bs.home_score >= bs.away_score else bs.away_team.team_name
            ),
        )
        for bs in box_scores
    ]

    espn_teams = espn_client.get_standings(league)
    power_rankings = espn_client.get_power_rankings(league, week)
    power_rank_by_team = {team.team_name: i + 1 for i, (_, team) in enumerate(power_rankings)}
    commissioner_override = load_power_rankings_override(power_rankings_override_path, week)

    standings_rows = []
    for team in espn_teams:
        result, length = stats.streak_ending_at(team.outcomes, week)
        streak_str = f"{length}{result}" if result else "-"
        standings_rows.append(
            StandingsRow(
                team_name=team.team_name,
                division_name=team.division_name,
                wins=team.wins,
                losses=team.losses,
                ties=team.ties,
                points_for=team.points_for,
                points_against=team.points_against,
                streak=streak_str,
                playoff_pct=getattr(team, "playoff_pct", None),
                power_rank=power_rank_by_team.get(team.team_name),
                commissioner_rank=commissioner_override.get(
                    team.team_name, power_rank_by_team.get(team.team_name)
                ),
            )
        )
    standings_rows.sort(key=lambda row: (-row.wins, row.losses, -row.points_for))

    best, worst = stats.best_worst_team(box_scores)
    most_improved, biggest_dropoff = stats.most_improved_biggest_dropoff(current_scores, prior_scores)
    closest, blowout = stats.closest_win_biggest_blowout(box_scores)
    win_streak, loss_streak = stats.longest_streaks(espn_teams, week)
    upset = stats.biggest_upset(box_scores)
    underachiever = stats.biggest_underachiever(box_scores)

    team_highlights = {
        "Best Performing Team": best,
        "Worst Performing Team": worst,
        "Most Improved": most_improved,
        "Biggest Drop-Off": biggest_dropoff,
        "Closest Win": closest,
        "Biggest Blowout": blowout,
        "Longest Win Streak": win_streak,
        "Longest Loss Streak": loss_streak,
        "Biggest Upset": upset,
        "Biggest Underachiever": underachiever,
    }
    team_highlights = {k: v for k, v in team_highlights.items() if v is not None}

    mvp = stats.individual_mvp(box_scores)
    top_by_position = stats.top_scorer_by_position(box_scores)
    bench = stats.bench_mvp(box_scores)
    rookie = stats.rookie_spotlight(box_scores, _safe_rookie_candidates(league.year, week))
    gamecock = stats.gamecock_of_the_week(box_scores, _safe_gamecock_candidates(league.year, week))

    individual_highlights = ordered_individual_highlights(mvp, top_by_position, bench, rookie, gamecock)

    return WeekReport(
        week=week,
        season_year=league.year,
        league_name=league.settings.name,
        report_date=date.today(),
        is_season_finale=espn_client.is_last_regular_season_week(league, week),
        matchups=matchups,
        standings=standings_rows,
        team_highlights=team_highlights,
        individual_highlights=individual_highlights,
    )
