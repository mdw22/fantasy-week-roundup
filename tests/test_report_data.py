"""Unit tests for the pure helpers in src/report_data.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import report_data


def test_individual_highlights_display_order():
    top = {pos: f"top-{pos}" for pos in ["K", "D/ST", "TE", "WR", "RB", "QB"]}  # scrambled input
    result = report_data.ordered_individual_highlights("mvp", top, "bench", "rookie", "gamecock")
    assert list(result) == [
        "Individual MVP", "Top QB", "Top RB", "Top WR", "Top TE", "Top D/ST", "Top K",
        "Bench MVP", "Rookie Spotlight", "Gamecock of the Week",
    ]


def test_individual_highlights_drops_missing_awards_and_positions():
    result = report_data.ordered_individual_highlights(
        "mvp", {"WR": "w", "QB": "q"}, None, None, "gamecock"
    )
    assert list(result) == ["Individual MVP", "Top QB", "Top WR", "Gamecock of the Week"]


def test_individual_highlights_unknown_positions_go_after_known_alphabetically():
    result = report_data.ordered_individual_highlights(
        "mvp", {"K": "k", "LB": "lb", "DL": "dl", "QB": "q"}, None, None, None
    )
    assert list(result) == ["Individual MVP", "Top QB", "Top K", "Top DL", "Top LB"]


def test_rank_change_positive_is_improvement_and_missing_data_is_none():
    assert report_data.rank_change(4, 2) == 2      # 4th -> 2nd: moved up two
    assert report_data.rank_change(2, 5) == -3     # fell three
    assert report_data.rank_change(3, 3) == 0      # unchanged
    assert report_data.rank_change(None, 3) is None  # no prior week (Week 1)
    assert report_data.rank_change(3, None) is None


def test_season_leaders_suppressed_in_week_one_and_built_from_week_two():
    rows = [
        report_data.StandingsRow(n, "D", 1, 0, 0, pf, 0.0, "1W", None, 1, 1)
        for n, pf in [("Low", 50.0), ("High", 300.0), ("Mid", 120.0), ("Second", 200.0)]
    ]
    assert report_data._build_season_leaders(rows, {1: []}, week=1) is None
    leaders = report_data._build_season_leaders(rows, {1: [], 2: []}, week=2)
    assert leaders.top_teams == [("High", 300.0), ("Second", 200.0), ("Mid", 120.0)]
    assert leaders.top_scorers == []
