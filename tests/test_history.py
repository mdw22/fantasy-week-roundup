"""Unit tests for src/history.py against hand-written season dicts and fake League objects."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import history


def _game(week, opp, pf, pa, playoff=False):
    return {"week": week, "opp_owner_id": opp, "pf": pf, "pa": pa, "playoff": playoff}


def _team(oid, team_name, standing, final, games):
    return {
        "owner_id": oid, "owner_name": f"Manager {oid}", "team_name": team_name, "abbrev": oid,
        "standing": standing, "final_standing": final, "games": games,
    }


def _seasons():
    # 2024 (complete): A beats B and C, wins the title in a week-3 playoff game.
    # 2025 (in progress): B beats A twice; A renamed their team.
    s2024 = {
        "season": 2024, "reg_season_count": 2, "playoff_team_count": 2, "complete": True,
        "teams": [
            _team("A", "Team A", 1, 1, [_game(1, "B", 100, 90), _game(2, "C", 120, 60), _game(3, "B", 50, 40, True)]),
            _team("B", "Team B", 2, 2, [_game(1, "A", 90, 100), _game(2, "D", 80, 79.5), _game(3, "A", 40, 50, True)]),
            _team("C", "Team C", 3, 3, [_game(1, "D", 80, 70), _game(2, "A", 60, 120)]),
            _team("D", "Team D", 4, 4, [_game(1, "C", 70, 80), _game(2, "B", 79.5, 80)]),
        ],
    }
    s2025 = {
        "season": 2025, "reg_season_count": 14, "playoff_team_count": 2, "complete": False,
        "teams": [
            _team("A", "A Renamed", 3, 0, [_game(1, "B", 100, 110), _game(2, "B", 101, 105)]),
            _team("B", "Team B", 1, 0, [_game(1, "A", 110, 100), _game(2, "A", 105, 101)]),
            _team("C", "Team C", 2, 0, [_game(1, "D", 90, 95), _game(2, "D", 70, 62)]),
            _team("D", "Team D", 4, 0, [_game(1, "C", 95, 90), _game(2, "C", 62, 70)]),
        ],
    }
    return [s2024, s2025]


def test_head_to_head_counts_regular_season_only():
    assert history.head_to_head(_seasons(), "A", "B") == (1, 2, 0)  # the playoff win isn't counted


def test_manager_records_merge_renames_and_exclude_playoffs():
    stats = history.lifetime_stats(_seasons())
    by_id = {m.owner_id: m for m in stats.managers}
    a = by_id["A"]
    assert (a.wins, a.losses, a.ties) == (2, 2, 0)
    assert a.points_for == 421 and a.seasons == 2
    assert a.team_name == "A Renamed"  # most recent name
    assert a.titles == 1 and a.playoff_apps == 1  # the in-progress season counts neither
    assert [m.owner_id for m in stats.managers][0] == "B"  # 3-1, best win %
    assert (stats.first_season, stats.last_season) == (2024, 2025)


def test_champions_only_from_completed_seasons():
    champs = history.lifetime_stats(_seasons()).champions
    assert [(c.season, c.team_name) for c in champs] == [(2024, "Team A")]


def test_rivalries_need_two_meetings_and_a_clear_edge():
    rivals = {r.manager: r for r in history.lifetime_stats(_seasons()).rivalries}
    assert (rivals["Manager A"].rival, rivals["Manager A"].nemesis) == (None, "Manager B")
    assert rivals["Manager A"].nemesis_record == "1-2"
    assert (rivals["Manager B"].rival, rivals["Manager B"].rival_record) == ("Manager A", "2-1")
    assert rivals["Manager C"].rival == "Manager D"
    assert rivals["Manager D"].nemesis == "Manager C"


def test_record_book():
    book = {e.label: e for e in history.lifetime_stats(_seasons()).record_book}
    assert (book["Highest single-week score"].value, book["Highest single-week score"].when) == ("120.00", "2024 Week 2")
    assert book["Lowest single-week score"].value == "60.00"
    assert book["Biggest blowout"].value == "60.00" and book["Biggest blowout"].detail == "over Manager C"
    assert book["Closest win"].value == "0.50" and book["Closest win"].manager == "Manager B"
    assert (book["Best regular season"].value, book["Best regular season"].when) == ("2-0", "2024")
    assert book["Most points in a season"].value == "220.00"


def _fake_league(year, previous=None):
    settings = SimpleNamespace(reg_season_count=1, playoff_team_count=1)
    a = SimpleNamespace(team_name="Team A", team_abbrev="A", standing=1, final_standing=1,
                        owners=[{"id": "A", "firstName": "Ann", "lastName": "A"}])
    b = SimpleNamespace(team_name="Team B", team_abbrev="B", standing=2, final_standing=2,
                        owners=[{"id": "B", "firstName": "Bo", "lastName": "B"}])
    a.schedule, a.scores, a.outcomes, a.mov = [b, b, b], [100.0, 90.0, 0.0], ["W", "L", "U"], [10.0, -5.0, 0.0]
    b.schedule, b.scores, b.outcomes, b.mov = [a, a, a], [90.0, 95.0, 0.0], ["L", "W", "U"], [-10.0, 5.0, 0.0]
    return SimpleNamespace(year=year, settings=settings, teams=[a, b], previousSeasons=previous or [])


def test_season_snapshot_uses_margin_for_points_against_and_marks_playoffs():
    snap = history.season_snapshot(_fake_league(2024))
    a = snap["teams"][0]
    assert a["owner_name"] == "Ann A" and snap["complete"] is True
    assert a["games"] == [_game(1, "B", 100.0, 90.0), _game(2, "B", 90.0, 95.0, True)]  # week 3 unplayed


def test_season_snapshot_through_week_stops_early_and_is_incomplete():
    snap = history.season_snapshot(_fake_league(2026), through_week=1)
    assert snap["complete"] is False
    assert [g["week"] for g in snap["teams"][0]["games"]] == [1]


def test_load_seasons_caches_past_seasons(tmp_path):
    calls = []

    def connect(year):
        calls.append(year)
        return _fake_league(year)

    current = _fake_league(2026, previous=[2024, 2025])
    seasons = history.load_seasons(current, 1, connect, tmp_path)
    assert [s["season"] for s in seasons] == [2024, 2025, 2026]
    assert calls == [2024, 2025] and (tmp_path / "2024.json").exists()

    history.load_seasons(current, 1, connect, tmp_path)
    assert calls == [2024, 2025]  # served from cache the second time

    history.load_seasons(current, 1, connect, tmp_path, refresh=True)
    assert calls == [2024, 2025, 2024, 2025]


def test_co_owner_ids_merge_into_one_manager():
    seasons = _seasons()
    # In 2025, D's team gains a second account listed first (as ESPN did for a real co-owned team).
    d2025 = seasons[1]["teams"][3]
    d2025["owner_id"], d2025["owner_ids"] = "D2", ["D2", "D"]
    for team in seasons[1]["teams"]:
        for g in team["games"]:
            if g["opp_owner_id"] == "D":
                g["opp_owner_id"] = "D2"
    stats = history.lifetime_stats(seasons)
    ds = [m for m in stats.managers if m.name == "Manager D"]
    assert len(ds) == 1 and ds[0].owner_id == "D" and ds[0].seasons == 2 and ds[0].active
    assert (ds[0].wins, ds[0].losses) == (1, 3)
    assert history.head_to_head(seasons, "C", "D2") == history.head_to_head(seasons, "C", "D") == (2, 1, 0)
