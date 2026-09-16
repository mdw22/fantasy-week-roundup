"""Unit tests for the pure parsing/combining logic in src/narrative.py — no API calls."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narrative


def test_split_letter_and_lore_note_with_marker():
    raw = (
        "Once upon a time in the realm...\n\nThe end.\n\n"
        f"{narrative.LORE_NOTE_MARKER}\n"
        "Coined the nickname 'the Iron Bank' for the waiver wire."
    )
    letter, note = narrative.split_letter_and_lore_note(raw)
    assert letter == "Once upon a time in the realm...\n\nThe end."
    assert note == "Coined the nickname 'the Iron Bank' for the waiver wire."


def test_split_letter_and_lore_note_without_marker():
    raw = "Just a letter with no marker at all."
    letter, note = narrative.split_letter_and_lore_note(raw)
    assert letter == "Just a letter with no marker at all."
    assert note == ""


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
