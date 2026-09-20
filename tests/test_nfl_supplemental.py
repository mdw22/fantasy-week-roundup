"""Unit tests for the pure helpers in src/nfl_supplemental.py -- no nflreadpy network calls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import nfl_supplemental as nfl_sup


def test_is_gamecock_matches_whole_entries_only():
    assert nfl_sup._is_gamecock("South Carolina")
    assert nfl_sup._is_gamecock("Oregon; South Carolina")  # transfers count
    assert nfl_sup._is_gamecock("South Carolina; Arkansas")
    assert not nfl_sup._is_gamecock("South Carolina State")
    assert not nfl_sup._is_gamecock("North Carolina")
    assert not nfl_sup._is_gamecock("East Carolina; South Carolina State")
    assert not nfl_sup._is_gamecock(None)
    assert not nfl_sup._is_gamecock("")


def test_score_and_describe_defender_sums_tackles_and_blocks():
    row = {
        "def_tackles_solo": 5, "def_tackle_assists": 1,
        "def_sacks": 1.0, "def_fg_blocks": 1, "def_punt_blocks": 0, "def_pat_blocks": None,
    }
    score, detail = nfl_sup.score_and_describe(row)
    assert score == 4.0 * 1 + 2.0 * 1 + 1.0 * 6
    assert detail == "Blocked kick, Sack, 6 tkl"


def test_score_and_describe_singular_capitalization_keeps_acronyms():
    _, detail = nfl_sup.score_and_describe({"def_interceptions": 1, "def_fumbles_forced": 1})
    assert detail == "INT, FF"


def test_score_and_describe_half_sack_is_not_truncated():
    _, detail = nfl_sup.score_and_describe({"def_sacks": 0.5, "def_tackles_solo": 5})
    assert detail == "0.5 sack, 5 tkl"


def test_score_and_describe_kicker_blocked_fg_is_ignored():
    # `fg_blocked` is a kicker's own kick being blocked; it must never score for anyone.
    score, detail = nfl_sup.score_and_describe({"fg_blocked": 2})
    assert score == 0.0
    assert detail == "no notable stat line"


def test_score_and_describe_offense_uses_tds_and_yards():
    row = {"receiving_tds": 1, "receptions": 6, "receiving_yards": 80}
    score, detail = nfl_sup.score_and_describe(row)
    assert score == 6.0 + 0.5 * 6 + 0.1 * 80
    assert detail == "Rec TD, 6 rec"


def test_espn_team_abbr_maps_nflverse_codes_that_differ():
    assert nfl_sup.espn_team_abbr("LA") == "LAR"
    assert nfl_sup.espn_team_abbr("WAS") == "WSH"
    assert nfl_sup.espn_team_abbr("MIA") == "MIA"
    assert nfl_sup.espn_team_abbr(None) == ""
