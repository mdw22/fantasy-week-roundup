"""Unit tests for the pure helpers in src/report_data.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import report_data


class _FakeTeam:
    def __init__(self, name):
        self.team_name = name


class _FakeLeague:
    """Minimal stand-in for espn_api's League -- ensure_power_rankings_override only ever calls
    .power_rankings(week=...), same shape espn_client.get_power_rankings expects: an ordered list
    of (score_str, Team), best team first."""

    def __init__(self, rankings=None):
        self._rankings = rankings if rankings is not None else [
            ("28.35", _FakeTeam("House Stark")),
            ("21.15", _FakeTeam(" Trailing Space Team ")),
            ("19.85", _FakeTeam("Kegorators ! ")),
        ]

    def power_rankings(self, week):
        return self._rankings


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


def test_ensure_power_rankings_override_seeds_a_new_file(tmp_path):
    path = tmp_path / "power_rankings_override.yaml"
    report_data.ensure_power_rankings_override(_FakeLeague(), 2, path)

    assert path.exists()
    assert "Commissioner" in path.read_text()  # header comment made it in
    assert report_data.load_power_rankings_override(path, 2) == {
        "House Stark": 1, " Trailing Space Team ": 2, "Kegorators ! ": 3,
    }


def test_ensure_power_rankings_override_leaves_an_existing_week_untouched(tmp_path):
    path = tmp_path / "power_rankings_override.yaml"
    path.write_text("week_2:\n  \"House Stark\": 14\n  \"Kegorators ! \": 1\n")  # hand-edited, upset order
    before = path.read_text()

    league = _FakeLeague()  # would give House Stark rank 1, not 14 -- must not overwrite
    report_data.ensure_power_rankings_override(league, 2, path)

    assert path.read_text() == before  # byte-for-byte unchanged
    assert report_data.load_power_rankings_override(path, 2) == {"House Stark": 14, "Kegorators ! ": 1}


def test_ensure_power_rankings_override_appends_new_week_and_keeps_existing_content(tmp_path):
    path = tmp_path / "power_rankings_override.yaml"
    original = "# my own notes up top\nweek_1:\n  \"House Stark\": 5\n"
    path.write_text(original)

    report_data.ensure_power_rankings_override(_FakeLeague(), 2, path)

    text = path.read_text()
    assert text.startswith(original)  # week_1 block and the comment survive verbatim
    assert report_data.load_power_rankings_override(path, 1) == {"House Stark": 5}
    assert report_data.load_power_rankings_override(path, 2) == {
        "House Stark": 1, " Trailing Space Team ": 2, "Kegorators ! ": 3,
    }


def test_ensure_power_rankings_override_noop_without_a_path():
    class _ExplodingLeague:
        def power_rankings(self, week):
            raise AssertionError("must not be called when path is falsy")

    report_data.ensure_power_rankings_override(_ExplodingLeague(), 2, None)  # no exception
