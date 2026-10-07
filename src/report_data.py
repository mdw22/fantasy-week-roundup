"""Assembles a single WeekReport object from espn_client + stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from . import casualties, espn_client, history, nfl_supplemental, preview, stats, waivers


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
    # Positions gained since last week (positive = moved up, negative = fell, 0 = unchanged);
    # None when there is no prior-week value to compare against (e.g. Week 1).
    power_rank_change: int | None = None
    commissioner_rank_change: int | None = None


@dataclass
class MatchupResult:
    home_team_name: str
    away_team_name: str
    home_score: float
    away_score: float
    home_projected: float
    away_projected: float
    winner_name: str
    # The starter (either team) who most exceeded/fell short of their own projection this
    # matchup -- letter-only context, not rendered in the PDF. See stats.matchup_standout_performers.
    overperformer: stats.PlayerStat | None = None
    underperformer: stats.PlayerStat | None = None


@dataclass
class SeasonLeaders:
    top_teams: list[tuple[str, float]]  # (team name, season points for), best first
    top_scorers: list[stats.SeasonScorer]


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
    score_bars: list[stats.ScoreBar] = field(default_factory=list)
    season_leaders: SeasonLeaders | None = None  # None in Week 1: season-to-date == this week
    # In-game injuries to rostered players this week, for the letter to optionally reference --
    # not rendered as its own report section. See stats.notable_injuries.
    injuries: list[stats.InjuryNote] = field(default_factory=list)
    season_table: list[stats.SeasonTeamRow] = field(default_factory=list)  # Appendix A
    lifetime: history.LifetimeStats | None = None  # Appendix B; None if history couldn't load
    # None if the activity/schedule lookups failed; an empty card is a quiet week.
    waiver_report_card: waivers.WaiverReportCard | None = None
    # Next week's best free agents; empty unless this is the latest completed week (a backfill
    # can't know who was available back then) and there is a next week.
    pickups: list[waivers.Pickup] = field(default_factory=list)
    # II. Week N+1 Preview; None under the same conditions as `pickups`, or if the lookup failed.
    preview: preview.Preview | None = None
    # Starters lost to injury this week, ranked by team; shown under the Waiver Report. Never sent
    # to the letter (that's `injuries` above). None under the same conditions as `pickups`, or if
    # a lookup failed.
    casualty_report: casualties.CasualtyReport | None = None
    commissioners_letter: str | None = None
    season_extras: dict = field(default_factory=dict)
    # Big Report mode renders the appendices (season_table, lifetime) too; Standard Weekly mode
    # hides them. Both modes build the same data -- this only decides what the PDF shows, so the
    # Big Report is turned off, never removed. main.py sets it from the schedule / CLI flags.
    big_report: bool = True

    @property
    def top_pickups(self) -> list[waivers.Pickup]:
        """One pickup per position: the Standard Weekly report's waiver section."""
        return waivers.best_per_position(self.pickups)


def load_power_rankings_override(path: str | Path | None, week: int) -> dict[str, int]:
    if not path or not Path(path).exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get(f"week_{week}", {})


_POWER_RANKINGS_OVERRIDE_HEADER = """\
# Manual "Commissioner" power rankings, updated by hand before each run.
# Keys are ESPN team_name values (must match exactly). Value is the rank (1 = best).
# Any team omitted falls back to the ESPN algorithmic power ranking for that week.
"""


def ensure_power_rankings_override(league, week: int, path: str | Path | None) -> None:
    """The first time a week is run, seeds config/power_rankings_override.yaml with that week's
    ESPN algorithmic ranking as a starting point to hand-edit. Every run after that leaves the
    week's block alone -- re-running a week (a re-render, a backfill) must never clobber whatever
    the "Commissioner" has since typed in by hand.

    Appends rather than rewriting the whole file: round-tripping the existing content through
    yaml.safe_load + yaml.safe_dump would silently strip the header comment (and any comments the
    user added to their own week blocks), since PyYAML has no comment-preserving dump mode."""
    if not path:
        return
    path = Path(path)
    existing_text = path.read_text() if path.exists() else ""
    existing_data = yaml.safe_load(existing_text) or {} if existing_text.strip() else {}
    week_key = f"week_{week}"
    if week_key in existing_data:
        return  # already seeded (or hand-edited) -- leave it alone

    power_rankings = espn_client.get_power_rankings(league, week)
    ranks = {team.team_name: i + 1 for i, (_, team) in enumerate(power_rankings)}
    if not ranks:
        return  # nothing to seed with (e.g. week not yet playable)

    block = yaml.safe_dump({week_key: ranks}, default_flow_style=False, sort_keys=False, allow_unicode=True)
    with open(path, "a") as f:
        if not existing_text:
            f.write(_POWER_RANKINGS_OVERRIDE_HEADER + "\n")
        elif not existing_text.endswith("\n"):
            f.write("\n")
        f.write("\n" + block)


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


def rank_change(previous: int | None, current: int | None) -> int | None:
    """Positions gained since last week: previous - current, since a lower rank number is better
    (4th -> 2nd is +2). None when either value is missing, so the report shows no movement
    marker at all rather than implying "unchanged"."""
    if previous is None or current is None:
        return None
    return previous - current


def _prior_week_ranks(league, week: int, override_path) -> tuple[dict[str, int], dict[str, int]]:
    """(power ranks, commissioner ranks) as of last week, or ({}, {}) for Week 1 or if ESPN
    can't supply them. Power rankings are recomputed by espn_api from each team's scoring history
    through that week, so no state has to be stored between runs. Commissioner ranks follow the
    same fallback as the current week: last week's manual override where a team has one, else
    last week's algorithmic rank."""
    if week <= 1:
        return {}, {}
    try:
        prior_power = {
            team.team_name: i + 1
            for i, (_, team) in enumerate(espn_client.get_power_rankings(league, week - 1))
        }
    except Exception as exc:  # noqa: BLE001 - movement markers are a nice-to-have
        print(f"warning: prior-week power rankings unavailable ({exc}); omitting rank movement.")
        return {}, {}
    prior_override = load_power_rankings_override(override_path, week - 1)
    prior_commissioner = {name: prior_override.get(name, rank) for name, rank in prior_power.items()}
    return prior_power, prior_commissioner


def _build_season_leaders(standings_rows: list, box_scores_by_week: dict, week: int) -> SeasonLeaders | None:
    """Top 3 teams (season points for) and top 3 starters (season fantasy points). Suppressed in
    Week 1, when it would only repeat this week's highlights."""
    if week < 2:
        return None
    top_teams = [
        (row.team_name, row.points_for)
        for row in sorted(standings_rows, key=lambda r: -r.points_for)[:3]
    ]
    return SeasonLeaders(top_teams, stats.season_top_scorers(box_scores_by_week))


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


def _safe_game_injuries(season: int, week: int) -> list:
    try:
        return nfl_supplemental.get_game_injuries(season, week)
    except Exception as exc:  # noqa: BLE001 - should never take down the whole report
        print(f"warning: in-game injury lookup failed ({exc}); omitting from letter context.")
        return []


def _safe_casualty_report(
    league, week: int, box_scores_by_week: dict[int, list], team_order: list[str]
) -> casualties.CasualtyReport | None:
    # Only the latest completed week: a backfill can't trust today's ESPN injury statuses.
    if not _is_current_report(league, week):
        return None
    try:
        weeks = sorted(box_scores_by_week)
        left_game = {
            w: {c.espn_id for c in nfl_supplemental.get_game_injuries(league.year, w) if c.espn_id is not None}
            for w in weeks
        }
        draft = league.draft or []
        return casualties.casualty_report(
            box_scores_by_week,
            nfl_supplemental.get_injury_designations_by_week(league.year, weeks),
            nfl_supplemental.get_reserve_by_week(league.year, weeks),
            left_game,
            {pick.playerId: (pick.team.team_name, pick.round_num) for pick in draft},
            max((pick.round_num for pick in draft), default=0),
            team_order,
        )
    except Exception as exc:  # noqa: BLE001 - a supplemental section should never take down the report
        print(f"warning: Casualty Report unavailable ({exc}); omitting it.")
        return None


def _safe_history(league, week: int, history_dir, refresh: bool) -> tuple[list[dict] | None, history.LifetimeStats | None]:
    """(every season's snapshot, lifetime stats) -- the snapshots also feed the preview's
    head-to-head records. (None, None) if there's no history dir or loading fails."""
    if not history_dir:
        return None, None
    try:
        seasons = history.load_seasons(
            league, week, lambda year: espn_client.connect(year=year), history_dir, refresh=refresh
        )
        return seasons, history.lifetime_stats(seasons)
    except Exception as exc:  # noqa: BLE001 - an appendix should never take down the report
        print(f"warning: lifetime stats unavailable ({exc}); omitting Appendix B.")
        return None, None


def _is_current_report(league, week: int) -> bool:
    """True when `week` is the latest completed week and another follows it -- the only time
    next-week sections (preview, pickups) describe something a reader can still act on."""
    return week == league.current_week - 1 and week < league.finalScoringPeriod


def _team_contexts(espn_teams: list, standings_rows: list, box_scores: list) -> dict[str, preview.TeamContext]:
    streaks = {row.team_name: row.streak for row in standings_rows}
    last_results = {}
    for bs in box_scores:
        for team, mine, theirs in (
            (bs.home_team, bs.home_score, bs.away_score), (bs.away_team, bs.away_score, bs.home_score),
        ):
            outcome = "W" if mine > theirs else ("L" if mine < theirs else "T")
            last_results[team.team_name] = f"{outcome} {mine:.2f}–{theirs:.2f}"
    contexts = {}
    for t in espn_teams:
        owner = (t.owners or [{}])[0]
        games = t.wins + t.losses + t.ties
        contexts[t.team_name] = preview.TeamContext(
            team_name=t.team_name,
            abbrev=t.team_abbrev,
            manager=f'{owner.get("firstName", "")} {owner.get("lastName", "")}'.strip(),
            owner_id=owner.get("id"),
            wins=t.wins, losses=t.losses, ties=t.ties,
            streak=streaks.get(t.team_name, "-"),
            seed=t.standing,
            average=t.points_for / games if games else 0.0,
            last_result=last_results.get(t.team_name, ""),
        )
    return contexts


def _safe_preview(league, week: int, contexts: dict, seasons: list[dict] | None) -> preview.Preview | None:
    if not _is_current_report(league, week):
        return None
    try:
        h2h = (lambda a, b: history.head_to_head(seasons, a, b)) if seasons else None
        matchups = preview.matchup_previews(espn_client.get_box_scores(league, week + 1), contexts, h2h)
        picks = preview.pick_highlights(
            matchups, league.settings.playoff_team_count,
            include_playoff_pick=week + 1 <= league.settings.reg_season_count,
        )
        return preview.Preview(week + 1, matchups, picks)
    except Exception as exc:  # noqa: BLE001 - a supplemental section should never take down the report
        print(f"warning: Week {week + 1} preview unavailable ({exc}); omitting it.")
        return None


def _week_points(players: list, week: int) -> dict[int, float]:
    """playerId -> points in `week`, from espn_api player cards (Player.stats[week]["points"])."""
    points = {}
    for p in players:
        pts = (getattr(p, "stats", {}) or {}).get(week, {}).get("points")
        if pts is not None:
            points[p.playerId] = pts
    return points


def _safe_waiver_report_card(league, week: int, box_scores: list) -> waivers.WaiverReportCard | None:
    try:
        end = nfl_supplemental.week_end_time(league.year, week)
        start = nfl_supplemental.week_end_time(league.year, week - 1) if week > 1 else None
        activity = espn_client.get_recent_activity(league, since=start)
        on_lineups = {p.playerId for bs in box_scores for p in bs.home_lineup + bs.away_lineup}
        # Players on no lineup at week's end (dropped and still unclaimed, or flipped again) need
        # their week looked up separately -- one batched request.
        missing = {
            player.playerId
            for act in activity if waivers.in_window(act, start, end)
            for _, _, player, *_ in act.actions
            if player.playerId not in on_lineups
        }
        points = _week_points(espn_client.get_player_info(league, sorted(missing)), week)
        current_rosters = {p.playerId: t.team_name for t in league.teams for p in t.roster}
        return waivers.waiver_report_card(activity, box_scores, start, end, points.get, current_rosters)
    except Exception as exc:  # noqa: BLE001 - a supplemental section should never take down the report
        print(f"warning: waiver report card unavailable ({exc}); omitting it.")
        return None


def _safe_pickups(league, week: int) -> list[waivers.Pickup]:
    if not _is_current_report(league, week):
        return []
    try:
        by_position = {
            pos: espn_client.get_free_agents(league, week + 1, pos) for pos in waivers.PICKUP_POSITIONS
        }
        pickups = waivers.suggested_pickups(by_position)
        # Last week's points aren't in the free-agent payload; fill them in for just the picks.
        points = _week_points(espn_client.get_player_info(league, [p.player_id for p in pickups]), week)
        for pick in pickups:
            pick.last_week_points = points.get(pick.player_id)
        return pickups
    except Exception as exc:  # noqa: BLE001 - a supplemental section should never take down the report
        print(f"warning: suggested pickups unavailable ({exc}); omitting them.")
        return []


def build_week_report(
    league,
    week: int | None = None,
    power_rankings_override_path: str | Path | None = None,
    history_dir: str | Path | None = None,
    refresh_history: bool = False,
) -> WeekReport:
    week = espn_client.resolve_target_week(league, week)
    ensure_power_rankings_override(league, week, power_rankings_override_path)
    # One fetch per week 1..N (~0.6s each): this week, last week (improvement/drop-off), and the
    # full run of weeks for season-to-date leaders.
    box_scores_by_week = espn_client.get_box_scores_through(league, week)
    box_scores = box_scores_by_week[week]
    current_scores = stats.team_scores(box_scores)

    prior_scores: dict[str, float] = {}
    if week > 1:
        prior_scores = stats.team_scores(box_scores_by_week[week - 1])

    matchups = []
    for bs in box_scores:
        overperformer, underperformer = stats.matchup_standout_performers(bs)
        matchups.append(
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
                overperformer=overperformer,
                underperformer=underperformer,
            )
        )

    espn_teams = espn_client.get_standings(league)
    power_rankings = espn_client.get_power_rankings(league, week)
    power_rank_by_team = {team.team_name: i + 1 for i, (_, team) in enumerate(power_rankings)}
    commissioner_override = load_power_rankings_override(power_rankings_override_path, week)

    prior_power, prior_commissioner = _prior_week_ranks(league, week, power_rankings_override_path)

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
        row = standings_rows[-1]
        row.power_rank_change = rank_change(prior_power.get(row.team_name), row.power_rank)
        row.commissioner_rank_change = rank_change(prior_commissioner.get(row.team_name), row.commissioner_rank)
    standings_rows.sort(key=lambda row: (-row.wins, row.losses, -row.points_for))

    best, worst = stats.best_worst_team(box_scores)
    most_improved, biggest_dropoff = stats.most_improved_biggest_dropoff(current_scores, prior_scores)
    closest, blowout = stats.closest_win_biggest_blowout(box_scores)
    win_streak, loss_streak = stats.longest_streaks(espn_teams, week)
    upset = stats.biggest_upset(box_scores)
    underachiever = stats.biggest_underachiever(box_scores)
    luckiest_win, unluckiest_loss = stats.luckiest_win_unluckiest_loss(box_scores)

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
        "Luckiest Win": luckiest_win,
        "Unluckiest Loss": unluckiest_loss,
    }
    team_highlights = {k: v for k, v in team_highlights.items() if v is not None}

    mvp = stats.individual_mvp(box_scores)
    top_by_position = stats.top_scorer_by_position(box_scores)
    bench = stats.bench_mvp(box_scores)
    rookie = stats.rookie_spotlight(box_scores, _safe_rookie_candidates(league.year, week))
    gamecock = stats.gamecock_of_the_week(box_scores, _safe_gamecock_candidates(league.year, week))
    injuries = stats.notable_injuries(box_scores, _safe_game_injuries(league.year, week))

    individual_highlights = ordered_individual_highlights(mvp, top_by_position, bench, rookie, gamecock)
    seasons, lifetime = _safe_history(league, week, history_dir, refresh_history)

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
        score_bars=stats.score_bars(box_scores),
        season_leaders=_build_season_leaders(standings_rows, box_scores_by_week, week),
        injuries=injuries,
        season_table=stats.season_team_table(box_scores_by_week, league.settings.position_slot_counts),
        lifetime=lifetime,
        waiver_report_card=_safe_waiver_report_card(league, week, box_scores),
        pickups=_safe_pickups(league, week),
        casualty_report=_safe_casualty_report(
            league, week, box_scores_by_week, [row.team_name for row in standings_rows]
        ),
        preview=_safe_preview(league, week, _team_contexts(espn_teams, standings_rows, box_scores), seasons),
    )
