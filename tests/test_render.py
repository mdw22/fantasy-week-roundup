"""Render-level checks: build a minimal WeekReport and inspect the HTML the template produces."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import render, report_data, stats

LEAGUE = {
    "league_name": "Test League",
    "commissioner_name": "House Test",
    "narrative_theme": "x",
    "team_nickname_overrides": {},
    "logo_path": "assets/does_not_exist.png",
    "seal_monogram": "T",
}


def _row(name, power_change, commissioner_change=None):
    return report_data.StandingsRow(
        team_name=name, division_name="Div", wins=1, losses=0, ties=0, points_for=100.0,
        points_against=90.0, streak="1W", playoff_pct=50.0, power_rank=3, commissioner_rank=3,
        power_rank_change=power_change, commissioner_rank_change=commissioner_change,
    )


def _report(standings, score_bars=None):
    return report_data.WeekReport(
        week=2, season_year=2026, league_name="Test League", report_date=date(2026, 9, 20),
        is_season_finale=False, matchups=[], standings=standings, team_highlights={},
        individual_highlights={}, score_bars=score_bars or [], commissioners_letter="Hi.",
    )


def test_rank_movement_markers_render_up_down_same_and_none():
    html = render.render_html(
        _report([_row("Up", 2), _row("Down", -3), _row("Same", 0), _row("Fresh", None)]), LEAGUE
    )
    assert 'class="move up"' in html and 'class="tri up"' in html
    assert 'class="move down"' in html and 'class="tri down"' in html
    assert 'class="move same"' in html
    assert html.count('class="move ') == 3  # "Fresh" (no prior value) gets no marker at all


def test_week_one_style_report_has_no_movement_markers_anywhere():
    html = render.render_html(_report([_row("A", None), _row("B", None)]), LEAGUE)
    assert 'class="move ' not in html


def test_score_chart_renders_heading_rows_and_winner_styling():
    bars = [stats.ScoreBar("Winners", 150.0, True, 100.0), stats.ScoreBar("Losers", 75.0, False, 50.0)]
    html = render.render_html(_report([_row("A", None)], score_bars=bars), LEAGUE)
    assert "Week 2 at a Glance" in html
    assert 'class="chart-bar won"' in html and 'class="chart-bar lost"' in html
    assert "150.00" in html and "75.00" in html
    empty = render.render_html(_report([_row("A", None)]), LEAGUE)
    assert '<h3 class="subhead">' not in empty and 'class="chart-row"' not in empty  # no bars -> no block


def test_season_leaders_block_renders_only_when_present():
    leaders = report_data.SeasonLeaders(
        top_teams=[("Alpha", 300.0), ("Beta", 250.0), ("Gamma", 200.0)],
        top_scorers=[stats.SeasonScorer("Star Player", "Alpha", "SF", "WR", 88.5)],
    )
    rep = _report([_row("A", None)])
    assert "Season Leaders" not in render.render_html(rep, LEAGUE).split("</style>")[1]
    rep.season_leaders = leaders
    html = render.render_html(rep, LEAGUE)
    assert "Season Leaders" in html.split("</style>")[1]
    assert "Top Teams" in html and "Top Scorers" in html
    assert "Star Player" in html and "88.50" in html and "300.00" in html
