"""Unit tests for src/preview.py: matchup cards and the rule-based highlight picks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import preview
from tests.test_stats import FakeBoxScore, FakePlayer, FakeTeam


def _ctx(name, wins, losses, seed, average, owner=None):
    return preview.TeamContext(
        team_name=name, abbrev=name[:3].upper(), manager=f"Mgr {name}", owner_id=owner or name,
        wins=wins, losses=losses, ties=0, streak="1W", seed=seed, average=average, last_result="W 1.00–0.00",
    )


def _player(name, slot, projected, status="ACTIVE", bye=False, position="WR"):
    p = FakePlayer(name, position, 0.0, slot, projected_points=projected)
    p.injuryStatus, p.on_bye_week = status, bye
    return p


def test_side_top_players_and_flags_cover_starters_only():
    lineup = [
        _player("Star", "WR", 20.0), _player("Solid", "RB", 12.0, status="QUESTIONABLE"),
        _player("Depth", "TE", 8.0), _player("Filler", "K", 5.0, bye=True),
        _player("Bench Stud", "BE", 30.0, status="OUT"), _player("Hurt", "IR", 0.0, status="INJURY_RESERVE"),
        _player("Defense", "D/ST", 4.0, status=[]),  # espn_api's D/ST status shape
        _player("Maybe Back", "IR", 0.0, status="QUESTIONABLE"),
    ]
    side = preview.preview_side(_ctx("A", 1, 0, 1, 100), 90.0, lineup)
    assert [p.name for p in side.top_players] == ["Star", "Solid", "Depth"]
    assert [(p.name, p.flag, p.in_ir_slot) for p in side.flagged] == [
        ("Solid", "Questionable", False), ("Filler", "Bye", False), ("Maybe Back", "Questionable", True),
    ]


def test_matchup_previews_carry_projections_and_head_to_head():
    a, b = FakeTeam("A"), FakeTeam("B")
    contexts = {"A": _ctx("A", 2, 1, 3, 110), "B": _ctx("B", 1, 2, 9, 120)}
    calls = []

    def h2h(x, y):
        calls.append((x, y))
        return (3, 1, 0)

    [m] = preview.matchup_previews([FakeBoxScore(a, 0, 101.5, b, 0, 96.0)], contexts, h2h)
    assert m.favorite.team.team_name == "A" and m.underdog.team.team_name == "B"
    assert round(m.gap, 2) == 5.5 and m.head_to_head == (3, 1, 0) and calls == [("A", "B")]
    [m] = preview.matchup_previews([FakeBoxScore(a, 0, 101.5, b, 0, 96.0)], contexts)
    assert m.head_to_head is None


def _matchup(home, away, home_proj, away_proj):
    return preview.MatchupPreview(
        preview.PreviewSide(home, home_proj, [], []), preview.PreviewSide(away, away_proj, [], []),
    )


def test_picks_are_distinct_and_follow_their_rules():
    top = _matchup(_ctx("Unbeaten", 3, 0, 1, 130), _ctx("Also Good", 2, 1, 2, 125), 120, 118)
    bubble = _matchup(_ctx("Eighth", 2, 1, 8, 110), _ctx("Ninth", 1, 2, 9, 108), 105, 104)
    upset = _matchup(_ctx("Fav", 1, 2, 11, 95), _ctx("Dog", 1, 2, 12, 112), 110, 100)
    rout = _matchup(_ctx("Juggernaut", 2, 1, 3, 120), _ctx("Doormat", 0, 3, 14, 80), 140, 80)
    picks = {p.label: p for p in preview.pick_highlights([top, bubble, upset, rout], playoff_spots=8)}

    assert list(picks) == ["Game of the Week", "Blowout Watch", "Upset Alert", "Biggest Playoff Implications"]
    assert picks["Game of the Week"].matchup is top
    assert picks["Biggest Playoff Implications"].matchup is bubble
    assert picks["Biggest Playoff Implications"].reason == (
        "No. 8 (2-1) vs. No. 9 (1-2), 1 game back of the 8th seed; the top 8 make the playoffs."
    )
    assert picks["Upset Alert"].matchup is upset and picks["Upset Alert"].team_name == "Dog"
    assert "averages 17.00 more points" in picks["Upset Alert"].reason
    assert picks["Blowout Watch"].matchup is rout and "60.00" in picks["Blowout Watch"].reason


def test_upset_alert_falls_back_to_closest_unused_game_and_playoff_pick_is_optional():
    close = _matchup(_ctx("A", 2, 1, 1, 100), _ctx("B", 2, 1, 2, 90), 100, 99)
    wide = _matchup(_ctx("C", 0, 3, 3, 100), _ctx("D", 0, 3, 4, 90), 130, 90)
    third = _matchup(_ctx("E", 1, 2, 5, 100), _ctx("F", 1, 2, 6, 90), 110, 100)
    picks = {p.label: p for p in preview.pick_highlights([close, wide, third], 8, include_playoff_pick=False)}
    assert "Biggest Playoff Implications" not in picks
    assert picks["Game of the Week"].matchup is close
    assert picks["Upset Alert"].matchup is third and picks["Upset Alert"].reason == "Projected to lose by just 10.00."
    assert picks["Blowout Watch"].matchup is wide


def test_no_matchups_no_picks():
    assert preview.pick_highlights([], 8) == []


def test_closeness_bands_by_projected_gap():
    def gap(g):
        return _matchup(_ctx("A", 1, 1, 1, 100), _ctx("B", 1, 1, 2, 100), 100 + g, 100).closeness

    assert [gap(0.4), gap(2.99), gap(3.0), gap(9.99), gap(10.0), gap(40)] == [
        "toss-up", "toss-up", "edge", "edge", "clear", "clear",
    ]
