"""Report-mode selection in src/main.py (Standard Weekly vs Big Report)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import main


def test_scheduled_weeks_are_big_and_others_standard():
    config = {"big_report_weeks": [3, 8]}
    assert [main.is_big_report(config, w) for w in (3, 4, 7, 8)] == [True, False, False, True]


def test_cli_override_beats_the_schedule():
    config = {"big_report_weeks": [8]}
    assert main.is_big_report(config, 8, override=False) is False
    assert main.is_big_report(config, 5, override=True) is True


def test_no_schedule_means_standard():
    assert main.is_big_report({}, 8) is False
    assert main.is_big_report({"big_report_weeks": None}, 8) is False
