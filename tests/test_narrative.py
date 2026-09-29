"""Unit tests for the pure parsing/combining logic in src/narrative.py — no API calls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narrative


def test_split_response_with_both_markers():
    raw = (
        "Once upon a time in the realm...\n\nThe end.\n\n"
        f"{narrative.LORE_NOTE_MARKER}\n"
        "Coined the nickname 'the Iron Bank' for the waiver wire.\n\n"
        f"{narrative.NICKNAME_MARKER}\n"
        'Patrick Mahomes | QB | Lord "The Dragon" Patrick Mahomes'
    )
    letter, note, nicknames_text, bold = narrative.split_response(raw)
    assert letter == "Once upon a time in the realm...\n\nThe end."
    assert note == "Coined the nickname 'the Iron Bank' for the waiver wire."
    assert nicknames_text == 'Patrick Mahomes | QB | Lord "The Dragon" Patrick Mahomes'
    assert bold == ""  # a draft from before the Bold Prediction existed


def test_split_response_with_only_lore_marker():
    # Older-format draft, or a hand-edit that dropped the nicknames section entirely.
    raw = f"A letter.\n\n{narrative.LORE_NOTE_MARKER}\nA lore note."
    letter, note, nicknames_text, bold = narrative.split_response(raw)
    assert letter == "A letter."
    assert note == "A lore note."
    assert nicknames_text == ""


def test_split_response_without_any_marker():
    raw = "Just a letter with no marker at all."
    letter, note, nicknames_text, bold = narrative.split_response(raw)
    assert letter == "Just a letter with no marker at all."
    assert note == ""
    assert nicknames_text == ""


def test_split_response_reads_bold_prediction_in_any_order():
    raw = (
        f"The letter.\n\n{narrative.LORE_NOTE_MARKER}\nA note.\n\n"
        f"{narrative.BOLD_PREDICTION_MARKER}\nHouse Stark wins by 40.\n\n"
        f"{narrative.NICKNAME_MARKER}\nnothing new"
    )
    assert narrative.split_response(raw) == ("The letter.", "A note.", "nothing new", "House Stark wins by 40.")
    only_bold = f"The letter.\n{narrative.BOLD_PREDICTION_MARKER}\nA call."
    assert narrative.split_response(only_bold) == ("The letter.", "", "", "A call.")


def test_bold_prediction_text_collapses_whitespace_and_drops_sentinel():
    assert narrative.bold_prediction_text("  House Stark\nwins by 40.  ") == "House Stark wins by 40."
    assert narrative.bold_prediction_text("nothing new") is None
    assert narrative.bold_prediction_text("") is None


def test_week_summary_includes_next_week_only_with_a_preview():
    from datetime import date

    from src import preview, report_data

    rep = report_data.WeekReport(
        week=3, season_year=2026, league_name="L", report_date=date(2026, 9, 29), is_season_finale=False,
        matchups=[], standings=[], team_highlights={}, individual_highlights={},
    )
    assert "next_week" not in narrative.build_week_summary(rep)

    def ctx(name):
        return preview.TeamContext(name, name[:3], "Mgr", name, 2, 1, 0, "2W", 1, 110.0, "W 1.00–0.00")

    home = preview.PreviewSide(ctx("Alpha"), 120.0, [preview.PlayerLine("Star", "WR", "SF", 20.0)],
                               [preview.PlayerLine("Hurt", "RB", "SF", 5.0, "Out")])
    m = preview.MatchupPreview(home, preview.PreviewSide(ctx("Beta"), 100.0, [], []), (3, 1, 0))
    rep.preview = preview.Preview(4, [m], [preview.PreviewPick("Blowout Watch", m, "Wide.")])
    nw = narrative.build_week_summary(rep)["next_week"]
    assert nw["week"] == 4 and nw["matchups"][0]["all_time_series"] == "Alpha 3-1 Beta"
    assert nw["matchups"][0]["home"]["lineup_concerns"] == [
        {"player": "Hurt", "position": "RB", "status": "Out", "in_ir_slot": False}
    ]
    assert nw["preview_highlights"][0]["category"] == "Blowout Watch"


def test_combine_lore_summary_with_real_note():
    combined = narrative.combine_lore_summary(
        "House A beat House B 100.0-90.0", "Coined 'the Iron Bank' for the waiver wire."
    )
    assert combined == "House A beat House B 100.0-90.0 — Coined 'the Iron Bank' for the waiver wire."


def test_combine_lore_summary_nothing_new():
    combined = narrative.combine_lore_summary(
        "House A beat House B 100.0-90.0", "Nothing new to carry forward."
    )
    assert combined == "House A beat House B 100.0-90.0"


def test_combine_lore_summary_empty_note():
    combined = narrative.combine_lore_summary("House A beat House B 100.0-90.0", "")
    assert combined == "House A beat House B 100.0-90.0"


def test_parse_new_nicknames_parses_well_formed_lines():
    text = (
        'Patrick Mahomes | QB | Lord "The Dragon" Patrick Mahomes\n'
        'Derrick Henry | RB | Knight "The Butcher" Derrick Henry'
    )
    result = narrative.parse_new_nicknames(text)
    assert result == {
        "Patrick Mahomes": {"position": "QB", "nickname": 'Lord "The Dragon" Patrick Mahomes'},
        "Derrick Henry": {"position": "RB", "nickname": 'Knight "The Butcher" Derrick Henry'},
    }


def test_parse_new_nicknames_nothing_new_sentinel_is_empty():
    assert narrative.parse_new_nicknames("nothing new") == {}
    assert narrative.parse_new_nicknames("Nothing new to carry forward.") == {}
    assert narrative.parse_new_nicknames("") == {}
    assert narrative.parse_new_nicknames("   ") == {}


def test_parse_new_nicknames_skips_malformed_lines():
    text = "This line has no pipes at all\nPatrick Mahomes | QB | Lord \"The Dragon\" Patrick Mahomes\nToo | Many | Pipe | Fields"
    result = narrative.parse_new_nicknames(text)
    assert list(result) == ["Patrick Mahomes"]


def test_format_nickname_registry_empty():
    assert "none established" in narrative.format_nickname_registry({})


def test_format_nickname_registry_lists_each_entry():
    registry = {
        "Patrick Mahomes": {"position": "QB", "nickname": 'Lord "The Dragon" Patrick Mahomes', "established_week": 3},
    }
    text = narrative.format_nickname_registry(registry)
    assert text == '- Patrick Mahomes (QB): Lord "The Dragon" Patrick Mahomes'


def test_append_nicknames_seeds_a_new_file(tmp_path):
    path = tmp_path / "nicknames.yaml"
    narrative.append_nicknames(
        path, {"Patrick Mahomes": {"position": "QB", "nickname": 'Lord "The Dragon" Patrick Mahomes'}}, week=3
    )
    assert path.exists()
    assert "Legendary player nicknames" in path.read_text()
    registry = narrative.read_nicknames(path)
    assert registry["Patrick Mahomes"]["nickname"] == 'Lord "The Dragon" Patrick Mahomes'
    assert registry["Patrick Mahomes"]["established_week"] == 3


def test_append_nicknames_never_overwrites_an_established_nickname(tmp_path):
    path = tmp_path / "nicknames.yaml"
    path.write_text('Patrick Mahomes:\n  position: QB\n  nickname: Lord "The Original" Mahomes\n  established_week: 1\n')
    before = path.read_text()

    narrative.append_nicknames(
        path, {"Patrick Mahomes": {"position": "QB", "nickname": 'Lord "A New One" Mahomes'}}, week=5
    )

    assert path.read_text() == before  # byte-for-byte unchanged


def test_append_nicknames_appends_new_players_and_keeps_existing_content(tmp_path):
    path = tmp_path / "nicknames.yaml"
    original = '# my own header\nPatrick Mahomes:\n  position: QB\n  nickname: Lord "The Dragon" Patrick Mahomes\n  established_week: 1\n'
    path.write_text(original)

    narrative.append_nicknames(
        path, {"Derrick Henry": {"position": "RB", "nickname": 'Knight "The Butcher" Derrick Henry'}}, week=5
    )

    text = path.read_text()
    assert text.startswith(original)
    registry = narrative.read_nicknames(path)
    assert registry["Patrick Mahomes"]["established_week"] == 1
    assert registry["Derrick Henry"]["established_week"] == 5


def test_append_nicknames_noop_with_no_new_nicknames(tmp_path):
    path = tmp_path / "nicknames.yaml"
    narrative.append_nicknames(path, {}, week=3)
    assert not path.exists()
