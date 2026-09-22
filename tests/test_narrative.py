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
    letter, note, nicknames_text = narrative.split_response(raw)
    assert letter == "Once upon a time in the realm...\n\nThe end."
    assert note == "Coined the nickname 'the Iron Bank' for the waiver wire."
    assert nicknames_text == 'Patrick Mahomes | QB | Lord "The Dragon" Patrick Mahomes'


def test_split_response_with_only_lore_marker():
    # Older-format draft, or a hand-edit that dropped the nicknames section entirely.
    raw = f"A letter.\n\n{narrative.LORE_NOTE_MARKER}\nA lore note."
    letter, note, nicknames_text = narrative.split_response(raw)
    assert letter == "A letter."
    assert note == "A lore note."
    assert nicknames_text == ""


def test_split_response_without_any_marker():
    raw = "Just a letter with no marker at all."
    letter, note, nicknames_text = narrative.split_response(raw)
    assert letter == "Just a letter with no marker at all."
    assert note == ""
    assert nicknames_text == ""


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
