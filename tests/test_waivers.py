"""Unit tests for src/waivers.py (Waiver Report Card, Suggested Pickups) and the week-end helper
it relies on, against the fake espn_api shapes from tests/test_stats.py."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import nfl_supplemental, waivers
from tests.test_stats import FakeBoxScore, FakePlayer, FakeTeam

START = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


def _act(when, *actions):
    return SimpleNamespace(date=when.timestamp() * 1000, actions=list(actions))


def _p(name, pid, position="WR", pro_team="SF"):
    return SimpleNamespace(name=name, playerId=pid, position=position, proTeam=pro_team)


def _card(activity, lookup=None, rosters=None):
    stark, lannister = FakeTeam("House Stark"), FakeTeam("House Lannister")
    bs = FakeBoxScore(
        stark, 100.0, 100.0, lannister, 90.0, 90.0,
        home_lineup=[
            FakePlayer("Starter Add", "WR", 21.0, "WR", player_id=1),
            FakePlayer("Bench Add", "RB", 13.0, "BE", player_id=2),
        ],
        away_lineup=[FakePlayer("Stark Castoff", "TE", 18.0, "TE", player_id=3)],
    )
    return waivers.waiver_report_card(activity, [bs], START, END, (lookup or {}).get, rosters or {})


def test_grades_by_points():
    assert [waivers.grade(p) for p in (20, 12, 6, 0.1, 0, -2, None)] == ["A", "B", "C", "D", "F", "F", "—"]


def test_report_card_grades_adds_in_window_and_flags_regret_drops():
    stark = FakeTeam("House Stark")
    mid = datetime(2026, 9, 24, tzinfo=timezone.utc)
    activity = [
        _act(mid, (stark, "WAIVER ADDED", _p("Starter Add", 1), 0), (stark, "DROPPED", _p("Stark Castoff", 3, "TE"), 0)),
        _act(mid, (stark, "FA ADDED", _p("Bench Add", 2, "RB"), 0)),
        _act(mid, (stark, "FA ADDED", _p("Flipped Again", 4), 0)),  # on no lineup now -> lookup
        _act(datetime(2026, 9, 29, 12, tzinfo=timezone.utc), (stark, "FA ADDED", _p("Too Late", 5), 0)),
        _act(datetime(2026, 9, 22, 9, tzinfo=timezone.utc), (stark, "FA ADDED", _p("Too Early", 6), 0)),
    ]
    rosters = {1: "House Stark", 2: "House Lannister"}  # today: 1 kept, 2 traded away, 4 dropped
    card = _card(activity, lookup={4: 2.5}, rosters=rosters)
    assert [(a.player_name, a.points, a.started, a.grade, a.status, a.current_team) for a in card.adds] == [
        ("Starter Add", 21.0, True, "A", "rostered", "House Stark"),
        ("Bench Add", 13.0, False, "B", "elsewhere", "House Lannister"),
        ("Flipped Again", 2.5, None, "D", "dropped", None),
    ]
    assert card.drops == 1
    assert [(r.player_name, r.points) for r in card.regrets] == [("Stark Castoff", 18.0)]  # scored for Lannister


def test_report_card_unknown_points_sort_last_and_small_drops_are_not_regrets():
    stark = FakeTeam("House Stark")
    mid = datetime(2026, 9, 24, tzinfo=timezone.utc)
    card = _card([
        _act(mid, (stark, "FA ADDED", _p("Unknown", 9), 0), (stark, "DROPPED", _p("Meh", 8), 0)),
        _act(mid, (stark, "FA ADDED", _p("Bench Add", 2, "RB"), 0)),
    ], lookup={8: 14.9})
    assert [a.player_name for a in card.adds] == ["Bench Add", "Unknown"]
    assert card.adds[1].grade == "—" and card.regrets == []


def _fa(name, pid, position, projected, pro_team="SF", status="ACTIVE", owned=5.0):
    return SimpleNamespace(
        name=name, playerId=pid, position=position, proTeam=pro_team, projected_points=projected,
        injuryStatus=status, percent_owned=owned,
    )


def test_suggested_pickups_rank_by_projection_and_skip_unavailable():
    by_pos = {
        "RB": [
            _fa("Low", 1, "RB", 4.0), _fa("High", 2, "RB", 11.0, pro_team="DAL"),
            _fa("Out", 3, "RB", 15.0, status="OUT"), _fa("Mid", 4, "RB", 8.0), _fa("Bye", 5, "RB", 0.0),
        ],
        "K": [_fa("Kicker", 6, "K", 7.0)],
        "D/ST": [_fa("Defense", 7, "D/ST", 6.0, status=[])],  # espn_api's D/ST status shape
    }
    picks = waivers.suggested_pickups(by_pos)
    assert [(p.player_name, p.position) for p in picks] == [
        ("High", "RB"), ("Mid", "RB"), ("Defense", "D/ST"), ("Kicker", "K"),
    ]


def test_week_end_is_morning_after_last_game_day_eastern():
    end = nfl_supplemental.week_end_from_game_days(["2026-09-24", "2026-09-28", "2026-09-27"])
    assert end.isoformat() == "2026-09-29T06:00:00-04:00"
