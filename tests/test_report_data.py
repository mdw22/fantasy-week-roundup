"""Unit tests for the pure helpers in src/report_data.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import report_data


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
