"""CLI entry point: python -m src.main [--week N] [--draft-only] [--letter-file PATH]"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import espn_client, narrative, render, report_data
from .report_data import WeekReport

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
REPORTS_DIR = BASE_DIR / "reports"
DRAFTS_DIR = BASE_DIR / "drafts"


def load_league_config() -> dict:
    path = CONFIG_DIR / "league.yaml"
    if not path.exists():
        path = CONFIG_DIR / "league.yaml.example"
    with open(path) as f:
        return yaml.safe_load(f)


def _connect_and_build_report(week: int | None) -> tuple[WeekReport, dict]:
    load_dotenv(BASE_DIR / ".env")
    league = espn_client.connect()
    league_config = load_league_config()
    report = report_data.build_week_report(
        league,
        week=week,
        power_rankings_override_path=CONFIG_DIR / "power_rankings_override.yaml",
    )
    return report, league_config


def generate_letter_draft(week: int | None = None) -> tuple[Path, int]:
    """Generate the Commissioner's Letter and write it to a plain-text draft file for manual
    editing, without touching the lore file, the nickname registry, or rendering a PDF. Pair with
    --letter-file once you're happy with the edits. Returns (draft_path, resolved_week).

    The draft file includes the trailing lore-note and nicknames sections (marked with
    narrative.LORE_NOTE_MARKER / narrative.NICKNAME_MARKER) below the letter — they're there to
    review/edit too, since they're what get folded into config/lore.md and config/nicknames.yaml
    for next week's continuity. --letter-file parses them back out, so leaving either in place (or
    editing it) both work; deleting a section just means nothing gets recorded there for the week."""
    report, league_config = _connect_and_build_report(week)
    letter, lore_note, nicknames_text = narrative.generate_commissioners_letter(
        report,
        theme=league_config["narrative_theme"],
        commissioner_name=league_config["commissioner_name"],
        lore_path=CONFIG_DIR / "lore.md",
        nicknames_path=CONFIG_DIR / "nicknames.yaml",
    )
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = DRAFTS_DIR / f"week_{report.week}_{report.season_year}_letter.txt"
    draft_contents = letter
    if lore_note:
        draft_contents += f"\n\n{narrative.LORE_NOTE_MARKER}\n{lore_note}"
    if nicknames_text:
        draft_contents += f"\n\n{narrative.NICKNAME_MARKER}\n{nicknames_text}"
    draft_path.write_text(draft_contents)
    return draft_path, report.week


def generate_report(week: int | None = None, letter_file: str | Path | None = None) -> Path:
    report, league_config = _connect_and_build_report(week)

    if letter_file:
        report.commissioners_letter, lore_note, nicknames_text = narrative.split_response(
            Path(letter_file).read_text()
        )
    else:
        report.commissioners_letter, lore_note, nicknames_text = narrative.generate_commissioners_letter(
            report,
            theme=league_config["narrative_theme"],
            commissioner_name=league_config["commissioner_name"],
            lore_path=CONFIG_DIR / "lore.md",
            nicknames_path=CONFIG_DIR / "nicknames.yaml",
        )

    factual_summary = narrative.summarize_matchups_for_lore(report)
    lore_summary = narrative.combine_lore_summary(factual_summary, lore_note)
    narrative.append_lore_entry(CONFIG_DIR / "lore.md", report.week, lore_summary)
    new_nicknames = narrative.parse_new_nicknames(nicknames_text)
    narrative.append_nicknames(CONFIG_DIR / "nicknames.yaml", new_nicknames, report.week)

    output_path = REPORTS_DIR / f"week_{report.week}_{report.season_year}.pdf"
    render.render_pdf(report, league_config, output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate the weekly ESPN fantasy recap PDF.")
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Explicit week override (default: most recently completed week)",
    )
    parser.add_argument(
        "--draft-only",
        action="store_true",
        help="Write the Commissioner's Letter to a text file for editing and stop there "
        "(no lore update, no PDF)",
    )
    parser.add_argument(
        "--letter-file",
        type=str,
        default=None,
        help="Use this file's contents as the Commissioner's Letter instead of generating one "
        "(e.g. a draft from --draft-only that you've edited)",
    )
    args = parser.parse_args()

    if args.draft_only:
        draft_path, resolved_week = generate_letter_draft(week=args.week)
        print(f"Letter draft written to {draft_path}")
        print(f"Edit it, then run: python -m src.main --week {resolved_week} --letter-file {draft_path}")
        return

    output_path = generate_report(week=args.week, letter_file=args.letter_file)
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
