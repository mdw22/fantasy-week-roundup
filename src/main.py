"""CLI entry point: python -m src.main [--week N]"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import espn_client, narrative, render, report_data

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
REPORTS_DIR = BASE_DIR / "reports"


def load_league_config() -> dict:
    path = CONFIG_DIR / "league.yaml"
    if not path.exists():
        path = CONFIG_DIR / "league.yaml.example"
    with open(path) as f:
        return yaml.safe_load(f)


def generate_report(week: int | None = None) -> Path:
    load_dotenv(BASE_DIR / ".env")

    league = espn_client.connect()
    league_config = load_league_config()

    report = report_data.build_week_report(
        league,
        week=week,
        power_rankings_override_path=CONFIG_DIR / "power_rankings_override.yaml",
    )

    lore_path = CONFIG_DIR / "lore.md"
    report.commissioners_letter = narrative.generate_commissioners_letter(
        report,
        theme=league_config["narrative_theme"],
        commissioner_name=league_config["commissioner_name"],
        lore_path=lore_path,
    )
    narrative.append_lore_entry(
        lore_path, report.week, narrative.summarize_matchups_for_lore(report)
    )

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
    args = parser.parse_args()

    output_path = generate_report(week=args.week)
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
