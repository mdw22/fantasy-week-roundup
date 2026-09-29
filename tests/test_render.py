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


def _body(html):
    return html.split("</style>")[1]


def test_appendix_a_renders_season_table_only_when_present():
    rep = _report([_row("A", None)])
    assert "Appendix A" not in _body(render.render_html(rep, LEAGUE))
    rep.season_table = [stats.SeasonTeamRow(
        team_name="Alpha", wins=2, losses=1, ties=0, all_play_wins=30, all_play_losses=9,
        points_for=345.6, points_against=300.0, average=115.2, high=140.1, low=90.0,
        bench_points_lost=22.5, last_week_max_points=161.3, beat_projection=2, weeks=3,
    )]
    html = _body(render.render_html(rep, LEAGUE))
    assert "Appendix A: 2026 Season Stats" in html
    assert "30-9" in html and "345.60" in html and "22.50" in html and "2 of 3" in html
    assert "Wk 2 Max" in html and "161.30" in html


def test_appendix_b_renders_lifetime_sections():
    from src import history

    rep = _report([_row("A", None)])
    assert "Appendix B" not in _body(render.render_html(rep, LEAGUE))
    rep.lifetime = history.LifetimeStats(
        first_season=2022, last_season=2026,
        managers=[
            history.ManagerRecord("1", "Ann Active", "Alpha", True, 5, 40, 20, 1, 7000.0, 61, 2, 4),
            history.ManagerRecord("2", "Old Timer", "Gone FC", False, 2, 10, 18, 0, 3000.0, 28, 0, 0),
        ],
        champions=[history.Champion(2022, "Ann Active", "Alpha")],
        rivalries=[history.Rivalry("Ann Active", "Alpha", "Old Timer", "4-0", None, "")],
        record_book=[history.RecordEntry("Biggest blowout", "88.10", "Ann Active", "Alpha", "2023 Week 5", "over Old Timer")],
    )
    html = _body(render.render_html(rep, LEAGUE))
    assert "Appendix B: Lifetime Stats" in html and "2022–2026" in html
    assert "40-20-1" in html and "0.664" in html
    assert 'class="former"' in html and "Gone FC" in html
    assert "Champions" in html and "Record Book" in html and "Rivalry Summary" in html
    assert "88.10" in html and "over Old Timer" in html and "(4-0)" in html
    assert "<th>Best Record Against</th>" in html and "Owns" not in html


def test_waiver_report_card_renders_grades_bench_tag_and_regrets():
    from src import waivers

    rep = _report([_row("A", None)])
    assert "Waiver Report Card" not in _body(render.render_html(rep, LEAGUE))
    rep.waiver_report_card = waivers.WaiverReportCard(
        adds=[
            waivers.GradedAdd("Alpha", "Hot Pickup", "WR", "SF", 24.3, True, "A", "rostered", "Alpha"),
            waivers.GradedAdd("Beta", "Bench Guy", "RB", "DAL", 3.0, False, "D", "dropped", None),
            waivers.GradedAdd("Beta", "Flipped", "TE", "KC", 1.0, None, "D", "elsewhere", "Gamma"),
        ],
        regrets=[waivers.RegretDrop("Beta", "Oops", "TE", "KC", 19.5)],
        drops=2,
    )
    html = _body(render.render_html(rep, LEAGUE))
    assert "Week 2 Waiver Report Card" in html and "after Week 1 ended" in html
    assert 'class="grade grade-a"' in html and 'class="grade grade-d"' in html
    assert html.count(">Bench<") == 1 and "24.30" in html
    assert "Current Status" in html and "On Roster" in html and ">Dropped<" in html and "On Gamma" in html
    assert "Drops That Bit Back" in html and "19.50" in html

    rep.waiver_report_card = waivers.WaiverReportCard([], [], 0)
    html = _body(render.render_html(rep, LEAGUE))
    assert "No pickups this week" in html and "Drops That Bit Back" not in html


def test_suggested_pickups_render():
    from src import waivers

    rep = _report([_row("A", None)])
    assert "Suggested Pickups" not in _body(render.render_html(rep, LEAGUE))
    rep.pickups = [
        waivers.Pickup(1, "Backup Back", "RB", "DAL", 11.2, 44.5, 6.1),
        waivers.Pickup(2, "Plain Kicker", "K", "SF", 7.0, 3.0, None),
    ]
    html = _body(render.render_html(rep, LEAGUE))
    assert "Suggested Pickups for Week 3" in html
    assert "Why" not in html
    assert "44.5%" in html and "11.20" in html


def test_preview_renders_projections_picks_cards_and_part_labels():
    from src import preview

    def ctx(name, seed):
        return preview.TeamContext(name, name[:3].upper(), f"Mgr {name}", name, 2, 1, 0, "2W", seed, 111.1, "W 120.00–99.50")

    home = preview.PreviewSide(ctx("Alpha", 1), 120.5, [preview.PlayerLine("Star", "WR", "SF", 22.4)],
                               [preview.PlayerLine("Hobbled", "RB", "DAL", 9.0, "Questionable"),
                                preview.PlayerLine("Parked", "WR", "LAR", 0.0, "Questionable", in_ir_slot=True)])
    away = preview.PreviewSide(ctx("Beta", 9), 101.0, [], [])
    m = preview.MatchupPreview(home, away, (1, 3, 0))
    rep = _report([_row("A", None)])
    html = _body(render.render_html(rep, LEAGUE))
    assert "Preview" not in html and "part-label" not in html
    rep.preview = preview.Preview(3, [m], [preview.PreviewPick("Blowout Watch", m, "Widest projected margin of the week: 19.50 points.")],
                                  bold_prediction="Beta wins by 30.")
    html = _body(render.render_html(rep, LEAGUE))
    assert "I. Week 2 Review" in html and "II. Week 3 Preview" in html
    assert "Week 3 Projected Scores" in html and "120.50" in html
    assert html.count('class="proj-label"') == 4  # scoreboard row + card, both sides
    assert 'class="matchup projected"' in html and "home-winner" not in html
    assert "IR slot" in html
    assert "Blowout Watch" in html and "19.50 points" in html
    assert "Bold Prediction" in html and "Beta wins by 30." in html
    assert "Week 3 Matchup Analysis" in html and "Mgr Alpha" in html and "No. 9" in html
    assert 'class="flag flag-questionable"' in html and "All clear" in html
    assert "Alpha favored by 19.50" in html and "Beta leads the series 3-1" in html


def test_letter_is_the_last_section():
    from src import history

    rep = _report([_row("A", None)])
    rep.lifetime = history.LifetimeStats(2025, 2026, [], [], [], [])
    html = _body(render.render_html(rep, LEAGUE))
    assert html.index("Appendix B") < html.index("Raven From")


def test_standard_mode_hides_appendices_but_keeps_everything_else():
    from src import history, preview

    rep = _report([_row("A", None)])
    rep.season_table = [stats.SeasonTeamRow(
        team_name="Alpha", wins=2, losses=1, ties=0, all_play_wins=30, all_play_losses=9,
        points_for=345.6, points_against=300.0, average=115.2, high=140.1, low=90.0,
        bench_points_lost=22.5, last_week_max_points=161.3, beat_projection=2, weeks=3,
    )]
    rep.lifetime = history.LifetimeStats(2025, 2026, [], [history.Champion(2025, "Ann", "Alpha")], [], [])

    def ctx(name):
        return preview.TeamContext(name, name[:3].upper(), f"Mgr {name}", name, 2, 1, 0, "2W", 1, 111.1, "")

    m = preview.MatchupPreview(preview.PreviewSide(ctx("Alpha"), 120.5, [], []),
                               preview.PreviewSide(ctx("Beta"), 101.0, [], []), (1, 3, 0))
    rep.preview = preview.Preview(3, [m], [])
    from src import waivers

    rep.waiver_report_card = waivers.WaiverReportCard(
        [waivers.GradedAdd("Alpha", "Graded Guy", "WR", "SF", 24.3, True, "A", "rostered", "Alpha")], [], 0,
    )
    rep.pickups = [
        waivers.Pickup(1, "Best QB", "QB", "SF", 18.0, 3.0, 20.0), waivers.Pickup(2, "Second QB", "QB", "SF", 16.0, 3.0, 9.0),
        waivers.Pickup(3, "Best K", "K", "SF", 9.0, 3.0, 8.0), waivers.Pickup(4, "Second K", "K", "SF", 8.5, 3.0, 7.0),
    ]

    rep.big_report = False
    standard = _body(render.render_html(rep, LEAGUE))
    assert "Appendix A" not in standard and "Appendix B" not in standard
    assert "Weekly Recap" in standard and "Big Edition" not in standard
    assert "Beta leads the series 3-1" in standard and "Raven From" in standard
    # Waivers: one pickup per position, no graded card, no full list.
    assert "Week 3 Waiver Report" in standard and "Best QB" in standard and "Best K" in standard
    assert "Second QB" not in standard and "Waiver Report Card" not in standard and "Suggested Pickups" not in standard
    # Compact matchup cards with a takeaway instead of the full cards.
    assert "Week 3 Matchups" in standard and 'class="card compact"' in standard
    assert "Matchup Analysis" not in standard and "Alpha favored by 19.50" in standard
    assert standard.index("Waiver Report") < standard.index("Projected Scores")

    rep.big_report = True
    big = _body(render.render_html(rep, LEAGUE))
    assert "Appendix A" in big and "Appendix B" in big and "Big Edition" in big
    assert "Waiver Report Card" in big and "Suggested Pickups" in big and "Second QB" in big
    assert "Matchup Analysis" in big and "card compact" not in big
