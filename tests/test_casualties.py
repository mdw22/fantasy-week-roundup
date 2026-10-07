"""Unit tests for src/casualties.py (season-long Casualty Report) against fake box-score players."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import casualties
from tests.test_stats import FakeBoxScore, FakePlayer, FakeTeam


def _p(name, pid, slot="RB", played=True, status="ACTIVE", bye=False, position="RB", week=1):
    p = FakePlayer(name, position, 10.0, slot, player_id=pid)
    p.injuryStatus, p.on_bye_week = status, bye
    p.stats = {week: {"breakdown": {casualties.GAMES_PLAYED_STAT: 1.0} if played else {}}}
    return p


def _weeks(*weekly_lineups):
    """weekly_lineups: one (home lineup, away lineup) per week, weeks numbered from 1."""
    return {
        w: [FakeBoxScore(FakeTeam("Home"), 100, 100, FakeTeam("Away"), 90, 90, list(home), list(away))]
        for w, (home, away) in enumerate(weekly_lineups, start=1)
    }


def _report(box_scores_by_week, designations=None, reserve=None, left=None, drafted=None, order=("Home", "Away")):
    return casualties.casualty_report(
        box_scores_by_week, designations or {}, reserve or {}, left or {}, drafted or {}, 16, list(order),
    )


def test_same_player_out_three_weeks_is_one_starter_three_weeks_affected():
    star = lambda w, slot: _p("Star", 1, slot=slot, played=w == 1, week=w)
    bsw = _weeks(([star(1, "RB")], []), ([star(2, "BE")], []), ([star(3, "BE")], []), ([star(4, "BE")], []))
    rep = _report(bsw, designations={2: {1: "Out"}, 3: {1: "Out"}, 4: {1: "Doubtful"}})
    [row] = rep.rows
    assert (row.starters_hurt, row.weeks_affected, rep.weeks_played) == (1, 3, 4)
    assert row.games_missed == 3  # internal tiebreak only
    assert row.this_week and row.this_week[0].name == "Star"


def test_two_players_out_the_same_week_count_that_week_once():
    bsw = _weeks(
        ([_p("A", 1, week=1), _p("B", 2, week=1)], []),
        ([_p("A", 1, played=False, week=2), _p("B", 2, played=False, week=2)], []),
        ([_p("A", 1, played=False, week=3), _p("B", 2, week=3)], []),
    )
    rep = _report(bsw, designations={2: {1: "Out", 2: "Out"}, 3: {1: "Out"}})
    [row] = rep.rows
    assert (row.starters_hurt, row.weeks_affected, row.games_missed) == (2, 2, 3)


def test_weeks_affected_never_exceeds_weeks_played():
    # Three starters, each out every week: lots of player-games, but only 3 weeks.
    lineups = [([_p(n, i, played=False, week=w) for i, n in enumerate("ABC", start=1)], []) for w in (1, 2, 3)]
    rep = _report(_weeks(*lineups), designations={w: {1: "Out", 2: "Out", 3: "Out"} for w in (1, 2, 3)},
                  drafted={i: ("Home", 1) for i in (1, 2, 3)})
    [row] = rep.rows
    assert row.games_missed == 9 and row.weeks_affected == 3 <= rep.weeks_played


def test_regular_starter_on_ir_slot_counts_each_week_out():
    bsw = _weeks(
        ([_p("Star", 1, week=1)], []),
        ([_p("Star", 1, slot="IR", played=False, status="INJURY_RESERVE", week=2)], []),
        ([_p("Star", 1, slot="IR", played=False, status="INJURY_RESERVE", week=3)], []),
    )
    rep = _report(bsw, reserve={2: {1}, 3: {1}})
    assert rep.rows[0].weeks_affected == 2 and rep.rows[0].biggest_loss.status_word == "IR"


def test_top_draft_pick_counts_before_ever_starting():
    bsw = _weeks(([_p("Hurt Rookie", 1, slot="IR", played=False, week=1)], []))
    rep = _report(bsw, designations={1: {1: "Out"}}, drafted={1: ("Home", 2)})
    assert rep.rows[0].games_missed == 1
    late = _report(bsw, designations={1: {1: "Out"}}, drafted={1: ("Home", 12)})
    assert late.rows == []  # a late pick who never started isn't a regular starter


def test_bench_player_who_never_started_does_not_count():
    bsw = _weeks(([_p("Backup", 1, slot="BE", played=False)], []), ([_p("Backup", 1, slot="BE", played=False, week=2)], []))
    rep = _report(bsw, designations={1: {1: "Out"}, 2: {1: "Out"}})
    assert rep.rows == []


def test_questionable_player_who_played_and_byes_do_not_count():
    bsw = _weeks(
        ([_p("Gutsy", 1, status="QUESTIONABLE")], []),
        ([_p("Gutsy", 1, played=False, bye=True, status="QUESTIONABLE", week=2)], []),
    )
    rep = _report(bsw, designations={1: {1: "Questionable"}, 2: {1: "Questionable"}})
    assert rep.rows == []


def test_one_play_exit_healthy_the_next_week_does_not_count():
    bsw = _weeks(([_p("Breather", 1)], []), ([_p("Breather", 1, week=2)], []))
    assert _report(bsw, left={1: {1}}).rows == []
    # ...but if he then misses the next game, both weeks count.
    bsw = _weeks(([_p("Hurt", 1)], []), ([_p("Hurt", 1, played=False, week=2)], []))
    rep = _report(bsw, left={1: {1}}, designations={2: {1: "Out"}})
    assert rep.rows[0].games_missed == 2


def test_latest_week_exit_uses_todays_espn_status():
    hurt = _weeks(([_p("Hurt", 1, status="QUESTIONABLE")], []))
    assert _report(hurt, left={1: {1}}).rows[0].games_missed == 1
    healthy = _weeks(([_p("Fine", 1, status="ACTIVE")], []))
    assert _report(healthy, left={1: {1}}).rows == []


def test_draft_position_breaks_ties_and_undrafted_is_last():
    bsw = _weeks((
        [_p("Pickup", 1, played=False)],
        [_p("Star", 2, played=False)],
    ))
    rep = _report(bsw, designations={1: {1: "Out", 2: "Out"}}, drafted={2: ("Away", 1)})
    assert [r.team_name for r in rep.rows] == ["Away", "Home"]
    assert rep.rows[0].biggest_loss.draft_label == "1st-round pick"
    assert rep.rows[1].biggest_loss.draft_label == "undrafted"


def test_biggest_loss_is_earliest_pick_and_team_with_no_games_missed_is_omitted():
    bsw = _weeks(([_p("Late", 1, played=False), _p("Early", 2, played=False)], [_p("Fine", 3)]))
    rep = _report(bsw, designations={1: {1: "Out", 2: "Out"}}, drafted={1: ("Home", 9), 2: ("Home", 3)})
    [row] = rep.rows
    assert row.biggest_loss.name == "Early" and row.starters_hurt == 2 and rep.unaffected_teams == 1


def test_more_starters_hurt_outranks_draft_position_then_standings_order():
    bsw = _weeks((
        [_p("A", 1, played=False), _p("B", 2, played=False)],
        [_p("Star", 3, played=False)],
    ))
    rep = _report(bsw, designations={1: {1: "Out", 2: "Out", 3: "Out"}}, drafted={3: ("Away", 1)})
    assert [r.team_name for r in rep.rows] == ["Home", "Away"]
    tie = _weeks(([_p("A", 1, played=False)], [_p("B", 2, played=False)]))
    rep = _report(tie, designations={1: {1: "Out", 2: "Out"}}, order=("Away", "Home"))
    assert [r.team_name for r in rep.rows] == ["Away", "Home"]


def test_dst_status_list_shape_is_handled():
    bsw = _weeks(([_p("Defense", 1, status=[], position="D/ST", slot="D/ST")], []))
    assert _report(bsw, left={1: {1}}).rows == []


def test_surname_skips_suffixes():
    assert casualties.PlayerToll(1, "Travis Etienne Jr.", "RB", None).surname == "Etienne"
    assert casualties.PlayerToll(1, "Saquon Barkley", "RB", None).surname == "Barkley"


def test_visible_rows_respect_row_and_height_caps():
    def row(n_this_week):
        players = [casualties.PlayerToll(i, f"P{i}", "RB", None, weeks={4}, this_week=True) for i in range(n_this_week)]
        return casualties.TeamToll("T", players or [casualties.PlayerToll(9, "Old", "RB", None, weeks={1})])

    rep = casualties.CasualtyReport([row(3), row(2), row(0), row(1)], 0, 4, 4)
    assert [len(r.this_week) for r in rep.visible_rows(6, 14)] == [3, 2, 0, 1]  # 3.6+2.6+1.6+1.6
    assert [len(r.this_week) for r in rep.visible_rows(6, 6.2)] == [3, 2]
    assert [len(r.this_week) for r in rep.visible_rows(2, 14)] == [3, 2]
    assert [len(r.this_week) for r in rep.visible_rows(6, 1)] == [3]  # the worst-hit team always shows
