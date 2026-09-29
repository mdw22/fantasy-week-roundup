"""League history across seasons, for Appendix B (Lifetime Stats) and head-to-head lookups.

Each completed season is snapshotted once to data/history/<year>.json (committed -- a finished
season never changes, so there's no reason to re-download it every week); the current season is
snapshotted live through the report week. Managers are keyed by ESPN owner ID rather than team
name, so a manager who renames their team between seasons still has one continuous record. A
co-owned team lists several owner IDs (one person can even hold two ESPN accounts); IDs that ever
shared a team are merged into one manager, keyed by whichever ID appeared first.

Rules: records, head-to-head and the record book count regular-season games only (ESPN's playoff
weeks also include consolation games, which would muddy "all-time record"). Titles come from
final_standing == 1 and playoff appearances from the regular-season seed, both only for completed
seasons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


def season_snapshot(league, through_week: int | None = None) -> dict:
    """A plain-dict record of one season: per team, owner identity and every played game.
    `through_week` limits an in-progress season to weeks already reported; None marks the season
    complete. Points against come from espn_api's per-game margin (`mov`), which avoids relying on
    the opponent's schedule lining up index-for-index."""
    reg = league.settings.reg_season_count
    teams = []
    for t in league.teams:
        owner = (t.owners or [{}])[0]
        games = []
        for i, (opp, pf, outcome, mov) in enumerate(zip(t.schedule, t.scores, t.outcomes, t.mov)):
            week = i + 1
            if outcome == "U" or (through_week is not None and week > through_week):
                continue
            opp_owner = (getattr(opp, "owners", None) or [{}])[0]
            games.append({
                "week": week,
                "opp_owner_id": opp_owner.get("id"),
                "pf": round(pf, 2),
                "pa": round(pf - mov, 2),
                "playoff": week > reg,
            })
        name = f'{owner.get("firstName", "")} {owner.get("lastName", "")}'.strip()
        teams.append({
            "owner_id": owner.get("id"),
            "owner_ids": [o.get("id") for o in (t.owners or []) if o.get("id")],
            "owner_name": name or t.team_name,
            "team_name": t.team_name,
            "abbrev": t.team_abbrev,
            "standing": t.standing,
            "final_standing": t.final_standing,
            "games": games,
        })
    return {
        "season": league.year,
        "reg_season_count": reg,
        "playoff_team_count": league.settings.playoff_team_count,
        "complete": through_week is None,
        "teams": teams,
    }


def load_seasons(
    current_league,
    through_week: int,
    connect_year: Callable[[int], object],
    history_dir: str | Path,
    refresh: bool = False,
) -> list[dict]:
    """Every season oldest first: cached past seasons (fetched and written on first use, or when
    `refresh` is set) followed by the live current season through `through_week`."""
    history_dir = Path(history_dir)
    seasons = []
    for year in sorted(getattr(current_league, "previousSeasons", None) or []):
        path = history_dir / f"{year}.json"
        if refresh or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(season_snapshot(connect_year(year)), indent=2) + "\n")
        seasons.append(json.loads(path.read_text()))
    seasons.append(season_snapshot(current_league, through_week))
    return seasons


@dataclass
class ManagerRecord:
    owner_id: str
    name: str
    team_name: str  # their most recent team name
    active: bool  # in the current season
    seasons: int
    wins: int
    losses: int
    ties: int
    points_for: float
    games: int
    titles: int
    playoff_apps: int

    @property
    def win_pct(self) -> float:
        return (self.wins + 0.5 * self.ties) / self.games if self.games else 0.0

    @property
    def average(self) -> float:
        return self.points_for / self.games if self.games else 0.0


@dataclass
class Champion:
    season: int
    manager: str
    team_name: str


@dataclass
class Rivalry:
    manager: str
    team_name: str
    rival: str | None  # opponent manager this manager has the best record against (> .500)
    rival_record: str
    nemesis: str | None  # opponent this manager has the worst record against (< .500)
    nemesis_record: str


@dataclass
class RecordEntry:
    label: str
    value: str
    manager: str
    team_name: str
    when: str
    detail: str = ""


@dataclass
class LifetimeStats:
    first_season: int
    last_season: int
    managers: list[ManagerRecord]
    champions: list[Champion]
    rivalries: list[Rivalry]
    record_book: list[RecordEntry]


def canonical_owner_ids(seasons: list[dict]) -> dict[str, str]:
    """owner_id -> the manager's canonical ID. IDs listed on the same team in any season are one
    manager; the canonical ID is whichever of them appears first (oldest season, team order)."""
    parent: dict[str, str] = {}
    order: dict[str, int] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for season in seasons:
        for team in season["teams"]:
            ids = team.get("owner_ids") or [team["owner_id"]]
            for oid in ids:
                parent.setdefault(oid, oid)
                order.setdefault(oid, len(order))
            for oid in ids[1:]:
                a, b = find(ids[0]), find(oid)
                if a != b:
                    first, second = (a, b) if order[a] < order[b] else (b, a)
                    parent[second] = first
    return {oid: find(oid) for oid in parent}


def normalize_owner_ids(seasons: list[dict]) -> list[dict]:
    """Copies of `seasons` with every owner_id / opp_owner_id replaced by its canonical ID."""
    canon = canonical_owner_ids(seasons)
    return [
        {**season, "teams": [
            {**team, "owner_id": canon.get(team["owner_id"], team["owner_id"]), "games": [
                {**g, "opp_owner_id": canon.get(g["opp_owner_id"], g["opp_owner_id"])} for g in team["games"]
            ]}
            for team in season["teams"]
        ]}
        for season in seasons
    ]


def _record(wins: int, losses: int, ties: int = 0) -> str:
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def _regular_games(seasons: list[dict]):
    """(season, team, game) for every regular-season game, from each team's point of view."""
    for season in seasons:
        for team in season["teams"]:
            for game in team["games"]:
                if not game["playoff"]:
                    yield season, team, game


def head_to_head(seasons: list[dict], owner_a: str, owner_b: str) -> tuple[int, int, int]:
    """(a's wins, b's wins, ties) across all regular-season meetings. Either owner may be given by
    any of their IDs."""
    canon = canonical_owner_ids(seasons)
    return _head_to_head(
        normalize_owner_ids(seasons), canon.get(owner_a, owner_a), canon.get(owner_b, owner_b)
    )


def _head_to_head(seasons: list[dict], owner_a: str, owner_b: str) -> tuple[int, int, int]:
    """head_to_head over seasons whose IDs are already canonical."""
    a_wins = b_wins = ties = 0
    for _, team, game in _regular_games(seasons):
        if team["owner_id"] != owner_a or game["opp_owner_id"] != owner_b:
            continue
        if game["pf"] > game["pa"]:
            a_wins += 1
        elif game["pf"] < game["pa"]:
            b_wins += 1
        else:
            ties += 1
    return a_wins, b_wins, ties


def _latest_identity(seasons: list[dict]) -> dict[str, tuple[str, str]]:
    """owner_id -> (manager name, team name) as of the most recent season they played."""
    identity = {}
    for season in seasons:
        for team in season["teams"]:
            identity[team["owner_id"]] = (team["owner_name"], team["team_name"])
    return identity


def _manager_records(seasons: list[dict], identity: dict, active_ids: set) -> list[ManagerRecord]:
    totals: dict[str, dict] = {}
    for season in seasons:
        for team in season["teams"]:
            t = totals.setdefault(team["owner_id"], {
                "seasons": 0, "w": 0, "l": 0, "t": 0, "pf": 0.0, "g": 0, "titles": 0, "po": 0,
            })
            t["seasons"] += 1
            if season["complete"]:
                t["titles"] += 1 if team["final_standing"] == 1 else 0
                t["po"] += 1 if 0 < team["standing"] <= season["playoff_team_count"] else 0
    for _, team, game in _regular_games(seasons):
        t = totals[team["owner_id"]]
        t["g"] += 1
        t["pf"] += game["pf"]
        if game["pf"] > game["pa"]:
            t["w"] += 1
        elif game["pf"] < game["pa"]:
            t["l"] += 1
        else:
            t["t"] += 1
    records = [
        ManagerRecord(
            owner_id=oid, name=identity[oid][0], team_name=identity[oid][1],
            active=oid in active_ids, seasons=t["seasons"], wins=t["w"], losses=t["l"],
            ties=t["t"], points_for=t["pf"], games=t["g"], titles=t["titles"], playoff_apps=t["po"],
        )
        for oid, t in totals.items()
    ]
    records.sort(key=lambda r: (-r.win_pct, -r.points_for))
    return records


def _rivalries(seasons: list[dict], identity: dict, active_ids: set, min_meetings: int = 2) -> list[Rivalry]:
    results = []
    for oid in active_ids:
        opponents = {g["opp_owner_id"] for _, team, g in _regular_games(seasons) if team["owner_id"] == oid}
        scored = []
        # Alphabetical, so equal records tie-break the same way every run (max/min keep the first).
        for opp in sorted(opponents - {None}, key=lambda o: identity.get(o, ("",))[0]):
            if opp == oid:
                continue
            w, l, t = _head_to_head(seasons, oid, opp)
            meetings = w + l + t
            if meetings >= min_meetings:
                scored.append(((w + 0.5 * t) / meetings, meetings, opp, _record(w, l, t)))
        rival = max((s for s in scored if s[0] > 0.5), key=lambda s: (s[0], s[1]), default=None)
        nemesis = min((s for s in scored if s[0] < 0.5), key=lambda s: (s[0], -s[1]), default=None)
        results.append(Rivalry(
            manager=identity[oid][0], team_name=identity[oid][1],
            rival=identity[rival[2]][0] if rival else None, rival_record=rival[3] if rival else "",
            nemesis=identity[nemesis[2]][0] if nemesis else None,
            nemesis_record=nemesis[3] if nemesis else "",
        ))
    results.sort(key=lambda r: r.manager)
    return results


def _record_book(seasons: list[dict], identity: dict) -> list[RecordEntry]:
    games = list(_regular_games(seasons))
    if not games:
        return []

    def who(season, team) -> tuple[str, str]:
        return team["owner_name"], team["team_name"]

    def when(season, game) -> str:
        return f'{season["season"]} Week {game["week"]}'

    def opp_name(game) -> str:
        return identity.get(game["opp_owner_id"], ("?", "?"))[0]

    entries = []
    s, t, g = max(games, key=lambda x: x[2]["pf"])
    entries.append(RecordEntry("Highest single-week score", f'{g["pf"]:.2f}', *who(s, t), when(s, g)))
    s, t, g = min(games, key=lambda x: x[2]["pf"])
    entries.append(RecordEntry("Lowest single-week score", f'{g["pf"]:.2f}', *who(s, t), when(s, g)))

    wins = [x for x in games if x[2]["pf"] > x[2]["pa"]]
    if wins:
        s, t, g = max(wins, key=lambda x: x[2]["pf"] - x[2]["pa"])
        entries.append(RecordEntry(
            "Biggest blowout", f'{g["pf"] - g["pa"]:.2f}', *who(s, t), when(s, g), f"over {opp_name(g)}"
        ))
        s, t, g = min(wins, key=lambda x: x[2]["pf"] - x[2]["pa"])
        entries.append(RecordEntry(
            "Closest win", f'{g["pf"] - g["pa"]:.2f}', *who(s, t), when(s, g), f"over {opp_name(g)}"
        ))

    season_totals = []
    for season in seasons:
        if not season["complete"]:
            continue
        for team in season["teams"]:
            regular = [g for g in team["games"] if not g["playoff"]]
            if not regular:
                continue
            w = sum(1 for g in regular if g["pf"] > g["pa"])
            l = sum(1 for g in regular if g["pf"] < g["pa"])
            ties = len(regular) - w - l
            season_totals.append((season, team, w, l, ties, sum(g["pf"] for g in regular)))
    if season_totals:
        s, t, w, l, ties, pf = max(season_totals, key=lambda x: ((x[2] + 0.5 * x[4]) / (x[2] + x[3] + x[4]), x[5]))
        entries.append(RecordEntry("Best regular season", _record(w, l, ties), *who(s, t), str(s["season"])))
        s, t, w, l, ties, pf = max(season_totals, key=lambda x: x[5])
        entries.append(RecordEntry("Most points in a season", f"{pf:.2f}", *who(s, t), str(s["season"])))
    return entries


def lifetime_stats(seasons: list[dict]) -> LifetimeStats:
    seasons = normalize_owner_ids(seasons)
    identity = _latest_identity(seasons)
    active_ids = {t["owner_id"] for t in seasons[-1]["teams"]}
    champions = [
        Champion(season["season"], team["owner_name"], team["team_name"])
        for season in seasons
        if season["complete"]
        for team in season["teams"]
        if team["final_standing"] == 1
    ]
    return LifetimeStats(
        first_season=seasons[0]["season"],
        last_season=seasons[-1]["season"],
        managers=_manager_records(seasons, identity, active_ids),
        champions=champions,
        rivalries=_rivalries(seasons, identity, active_ids),
        record_book=_record_book(seasons, identity),
    )
