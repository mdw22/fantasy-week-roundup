"""II. Week N+1 Preview: next week's projected matchups, rule-based highlight picks, and a data card
per matchup. No generated text here -- the only prose in the preview is the Bold Prediction, which
comes from the letter call (narrative.py).

Pure functions over next week's espn_api box scores plus a per-team TeamContext that report_data
assembles from standings, this week's results and league history. Projections reflect lineups as
of the report (Tuesday); managers may still change them.

Pick and reason strings deliberately name no teams: the template renders team names itself (through
its nickname overrides and name cleanup), next to the reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .stats import BENCH_SLOTS, _ordinal

TOP_PLAYERS_PER_SIDE = 3
# Projected-margin bands for the compact (Standard Weekly) card's one-line takeaway.
TOSS_UP_GAP = 3.0
CLEAR_FAVORITE_GAP = 10.0
# Starter statuses worth a warning on the card, and how to label them.
STATUS_FLAGS = {
    "OUT": "Out",
    "DOUBTFUL": "Doubtful",
    "QUESTIONABLE": "Questionable",
    "INJURY_RESERVE": "IR",
    "SUSPENSION": "Suspended",
}
# Players parked in an IR slot are only worth a mention when they might come back this week.
IR_SLOT_RETURN_STATUSES = {"QUESTIONABLE", "DOUBTFUL"}


@dataclass
class TeamContext:
    team_name: str
    abbrev: str
    manager: str
    owner_id: str | None
    wins: int
    losses: int
    ties: int
    streak: str
    seed: int
    average: float  # season points per game
    last_result: str  # e.g. "W 120.50–98.20"; "" in Week 1

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ties}" if self.ties else f"{self.wins}-{self.losses}"


@dataclass
class PlayerLine:
    name: str
    position: str
    pro_team: str
    projected: float
    flag: str | None = None
    in_ir_slot: bool = False


@dataclass
class PreviewSide:
    team: TeamContext
    projected: float
    top_players: list[PlayerLine]
    # Starters who are out, doubtful, questionable, on IR or on bye, then IR-slot players who are
    # questionable or doubtful (i.e. might return).
    flagged: list[PlayerLine]


@dataclass
class MatchupPreview:
    home: PreviewSide
    away: PreviewSide
    # (home wins, away wins, ties), regular season, all seasons; None if history is unavailable.
    head_to_head: tuple[int, int, int] | None = None

    @property
    def favorite(self) -> PreviewSide:
        return self.home if self.home.projected >= self.away.projected else self.away

    @property
    def underdog(self) -> PreviewSide:
        return self.away if self.favorite is self.home else self.home

    @property
    def gap(self) -> float:
        return abs(self.home.projected - self.away.projected)

    @property
    def closeness(self) -> str:
        """"toss-up", "edge" or "clear" by projected margin (see TOSS_UP_GAP, CLEAR_FAVORITE_GAP)."""
        if self.gap < TOSS_UP_GAP:
            return "toss-up"
        return "edge" if self.gap < CLEAR_FAVORITE_GAP else "clear"

    @property
    def combined_wins(self) -> int:
        return self.home.team.wins + self.away.team.wins


@dataclass
class PreviewPick:
    label: str
    matchup: MatchupPreview
    reason: str
    team_name: str | None = None  # the team the pick is about (Upset Alert's underdog), if one


@dataclass
class Preview:
    week: int
    matchups: list[MatchupPreview]
    picks: list[PreviewPick]
    bold_prediction: str | None = None  # from the letter call; filled in by main.py


def starter_flag(player) -> str | None:
    if getattr(player, "on_bye_week", False):
        return "Bye"
    status = player.injuryStatus if isinstance(player.injuryStatus, str) else ""
    return STATUS_FLAGS.get(status)


def preview_side(team: TeamContext, projected: float, lineup: list) -> PreviewSide:
    starters = [p for p in lineup if p.lineupSlot not in BENCH_SLOTS]
    ir_returns = [p for p in lineup if p.lineupSlot == "IR" and p.injuryStatus in IR_SLOT_RETURN_STATUSES]

    def line(p) -> PlayerLine:
        return PlayerLine(
            p.name, p.position, p.proTeam, p.projected_points or 0.0, starter_flag(p), p.lineupSlot == "IR"
        )

    top = sorted(starters, key=lambda p: -(p.projected_points or 0.0))[:TOP_PLAYERS_PER_SIDE]
    flagged = [line(p) for p in starters if starter_flag(p)] + [line(p) for p in ir_returns]
    return PreviewSide(team, projected, [line(p) for p in top], flagged)


def matchup_previews(
    box_scores: list,
    contexts: dict[str, TeamContext],
    head_to_head: Callable[[str, str], tuple[int, int, int]] | None = None,
) -> list[MatchupPreview]:
    """One MatchupPreview per box score of the upcoming week. Byes (no away team) are skipped."""
    previews = []
    for bs in box_scores:
        if not getattr(bs, "away_team", None) or not getattr(bs, "home_team", None):
            continue
        home = contexts[bs.home_team.team_name]
        away = contexts[bs.away_team.team_name]
        h2h = None
        if head_to_head and home.owner_id and away.owner_id:
            h2h = head_to_head(home.owner_id, away.owner_id)
        previews.append(MatchupPreview(
            preview_side(home, bs.home_projected, bs.home_lineup),
            preview_side(away, bs.away_projected, bs.away_lineup),
            h2h,
        ))
    return previews


def _games_back(team: TeamContext, line_team: TeamContext) -> float:
    return ((line_team.wins - team.wins) + (team.losses - line_team.losses)) / 2


def _seed_phrase(team: TeamContext, line_team: TeamContext | None, playoff_spots: int) -> str:
    phrase = f"No. {team.seed} ({team.record})"
    if line_team is None or team.seed <= playoff_spots:
        return phrase
    back = _games_back(team, line_team)
    if back <= 0:
        return f"{phrase}, tied with the {_ordinal(playoff_spots)} seed"
    return f"{phrase}, {back:g} game{'s' if back != 1 else ''} back of the {_ordinal(playoff_spots)} seed"


def pick_highlights(
    matchups: list[MatchupPreview],
    playoff_spots: int,
    include_playoff_pick: bool = True,
) -> list[PreviewPick]:
    """Game of the Week, Blowout Watch, Upset Alert and Biggest Playoff Implications, each on a
    different matchup where possible. Chosen in order of how specific the rule is (playoff line
    first, blowout last), then returned in display order."""
    if not matchups:
        return []
    used: list[MatchupPreview] = []

    def choose(candidates, key):
        fresh = [m for m in candidates if all(m is not u for u in used)]
        pool = fresh or candidates
        if not pool:
            return None
        best = min(pool, key=key)
        used.append(best)
        return best

    picks: dict[str, PreviewPick] = {}

    if include_playoff_pick:
        teams = [side.team for m in matchups for side in (m.home, m.away)]
        line_team = next((t for t in teams if t.seed == playoff_spots), None)

        def distance(seed: int) -> int:  # seeds P and P+1 are both 1 from the line
            return seed - playoff_spots if seed > playoff_spots else playoff_spots + 1 - seed

        m = choose(matchups, lambda m: (distance(m.home.team.seed) + distance(m.away.team.seed), m.gap))
        if m:
            hi, lo = sorted((m.home.team, m.away.team), key=lambda t: t.seed)
            picks["Biggest Playoff Implications"] = PreviewPick(
                "Biggest Playoff Implications", m,
                f"{_seed_phrase(hi, line_team, playoff_spots)} vs. {_seed_phrase(lo, line_team, playoff_spots)}; "
                f"the top {playoff_spots} make the playoffs.",
            )

    m = choose(matchups, lambda m: (-m.combined_wins, m.gap))
    if m:
        picks["Game of the Week"] = PreviewPick(
            "Game of the Week", m,
            f"Combined record {m.combined_wins}-{m.home.team.losses + m.away.team.losses}, "
            f"projected {m.gap:.2f} points apart.",
        )

    out_averaging = [
        m for m in matchups
        if m.underdog.team.average > m.favorite.team.average and all(m is not u for u in used)
    ]
    m = choose(out_averaging, lambda m: -(m.underdog.team.average - m.favorite.team.average)) if out_averaging else None
    if m:
        diff = m.underdog.team.average - m.favorite.team.average
        picks["Upset Alert"] = PreviewPick(
            "Upset Alert", m,
            f"Projected to lose by {m.gap:.2f}, but averages {diff:.2f} more points a week.",
            m.underdog.team.team_name,
        )
    else:
        m = choose(matchups, lambda m: m.gap)
        if m:
            picks["Upset Alert"] = PreviewPick(
                "Upset Alert", m, f"Projected to lose by just {m.gap:.2f}.", m.underdog.team.team_name,
            )

    m = choose(matchups, lambda m: -m.gap)
    if m:
        picks["Blowout Watch"] = PreviewPick(
            "Blowout Watch", m, f"Widest projected margin of the week: {m.gap:.2f} points."
        )

    order = ["Game of the Week", "Blowout Watch", "Upset Alert", "Biggest Playoff Implications"]
    return [picks[label] for label in order if label in picks]
