"""Unit tests for src/stats.py against lightweight fixtures that mimic espn_api's
Team/BoxScore/Player attribute shapes (see src/espn_client.py's probe notes),
without depending on espn_api itself or a live connection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import nfl_supplemental, stats


class FakeTeam:
    def __init__(self, team_name, outcomes=None):
        self.team_name = team_name
        self.outcomes = outcomes or []


class FakePlayer:
    def __init__(self, name, position, points, lineup_slot, pro_team="NFL", player_id=None):
        self.playerId = player_id
        self.name = name
        self.position = position
        self.points = points
        self.lineupSlot = lineup_slot
        self.proTeam = pro_team


class FakeBoxScore:
    def __init__(
        self,
        home_team,
        home_score,
        home_projected,
        away_team,
        away_score,
        away_projected,
        home_lineup=None,
        away_lineup=None,
    ):
        self.home_team = home_team
        self.home_score = home_score
        self.home_projected = home_projected
        self.away_team = away_team
        self.away_score = away_score
        self.away_projected = away_projected
        self.home_lineup = home_lineup or []
        self.away_lineup = away_lineup or []


def make_box_scores():
    house_stark = FakeTeam("House Stark")
    house_lannister = FakeTeam("House Lannister")
    house_targaryen = FakeTeam("House Targaryen")
    house_greyjoy = FakeTeam("House Greyjoy")

    bs1 = FakeBoxScore(
        home_team=house_stark,
        home_score=120.5,
        home_projected=100.0,
        away_team=house_lannister,
        away_score=90.0,
        away_projected=110.0,
        home_lineup=[
            FakePlayer("Jon Snow", "QB", 30.0, "QB"),
            FakePlayer("Robb Stark", "RB", 15.0, "BE"),
        ],
        away_lineup=[
            FakePlayer("Tyrion Lannister", "WR", 25.0, "WR"),
        ],
    )
    bs2 = FakeBoxScore(
        home_team=house_targaryen,
        home_score=95.0,
        home_projected=105.0,
        away_team=house_greyjoy,
        away_score=94.0,
        away_projected=80.0,
        home_lineup=[
            FakePlayer("Daenerys Targaryen", "QB", 20.0, "QB"),
        ],
        away_lineup=[
            FakePlayer("Theon Greyjoy", "RB", 40.0, "RB"),
            FakePlayer("Yara Greyjoy", "TE", 5.0, "BE"),
        ],
    )
    return [bs1, bs2]


def test_team_scores():
    box_scores = make_box_scores()
    scores = stats.team_scores(box_scores)
    assert scores["House Stark"] == 120.5
    assert scores["House Greyjoy"] == 94.0


def test_best_worst_team():
    box_scores = make_box_scores()
    best, worst = stats.best_worst_team(box_scores)
    assert best.team_name == "House Stark"
    assert worst.team_name == "House Lannister"


def test_most_improved_biggest_dropoff():
    current = {"House Stark": 120.5, "House Lannister": 90.0}
    prior = {"House Stark": 80.0, "House Lannister": 130.0}
    improved, dropoff = stats.most_improved_biggest_dropoff(current, prior)
    assert improved.team_name == "House Stark"
    assert dropoff.team_name == "House Lannister"


def test_most_improved_biggest_dropoff_no_prior_week():
    improved, dropoff = stats.most_improved_biggest_dropoff({"House Stark": 100.0}, {})
    assert improved is None
    assert dropoff is None


def test_closest_win_biggest_blowout():
    box_scores = make_box_scores()
    closest, blowout = stats.closest_win_biggest_blowout(box_scores)
    assert closest.team_name == "House Targaryen"
    assert closest.value == 1.0
    assert blowout.team_name == "House Stark"
    assert blowout.value == 30.5


def test_streak_ending_at():
    outcomes = ["W", "W", "L", "W", "W", "W"]
    result, length = stats.streak_ending_at(outcomes, 6)
    assert result == "W"
    assert length == 3

    result, length = stats.streak_ending_at(outcomes, 3)
    assert result == "L"
    assert length == 1


def test_streak_ending_at_unplayed_week():
    result, length = stats.streak_ending_at(["W", "U", "U"], 2)
    assert result == ""
    assert length == 0


def test_longest_streaks():
    teams = [
        FakeTeam("House Stark", outcomes=["W", "W", "W"]),
        FakeTeam("House Lannister", outcomes=["L", "L", "L", "L"]),
        FakeTeam("House Targaryen", outcomes=["W", "L", "W"]),
    ]
    win_streak, loss_streak = stats.longest_streaks(teams, 4)
    assert win_streak.team_name == "House Stark"
    assert win_streak.value == 3
    assert loss_streak.team_name == "House Lannister"
    assert loss_streak.value == 4


def test_biggest_upset():
    box_scores = make_box_scores()
    upset = stats.biggest_upset(box_scores)
    # House Greyjoy was projected to lose by 25 but won by 1 -> upset.
    # House Lannister was favored by 10 but lost by 30.5 -> also an upset, bigger swing.
    assert upset.team_name == "House Stark"


def test_biggest_underachiever():
    box_scores = make_box_scores()
    underachiever = stats.biggest_underachiever(box_scores)
    assert underachiever.team_name == "House Lannister"
    assert underachiever.value == -20.0


def test_individual_mvp():
    box_scores = make_box_scores()
    mvp = stats.individual_mvp(box_scores)
    assert mvp.player_name == "Theon Greyjoy"
    assert mvp.points == 40.0


def test_top_scorer_by_position():
    box_scores = make_box_scores()
    top = stats.top_scorer_by_position(box_scores)
    assert top["QB"].player_name == "Jon Snow"
    assert top["RB"].player_name == "Theon Greyjoy"
    assert "TE" not in top  # Yara Greyjoy was benched


def test_bench_mvp():
    box_scores = make_box_scores()
    bench = stats.bench_mvp(box_scores)
    assert bench.player_name == "Robb Stark"
    assert bench.points == 15.0


def _rookie_gamecock_box_scores():
    return [
        FakeBoxScore(
            home_team=FakeTeam("House Stark"), home_score=0, home_projected=0,
            away_team=FakeTeam("House Lannister"), away_score=0, away_projected=0,
            home_lineup=[
                FakePlayer("Vet Starter", "QB", 40.0, "QB", player_id=1),
                FakePlayer("Bench Rookie", "RB", 18.0, "BE", player_id=2),
            ],
            away_lineup=[
                FakePlayer("Starter Rookie", "WR", 12.0, "WR", player_id=3),
                FakePlayer("No Id Player", "TE", 50.0, "TE"),
            ],
        )
    ]


def _rookie(name, points, espn_id, position="WR", pro_team="MIA"):
    return nfl_supplemental.RookieCandidate(
        espn_id=espn_id, name=name, position=position, pro_team=pro_team, points=points
    )


def test_rookie_spotlight_picks_highest_league_wide_and_credits_rostering_team():
    # id 2 is a benched rookie on House Stark; id 3 a starter on House Lannister
    result = stats.rookie_spotlight(
        _rookie_gamecock_box_scores(), [_rookie("Bench Rookie", 18.0, 2), _rookie("Starter Rookie", 12.0, 3)]
    )
    assert result.player_name == "Bench Rookie"
    assert result.team_name == "House Stark"
    assert result.points == 18.0
    assert result.pro_team == "MIA" and result.position == "WR"


def test_rookie_spotlight_unrostered_rookie_can_win_and_has_no_team():
    result = stats.rookie_spotlight(
        _rookie_gamecock_box_scores(), [_rookie("Free Agent Rookie", 30.0, 999), _rookie("Bench Rookie", 18.0, 2)]
    )
    assert result.player_name == "Free Agent Rookie"
    assert result.team_name is None


def test_rookie_spotlight_none_without_candidates():
    assert stats.rookie_spotlight(_rookie_gamecock_box_scores(), []) is None


def _candidate(name, score, espn_id):
    return nfl_supplemental.GamecockCandidate(
        espn_id=espn_id, name=name, position="LB", pro_team="SEA", score=score, detail="13 tkl"
    )


def test_gamecock_of_the_week_credits_rostering_team_and_carries_detail():
    result = stats.gamecock_of_the_week(
        _rookie_gamecock_box_scores(), [_candidate("Low", 5.0, 1), _candidate("High", 13.0, 3)]
    )
    assert result.player_name == "High"
    assert result.team_name == "House Lannister"
    assert result.detail == "13 tkl"


def test_gamecock_of_the_week_unrostered_has_no_team():
    result = stats.gamecock_of_the_week(_rookie_gamecock_box_scores(), [_candidate("Free", 9.0, 777)])
    assert result.team_name is None


def test_gamecock_of_the_week_missing_espn_id_never_matches_id_less_roster_player():
    # "No Id Player" has playerId None on the roster; a candidate with espn_id None must not match it.
    result = stats.gamecock_of_the_week(_rookie_gamecock_box_scores(), [_candidate("Nobody", 9.0, None)])
    assert result.team_name is None


def test_gamecock_of_the_week_none_without_candidates():
    assert stats.gamecock_of_the_week(_rookie_gamecock_box_scores(), []) is None
