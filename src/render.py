"""Jinja2 + WeasyPrint: WeekReport -> styled PDF."""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from .report_data import WeekReport

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def clean_team_name(name: str) -> str:
    """ESPN team names sometimes carry stray leading/trailing/doubled whitespace."""
    return re.sub(r"\s+", " ", name).strip()


def asset_exists(relative_path: str) -> bool:
    """Checks a template-relative asset path against disk — lets the template fall back to
    generated graphics (e.g. the wax seal) when an optional asset like the league logo hasn't
    been supplied yet, rather than silently rendering a broken image."""
    return bool(relative_path) and (TEMPLATE_DIR / relative_path).is_file()


def render_html(report: WeekReport, league_config: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    env.filters["clean_team_name"] = clean_team_name
    env.globals["asset_exists"] = asset_exists
    template = env.get_template("report.html.jinja")
    return template.render(report=report, league=league_config)


def render_pdf(report: WeekReport, league_config: dict, output_path: str | Path) -> Path:
    html_str = render_html(report, league_config)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str, base_url=str(TEMPLATE_DIR)).write_pdf(str(output_path))
    return output_path
